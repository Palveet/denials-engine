from datetime import date
from decimal import Decimal

from pypdf import PdfReader

from app.output.documents import generate_fax_packet
from app.schemas import (
    Actor,
    ClaimData,
    DenialData,
    NextAction,
    Outcome,
    Source,
    ValidatedDecision,
)


def test_fax_packet_contains_required_fields_and_two_pages(tmp_path):
    claim = ClaimData(
        claim_id="CLM-2001",
        patient_name="SAMUEL ORTIZ",
        payer_name="GRANITE STATE HEALTH PLAN",
        date_of_service=date(2026, 6, 9),
        billed_amount=Decimal("1580"),
        clearinghouse_ref="CH-77843",
        sources=[Source.CLEARINGHOUSE_CSV],
    )
    denial = DenialData(
        group_code="CO",
        carc="50",
        denied_amount=Decimal("1580"),
        source="clearinghouse_csv",
        clearinghouse_ref="CH-77843",
    )
    decision = ValidatedDecision(
        outcome=Outcome.RECOVERABLE,
        next_action=NextAction.SUBMIT_APPEAL,
        actor=Actor.BILLER,
        fax_required=True,
        rationale="The denial needs a medical-necessity appeal with supporting records.",
        confidence=0.9,
        model_name="test",
        prompt_version="test",
    )
    html_path, pdf_path, page_count = generate_fax_packet(
        claim,
        denial,
        decision,
        output_dir=tmp_path,
        packet_date=date(2026, 7, 28),
    )
    assert page_count == 2
    assert pdf_path.stat().st_size > 1000
    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages)
    for expected in (
        "SAMUEL ORTIZ",
        "CH-77843",
        "CLM-2001",
        "1999999984",
        "(603) 555-0188",
        "Medical necessity appeal",
    ):
        assert expected in text
    assert "GENERATED PACKET PAGES 2" in " ".join(text.upper().split())
    assert "CO-50" in html_path.read_text()
