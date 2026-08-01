import csv
from datetime import date
from decimal import Decimal

from pypdf import PdfReader

from app.output.documents import _letter_body, generate_fax_packet, packet_html
from app.output.handoff import HEADERS, generate_handoff
from app.schemas import (
    Actor,
    ClaimData,
    DenialData,
    NextAction,
    Outcome,
    Source,
    ValidatedDecision,
)


def _decision(next_action: NextAction) -> ValidatedDecision:
    return ValidatedDecision(
        outcome=Outcome.RECOVERABLE,
        next_action=next_action,
        actor=Actor.BILLER,
        fax_required=True,
        rationale="Deterministic letter-content fixture for the denial under review.",
        confidence=0.9,
        model_name="test",
        prompt_version="test",
    )


def _claim() -> ClaimData:
    return ClaimData(
        claim_id="CLM-1008",
        patient_name="OLIVER FINCH",
        payer_name="GRANITE STATE HEALTH PLAN",
        date_of_service=date(2026, 6, 24),
        billed_amount=Decimal("1426"),
        sources=[Source.ERA_835],
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


def test_packet_never_carries_the_model_rationale_to_the_payer():
    """The rationale is an internal audit record; the payer must not read it."""
    claim = _claim()
    denial = DenialData(
        group_code="CO", carc="50", denied_amount=Decimal("276"), source="era_835"
    )
    decision = ValidatedDecision(
        outcome=Outcome.RECOVERABLE,
        next_action=NextAction.SUBMIT_RECORDS,
        actor=Actor.BILLER,
        fax_required=True,
        rationale=(
            "appears_in_both_sources=false and group_is_explicit=true; confidence tempered "
            "by the absence of RARC detail, so the biller should assemble the packet."
        ),
        confidence=0.68,
        model_name="test",
        prompt_version="test",
    )
    markup = packet_html(claim, denial, decision, packet_date=date(2026, 8, 1), page_count=2)
    assert "Decision basis" not in markup
    assert "appears_in_both_sources" not in markup
    assert "confidence tempered" not in markup.lower()


def test_records_letter_for_medical_necessity_does_not_demand_a_cmn():
    """A CO-50 denial never cited a missing CMN, so the letter must not ask for one."""
    denial = DenialData(
        group_code="CO", carc="50", denied_amount=Decimal("276"), source="era_835"
    )
    body = _letter_body(_claim(), denial, _decision(NextAction.SUBMIT_RECORDS))
    assert "Certificate of Medical Necessity" not in body
    assert "clinical records supporting the medical necessity" in body
    assert "CO-50" in body


def test_letter_omits_the_remark_sentence_when_the_payer_sent_none():
    denial = DenialData(
        group_code="CO", carc="50", denied_amount=Decimal("276"), source="era_835"
    )
    body = _letter_body(_claim(), denial, _decision(NextAction.SUBMIT_RECORDS))
    assert "remark code" not in body
    assert "not supplied" not in body


def test_letter_cites_and_explains_a_supplied_remark_code():
    denial = DenialData(
        group_code="CO",
        carc="16",
        rarcs=["M60"],
        denied_amount=Decimal("1275"),
        source="era_835",
    )
    body = _letter_body(_claim(), denial, _decision(NextAction.SUBMIT_RECORDS))
    assert "remark code M60 (Missing Certificate of Medical Necessity)" in body
    assert "signed Certificate of Medical Necessity" in body


def test_letter_handles_a_denial_with_no_carc():
    denial = DenialData(
        group_code="UNKNOWN", carc=None, denied_amount=Decimal("1120"), source="clearinghouse_csv"
    )
    body = _letter_body(_claim(), denial, _decision(NextAction.SUBMIT_APPEAL))
    assert "a reason code the payer did not supply" in body
    assert "None" not in body


def test_handoff_separates_validator_flags_from_source_discrepancies(tmp_path):
    rows = [
        {
            "claim_id": "CLM-1006",
            "patient": "LIN CHEN",
            "date_of_service": "2026-01-12",
            "denied_amount": "1450.00",
            "outcome": "unsure",
            "next_step": "call_payer",
            "actor": "biller",
            "confidence": "0.550",
            "validator_flags": "low_confidence",
            "source_discrepancies": "billed_amount; patient_name",
            "artifacts": "",
            "model_rationale": "CO-197 with no supplied authorization window.",
        }
    ]
    html_path, csv_path = generate_handoff(rows, tmp_path)
    written = list(csv.DictReader(csv_path.open()))
    assert list(written[0]) == HEADERS
    assert written[0]["validator_flags"] == "low_confidence"
    assert written[0]["source_discrepancies"] == "billed_amount; patient_name"
    assert written[0]["model_rationale"] == "CO-197 with no supplied authorization window."
    assert "LIN CHEN" in html_path.read_text()
