from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_session, init_db
from app.decide.policy import policy_view
from app.models import ArtifactRecord, ClaimRecord, DecisionRecord, RunRecord
from app.service import ingest_run, process_run, run_status


app = FastAPI(title="Mini Denials Engine", version="1.0.0")


@app.on_event("startup")
def startup() -> None:
    init_db()
    Path("artifacts/runs").mkdir(parents=True, exist_ok=True)


class RunRequest(BaseModel):
    run_id: str


def _decode_upload(data: bytes, name: str) -> str:
    limit = int(os.getenv("MAX_UPLOAD_BYTES", "5000000"))
    if not data:
        raise HTTPException(400, f"{name} is empty")
    if len(data) > limit:
        raise HTTPException(413, f"{name} exceeds the {limit}-byte upload limit")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(400, f"{name} must be UTF-8 text") from exc


@app.get("/api/health")
def health() -> dict:
    model_name = os.getenv("LLM_MODEL", "")
    api_key_configured = bool(os.getenv("ANTHROPIC_API_KEY", "").strip())
    return {
        "status": "ok",
        "llm_provider": "anthropic",
        "llm_configured": api_key_configured and bool(model_name.strip()),
        "llm_model": model_name,
        "current_date": date.today().isoformat(),
    }


@app.post("/api/upload")
async def upload(
    era_file: UploadFile = File(...),
    csv_file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict:
    if not (era_file.filename or "").lower().endswith(".835"):
        raise HTTPException(400, "The ERA filename must end in .835")
    if not (csv_file.filename or "").lower().endswith(".csv"):
        raise HTTPException(400, "The clearinghouse filename must end in .csv")
    era_text = _decode_upload(await era_file.read(), "ERA file")
    csv_text = _decode_upload(await csv_file.read(), "CSV file")
    try:
        summary = ingest_run(session, era_text, csv_text, as_of_date=date.today())
    except ValueError as exc:
        session.rollback()
        raise HTTPException(422, str(exc)) from exc
    return summary.model_dump(mode="json")


@app.post("/api/run")
async def run_agent(
    request: RunRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict:
    if not os.getenv("ANTHROPIC_API_KEY", "").strip():
        raise HTTPException(503, "The model API key is not configured. Add ANTHROPIC_API_KEY to .env and restart the app.")
    if not os.getenv("LLM_MODEL", "").strip():
        raise HTTPException(503, "LLM_MODEL is not configured. Add the exact provider model ID to .env and restart the app.")
    run = session.get(RunRecord, request.run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status not in {"uploaded", "failed"}:
        raise HTTPException(409, f"Run is already {run.status}")
    background_tasks.add_task(process_run, request.run_id)
    return {"run_id": request.run_id, "status": "queued"}


@app.get("/api/run/{run_id}/status")
def get_run_status(run_id: str, session: Session = Depends(get_session)) -> dict:
    result = run_status(session, run_id)
    if result is None:
        raise HTTPException(404, "Run not found")
    return result


@app.get("/api/claims")
def get_claims(run_id: str, session: Session = Depends(get_session)) -> list[dict]:
    claims = list(
        session.scalars(
            select(ClaimRecord)
            .where(ClaimRecord.run_id == run_id)
            .options(selectinload(ClaimRecord.decisions).selectinload(DecisionRecord.denial))
            .order_by(ClaimRecord.claim_id)
        )
    )
    return [
        {
            **claim.normalized_json,
            "decisions": [
                {
                    "id": decision.id,
                    "status": decision.status,
                    "outcome": decision.outcome,
                    "next_action": decision.next_action,
                    "actor": decision.actor,
                    "fax_required": decision.fax_required,
                    "rationale": decision.rationale,
                    "confidence": float(decision.confidence) if decision.confidence is not None else None,
                    "validator_flags": decision.validator_flags,
                    "fact_sheet": decision.fact_sheet,
                    "llm_raw": decision.llm_raw,
                    "model_name": decision.model_name,
                    "prompt_version": decision.prompt_version,
                    "denial_id": decision.denial_id,
                    "policy": policy_view(
                        decision.fact_sheet or {},
                        outcome=decision.outcome or "",
                        next_action=decision.next_action or "",
                        actor=decision.actor or "",
                        fax_required=bool(decision.fax_required),
                        validator_flags=decision.validator_flags or [],
                    ),
                }
                for decision in sorted(claim.decisions, key=lambda item: item.id)
            ],
        }
        for claim in claims
    ]


@app.get("/api/artifacts")
def get_artifacts(run_id: str, session: Session = Depends(get_session)) -> list[dict]:
    artifacts = list(
        session.scalars(
            select(ArtifactRecord)
            .where(ArtifactRecord.run_id == run_id)
            .order_by(ArtifactRecord.claim_business_id, ArtifactRecord.kind)
        )
    )
    return [
        {
            "id": artifact.id,
            "claim_id": artifact.claim_business_id,
            "kind": artifact.kind,
            "download_url": f"/api/artifact/{artifact.id}",
            "preview_url": f"/api/artifact/{artifact.id}/preview" if artifact.preview_path else None,
            "page_count": artifact.page_count,
        }
        for artifact in artifacts
    ]


def _artifact_or_404(session: Session, artifact_id: int) -> ArtifactRecord:
    artifact = session.get(ArtifactRecord, artifact_id)
    if not artifact:
        raise HTTPException(404, "Artifact not found")
    return artifact


@app.get("/api/artifact/{artifact_id}")
def download_artifact(artifact_id: int, session: Session = Depends(get_session)):
    artifact = _artifact_or_404(session, artifact_id)
    path = Path(artifact.file_path).resolve()
    if not path.is_file():
        raise HTTPException(404, "Artifact file is missing")
    return FileResponse(path, filename=path.name)


@app.get("/api/artifact/{artifact_id}/preview")
def preview_artifact(artifact_id: int, session: Session = Depends(get_session)):
    artifact = _artifact_or_404(session, artifact_id)
    if not artifact.preview_path:
        raise HTTPException(404, "Preview is not available")
    path = Path(artifact.preview_path).resolve()
    if not path.is_file():
        raise HTTPException(404, "Preview file is missing")
    return FileResponse(path, media_type="text/html")


frontend_dist = Path("app/static")
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
