from decimal import Decimal
from pathlib import Path

import pytest

from app.ingest.clearinghouse import normalize_carc, parse_clearinghouse_csv
from app.ingest.merge import merge_claims
from app.ingest.x12_835 import parse_835


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
    by_id = {claim.claim_id: claim for claim in era.claims}
    assert by_id["CLM-1001"].member_id == "GSH001234501"
    assert len(by_id["CLM-1001"].service_lines) == 2
    assert by_id["CLM-1004"].service_lines[0].adjustments[0].rarcs == ["M60"]
    assert by_id["CLM-1005"].service_lines[0].adjustments[0].rarcs == ["N115"]
    assert by_id["CLM-1008"].service_lines[1].hcpcs == "A0425"


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
    assert by_id["CLM-1008"].denials[0].service_line_sequence == 2
    assert by_id["CLM-2001"].denials[0].group_code == "UNKNOWN"

