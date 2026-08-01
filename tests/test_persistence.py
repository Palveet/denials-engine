from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

import app.service as service
from app.database import make_engine
from app.decide.llm import ModelDecisionError
from app.models import ArtifactRecord, Base, ClaimRecord, DecisionRecord, DenialRecord, RunRecord
from app.service import ingest_run, process_run


DATA = Path(__file__).parents[1] / "data"


def test_ingest_persists_run_scoped_normalized_graph():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        summary = ingest_run(
            session,
            (DATA / "sample.835").read_text(),
            (DATA / "denials_export.csv").read_text(),
            as_of_date=date(2026, 7, 28),
        )
        assert summary.normalized_claims == 12
        assert session.scalar(select(func.count()).select_from(ClaimRecord)) == 12
        assert session.scalar(select(func.count()).select_from(DenialRecord)) == 10
        assert session.scalar(select(func.count()).select_from(DecisionRecord)) == 12


class FailingProvider:
    model_name = "failure-test"

    async def complete(self, fact_sheet, validation_error=None):
        raise RuntimeError("provider unavailable")


@pytest.mark.asyncio
async def test_provider_failure_fails_run_and_generates_no_artifacts(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'failure.db'}")
    Base.metadata.create_all(engine)
    test_sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    monkeypatch.setattr(service, "SessionLocal", test_sessions)
    monkeypatch.setattr(service, "get_client", lambda: FailingProvider())

    with test_sessions() as session:
        summary = ingest_run(
            session,
            (DATA / "sample.835").read_text(),
            (DATA / "denials_export.csv").read_text(),
            as_of_date=date(2026, 7, 28),
        )

    with pytest.raises(ModelDecisionError):
        await process_run(summary.run_id, output_dir=tmp_path / "artifacts")

    with test_sessions() as session:
        run = session.get(RunRecord, summary.run_id)
        assert run.status == "failed"
        assert "Model request failed" in run.error
        assert session.scalar(select(func.count()).select_from(ArtifactRecord)) == 0
        assert session.scalar(
            select(func.count()).select_from(DecisionRecord).where(DecisionRecord.status == "failed")
        ) >= 1
