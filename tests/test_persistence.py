from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import make_engine
from app.models import Base, ClaimRecord, DecisionRecord, DenialRecord
from app.service import ingest_run


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

