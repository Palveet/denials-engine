from __future__ import annotations

import asyncio
import os
import uuid
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import SessionLocal
from app.decide.facts import build_fact_sheet
from app.decide.llm import ModelDecisionError, decide_fact_sheet, get_client
from app.constants import PROMPT_VERSION
from app.ingest.clearinghouse import parse_clearinghouse_csv
from app.ingest.merge import merge_claims
from app.ingest.x12_835 import parse_835
from app.models import (
    AdjustmentRecord,
    ArtifactRecord,
    ClaimRecord,
    DecisionRecord,
    DenialRecord,
    RunRecord,
    ServiceLineRecord,
)
from app.output.documents import generate_fax_packet
from app.output.handoff import generate_handoff
from app.schemas import ClaimData, DenialData, IngestSummary, ValidatedDecision


ARTIFACT_BASE = Path(os.getenv("ARTIFACT_DIR", "artifacts"))


def _decimal(value) -> Decimal:
    return Decimal(str(value))


def ingest_run(
    session: Session,
    era_text: str,
    csv_text: str,
    *,
    as_of_date: date,
) -> IngestSummary:
    era = parse_835(era_text)
    csv_claims = parse_clearinghouse_csv(csv_text)
    claims = merge_claims(era.claims, csv_claims)
    run_id = str(uuid.uuid4())
    run = RunRecord(id=run_id, status="uploaded", as_of_date=as_of_date, bpr_total=era.bpr_total)
    session.add(run)

    for claim in claims:
        record = ClaimRecord(
            run=run,
            claim_id=claim.claim_id,
            payer_claim_ref=claim.payer_claim_ref,
            patient_name=claim.patient_name,
            member_id=claim.member_id,
            payer_name=claim.payer_name,
            date_of_service=claim.date_of_service,
            billed_amount=claim.billed_amount,
            paid_amount=claim.paid_amount,
            patient_responsibility=claim.patient_responsibility,
            claim_status_835=claim.claim_status_835,
            clearinghouse_ref=claim.clearinghouse_ref,
            sources=[source.value for source in claim.sources],
            discrepancies=[item.model_dump(mode="json") for item in claim.discrepancies],
            normalized_json=claim.model_dump(mode="json"),
        )
        session.add(record)
        session.flush()
        lines: dict[int, ServiceLineRecord] = {}
        for line in claim.service_lines:
            line_record = ServiceLineRecord(
                claim=record,
                sequence=line.sequence,
                hcpcs=line.hcpcs,
                billed_amount=line.billed_amount,
                paid_amount=line.paid_amount,
                units=line.units,
                service_date=line.service_date,
            )
            session.add(line_record)
            session.flush()
            lines[line.sequence] = line_record
            for adjustment in line.adjustments:
                session.add(
                    AdjustmentRecord(
                        claim=record,
                        service_line=line_record,
                        group_code=adjustment.group_code,
                        carc=adjustment.carc,
                        amount=adjustment.amount,
                        rarcs=adjustment.rarcs,
                        source=adjustment.source.value,
                    )
                )
        for adjustment in claim.claim_adjustments:
            session.add(
                AdjustmentRecord(
                    claim=record,
                    group_code=adjustment.group_code,
                    carc=adjustment.carc,
                    amount=adjustment.amount,
                    rarcs=adjustment.rarcs,
                    source=adjustment.source.value,
                )
            )
        denial_records: list[DenialRecord] = []
        for denial in claim.denials:
            denial_record = DenialRecord(
                claim=record,
                service_line=lines.get(denial.service_line_sequence or -1),
                group_code=denial.group_code,
                carc=denial.carc,
                rarcs=denial.rarcs,
                payer_reason_text=denial.payer_reason_text,
                denied_amount=denial.denied_amount,
                source=denial.source,
                clearinghouse_ref=denial.clearinghouse_ref,
            )
            session.add(denial_record)
            denial_records.append(denial_record)
        session.flush()
        if denial_records:
            for denial_record in denial_records:
                session.add(DecisionRecord(claim=record, denial=denial_record, status="pending"))
        else:
            # The prompt requires an outcome for every claim, including paid/no-action claims.
            session.add(DecisionRecord(claim=record, status="pending"))
    session.commit()
    return IngestSummary(
        run_id=run_id,
        era_claims=len(era.claims),
        csv_claims=len(csv_claims),
        normalized_claims=len(claims),
        denials=sum(len(claim.denials) for claim in claims),
        decision_work_items=sum(max(1, len(claim.denials)) for claim in claims),
        overlapping_claims=sum(len(claim.sources) > 1 for claim in claims),
        discrepancy_count=sum(len(claim.discrepancies) for claim in claims),
        bpr_total=era.bpr_total,
        as_of_date=as_of_date,
    )


