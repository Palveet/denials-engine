from __future__ import annotations

from copy import deepcopy

from app.constants import ACTIONABLE_CARCS
from app.schemas import ClaimData, DenialData, Discrepancy, Source


def _promote_era_adjustments(claim: ClaimData) -> list[DenialData]:
    denials: list[DenialData] = []
    for adjustment in claim.claim_adjustments:
        if adjustment.carc not in ACTIONABLE_CARCS:
            continue
        denials.append(
            DenialData(
                group_code=adjustment.group_code,
                carc=adjustment.carc,
                rarcs=list(adjustment.rarcs),
                denied_amount=adjustment.amount,
                source=Source.ERA_835.value,
            )
        )
    for line in claim.service_lines:
        for adjustment in line.adjustments:
            if adjustment.carc not in ACTIONABLE_CARCS:
                continue
            denials.append(
                DenialData(
                    group_code=adjustment.group_code,
                    carc=adjustment.carc,
                    rarcs=list(dict.fromkeys([*adjustment.rarcs, *line.rarcs])),
                    denied_amount=adjustment.amount,
                    source=Source.ERA_835.value,
                    service_line_sequence=line.sequence,
                )
            )
    return denials


def _add_discrepancy(claim: ClaimData, field: str, era_value, csv_value) -> None:
    if era_value != csv_value:
        claim.discrepancies.append(
            Discrepancy(field=field, era_value=str(era_value), csv_value=str(csv_value))
        )


def _merge_csv_denial(target: ClaimData, csv_denial: DenialData) -> None:
    for existing in target.denials:
        if existing.carc == csv_denial.carc:
            sources = set(existing.source.split("+")) | {Source.CLEARINGHOUSE_CSV.value}
            existing.source = "+".join(sorted(sources))
            existing.payer_reason_text = csv_denial.payer_reason_text
            existing.clearinghouse_ref = csv_denial.clearinghouse_ref
            # The explicit payer group from the 835 wins over the CSV's absent group.
            if existing.group_code == "UNKNOWN" and csv_denial.group_code != "UNKNOWN":
                existing.group_code = csv_denial.group_code
            return
    target.denials.append(deepcopy(csv_denial))


def merge_claims(era_claims: list[ClaimData], csv_claims: list[ClaimData]) -> list[ClaimData]:
    by_id: dict[str, ClaimData] = {}
    for era in era_claims:
        merged = deepcopy(era)
        merged.denials = _promote_era_adjustments(merged)
        by_id[merged.claim_id] = merged

    for csv_claim in csv_claims:
        existing = by_id.get(csv_claim.claim_id)
        if existing is None:
            by_id[csv_claim.claim_id] = deepcopy(csv_claim)
            continue
        _add_discrepancy(existing, "billed_amount", existing.billed_amount, csv_claim.billed_amount)
        _add_discrepancy(existing, "patient_name", existing.patient_name, csv_claim.patient_name)
        _add_discrepancy(existing, "date_of_service", existing.date_of_service, csv_claim.date_of_service)
        existing.sources = list(dict.fromkeys(existing.sources + csv_claim.sources))
        existing.clearinghouse_ref = csv_claim.clearinghouse_ref
        existing.clearinghouse_status = csv_claim.clearinghouse_status
        existing.clearinghouse_received_date = csv_claim.clearinghouse_received_date
        for denial in csv_claim.denials:
            _merge_csv_denial(existing, denial)

    return sorted(by_id.values(), key=lambda claim: claim.claim_id)
