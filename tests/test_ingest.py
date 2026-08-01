from decimal import Decimal
from pathlib import Path

import pytest

from app.ingest.clearinghouse import normalize_carc, parse_clearinghouse_csv
from app.ingest.merge import merge_claims
from app.ingest.x12_835 import X12835Error, parse_835


DATA = Path(__file__).parents[1] / "data"


@pytest.fixture
def merged_claims():
    era = parse_835((DATA / "sample.835").read_text())
    csv_claims = parse_clearinghouse_csv((DATA / "denials_export.csv").read_text())
    return era, csv_claims, merge_claims(era.claims, csv_claims)


def test_835_parser_maps_claims_lines_rarcs_and_total(merged_claims):
    era, _, _ = merged_claims
    assert len(era.claims) == 8
    assert era.bpr_total == Decimal("3345.00")
    assert sum((claim.paid_amount for claim in era.claims), Decimal("0")) == era.bpr_total
    by_id = {claim.claim_id: claim for claim in era.claims}
    assert {claim.payer_name for claim in era.claims} == {"GRANITE STATE HEALTH PLAN"}
    assert by_id["CLM-1001"].member_id == "GSH001234501"
    assert len(by_id["CLM-1001"].service_lines) == 2
    assert by_id["CLM-1004"].service_lines[0].rarcs == ["M60"]
    assert by_id["CLM-1005"].service_lines[0].rarcs == ["N115"]
    assert by_id["CLM-1008"].service_lines[1].hcpcs == "A0425"


def test_835_parser_reads_payer_and_member_id_from_exact_positions():
    text = (DATA / "sample.835").read_text()
    text = text.replace("N1*PR*GRANITE STATE HEALTH PLAN", "N1*PR*ANOTHER HEALTH PLAN")
    text = text.replace("NM1*QC*1*DOE*JANE", "NM1*QC*1*MI*JANE")
    era = parse_835(text)
    first = era.claims[0]
    assert first.payer_name == "ANOTHER HEALTH PLAN"
    assert first.patient_name == "JANE MI"
    assert first.member_id == "GSH001234501"


def test_835_parser_keeps_informational_lq_without_a_cas():
    text = (DATA / "sample.835").read_text().replace(
        "DTM*472*20260608~\nSVC*HC:A0425",
        "DTM*472*20260608~\nLQ*HE*N123~\nSVC*HC:A0425",
        1,
    )
    era = parse_835(text)
    assert era.claims[0].service_lines[0].rarcs == ["N123"]
    assert era.claims[0].service_lines[0].adjustments == []


def test_835_parser_accepts_a_different_segment_terminator():
    text = (DATA / "sample.835").read_text().replace("~", "|")
    era = parse_835(text)
    assert len(era.claims) == 8


def test_835_parser_rejects_an_unbalanced_payment_without_plb():
    text = (DATA / "sample.835").read_text().replace("BPR*I*3345.00", "BPR*I*3344.00")
    with pytest.raises(X12835Error, match="does not reconcile"):
        parse_835(text)


def test_835_parser_accumulates_multiple_transaction_sets():
    text = (DATA / "sample.835").read_text()
    transaction = text.split("ST*835*0001~", 1)[1].split("SE*70*0001~", 1)[0]
    second = (
        "ST*835*0002~"
        + transaction.replace("GRANITE STATE HEALTH PLAN", "SECOND HEALTH PLAN").replace(
            "CLM-100", "CLM-300"
        )
        + "SE*70*0002~\n"
    )
    text = text.replace("GE*1*101~", second + "GE*2*101~")

    era = parse_835(text)
    assert len(era.claims) == 16
    assert era.bpr_total == Decimal("6690.00")
    assert {claim.payer_name for claim in era.claims} == {
        "GRANITE STATE HEALTH PLAN",
        "SECOND HEALTH PLAN",
    }


def test_csv_carc_normalization_preserves_unknown_group():
    assert normalize_carc("16") == ("UNKNOWN", "16")
    assert normalize_carc("PR-1") == ("PR", "1")
    assert normalize_carc("") == ("UNKNOWN", None)


def test_merge_dedupes_promotes_and_records_discrepancies(merged_claims):
    _, _, claims = merged_claims
    assert len(claims) == 12
    assert sum(len(claim.denials) for claim in claims) == 10
    by_id = {claim.claim_id: claim for claim in claims}
    assert len(by_id["CLM-1004"].denials) == 1
    assert len(by_id["CLM-1006"].denials) == 1
    assert {item.field for item in by_id["CLM-1006"].discrepancies} == {
        "billed_amount",
        "patient_name",
    }
    assert by_id["CLM-1006"].billed_amount == Decimal("1450.00")
    assert by_id["CLM-1002"].denials == []
    assert by_id["CLM-1003"].denials[0].group_code == "PR"
    assert by_id["CLM-1004"].denials[0].rarcs == ["M60"]
    assert by_id["CLM-1005"].denials[0].rarcs == ["N115"]
    assert by_id["CLM-1008"].denials[0].service_line_sequence == 2
    assert by_id["CLM-2001"].denials[0].group_code == "UNKNOWN"