def _denial_data(record: DenialRecord | None) -> DenialData | None:
    if record is None:
        return None
    return DenialData(
        group_code=record.group_code,
        carc=record.carc,
        rarcs=record.rarcs or [],
        payer_reason_text=record.payer_reason_text,
        denied_amount=record.denied_amount,
        source=record.source,
        clearinghouse_ref=record.clearinghouse_ref,
        service_line_sequence=record.service_line.sequence if record.service_line else None,
    )


async def _process_decision(decision_id: int, client, semaphore: asyncio.Semaphore) -> None:
    async with semaphore:
        with SessionLocal() as session:
            decision = session.scalar(
                select(DecisionRecord)
                .where(DecisionRecord.id == decision_id)
                .options(
                    selectinload(DecisionRecord.claim),
                    selectinload(DecisionRecord.denial).selectinload(DenialRecord.service_line),
                )
            )
            if not decision:
                return
            claim_data = ClaimData.model_validate(decision.claim.normalized_json)
            facts = build_fact_sheet(
                claim_data,
                _denial_data(decision.denial),
                as_of_date=decision.claim.run.as_of_date,
            )
            decision.status = "deciding"
            decision.fact_sheet = facts
            session.commit()
        try:
            result = await decide_fact_sheet(client, facts)
        except ModelDecisionError as exc:
            with SessionLocal() as session:
                decision = session.get(DecisionRecord, decision_id)
                if decision:
                    decision.status = "failed"
                    decision.rationale = str(exc)
                    decision.confidence = Decimal("0")
                    decision.llm_raw = exc.raw
                    decision.validator_flags = [exc.flag]
                    decision.model_name = exc.model_name
                    decision.prompt_version = PROMPT_VERSION
                    session.commit()
            raise
        with SessionLocal() as session:
            decision = session.get(DecisionRecord, decision_id)
            if not decision:
                return
            decision.status = "decided"
            decision.outcome = result.outcome.value
            decision.next_action = result.next_action.value
            decision.actor = result.actor.value
            decision.fax_required = result.fax_required
            decision.rationale = result.rationale
            decision.confidence = Decimal(str(result.confidence))
            decision.llm_raw = result.llm_raw
            decision.validator_flags = result.validator_flags
            decision.model_name = result.model_name
            decision.prompt_version = result.prompt_version
            session.commit()


def _validated(record: DecisionRecord) -> ValidatedDecision:
    return ValidatedDecision(
        outcome=record.outcome,
        next_action=record.next_action,
        actor=record.actor,
        fax_required=bool(record.fax_required),
        rationale=record.rationale or "No rationale supplied.",
        confidence=float(record.confidence or 0),
        validator_flags=record.validator_flags or [],
        llm_raw=record.llm_raw or {},
        model_name=record.model_name or "unknown",
        prompt_version=record.prompt_version or "unknown",
    )


def generate_run_artifacts(run_id: str, *, output_dir: Path | None = None) -> None:
    target = output_dir or (ARTIFACT_BASE / "runs" / run_id)
    target.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as session:
        run = session.scalar(
            select(RunRecord)
            .where(RunRecord.id == run_id)
            .options(
                selectinload(RunRecord.claims)
                .selectinload(ClaimRecord.decisions)
                .selectinload(DecisionRecord.denial)
                .selectinload(DenialRecord.service_line)
            )
        )
        if not run:
            raise ValueError(f"Run {run_id} not found")
        rows: list[dict] = []
        for claim in sorted(run.claims, key=lambda item: item.claim_id):
            claim_data = ClaimData.model_validate(claim.normalized_json)
            artifact_names: list[str] = []
            decisions = sorted(claim.decisions, key=lambda item: item.id)
            for decision in decisions:
                if decision.fax_required and decision.denial:
                    html_path, pdf_path, pages = generate_fax_packet(
                        claim_data,
                        _denial_data(decision.denial),
                        _validated(decision),
                        output_dir=target,
                        packet_date=run.as_of_date,
                    )
                    artifact_names.append(pdf_path.name)
                    session.add(
                        ArtifactRecord(
                            run=run,
                            decision=decision,
                            claim_business_id=claim.claim_id,
                            kind="fax_packet",
                            file_path=str(pdf_path),
                            preview_path=str(html_path),
                            page_count=pages,
                        )
                    )
            denied_amount = sum((_decimal(item.denial.denied_amount) for item in decisions if item.denial), Decimal("0"))
            rows.append(
                {
                    "claim_id": claim.claim_id,
                    "patient": claim.patient_name,
                    "date_of_service": claim.date_of_service.isoformat(),
                    "denied_amount": f"{denied_amount:.2f}",
                    "outcome": "; ".join(item.outcome or "pending" for item in decisions),
                    "next_step": "; ".join(item.next_action or "pending" for item in decisions),
                    "actor": "; ".join(item.actor or "pending" for item in decisions),
                    "confidence": "; ".join(str(item.confidence or "") for item in decisions),
                    "validator_flags": "; ".join(
                        dict.fromkeys(flag for item in decisions for flag in (item.validator_flags or []))
                    ),
                    "source_discrepancies": "; ".join(
                        dict.fromkeys(item["field"] for item in (claim.discrepancies or []))
                    ),
                    "artifacts": "; ".join(artifact_names),
                }
            )
        handoff_html, handoff_csv = generate_handoff(rows, target)
        for kind, path in (("handoff_html", handoff_html), ("handoff_csv", handoff_csv)):
            session.add(ArtifactRecord(run=run, kind=kind, file_path=str(path)))
        session.flush()
        zip_path = target / "all-artifacts.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(target.iterdir()):
                if path.is_file() and path != zip_path:
                    archive.write(path, arcname=path.name)
        session.add(ArtifactRecord(run=run, kind="all_artifacts_zip", file_path=str(zip_path)))
        session.commit()


async def process_run(run_id: str, *, output_dir: Path | None = None) -> None:
    with SessionLocal() as session:
        run = session.get(RunRecord, run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")
        run.status = "running"
        run.error = None
        decision_ids = list(
            session.scalars(
                select(DecisionRecord.id)
                .join(ClaimRecord)
                .where(ClaimRecord.run_id == run_id)
                .order_by(DecisionRecord.id)
            )
        )
        session.commit()
    try:
        client = get_client()
        semaphore = asyncio.Semaphore(4)
        tasks = [
            asyncio.create_task(_process_decision(item_id, client, semaphore))
            for item_id in decision_ids
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        errors: list[BaseException] = []
        for task in done:
            try:
                task.result()
            except BaseException as exc:
                errors.append(exc)
        if errors:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            raise errors[0]
        if pending:
            await asyncio.gather(*pending)
        generate_run_artifacts(run_id, output_dir=output_dir)
        with SessionLocal() as session:
            run = session.get(RunRecord, run_id)
            run.status = "completed"
            session.commit()
    except Exception as exc:
        with SessionLocal() as session:
            run = session.get(RunRecord, run_id)
            if run:
                run.status = "failed"
                run.error = str(exc)
                session.commit()
        raise


def run_status(session: Session, run_id: str) -> dict | None:
    run = session.get(RunRecord, run_id)
    if not run:
        return None
    decisions = list(
        session.scalars(
            select(DecisionRecord)
            .join(ClaimRecord)
            .where(ClaimRecord.run_id == run_id)
            .options(selectinload(DecisionRecord.claim), selectinload(DecisionRecord.denial))
            .order_by(ClaimRecord.claim_id, DecisionRecord.id)
        )
    )
    return {
        "run_id": run_id,
        "status": run.status,
        "total": len(decisions),
        "completed": sum(item.status == "decided" for item in decisions),
        "error": run.error,
        "items": [
            {
                "decision_id": item.id,
                "claim_id": item.claim.claim_id,
                "code": (
                    f"{item.denial.group_code}-{item.denial.carc or 'missing'}" if item.denial else "no denial"
                ),
                "status": item.status,
            }
            for item in decisions
        ],
    }
