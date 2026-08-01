from __future__ import annotations

from datetime import date

from app.constants import CARC_DESCRIPTIONS, RARC_DESCRIPTIONS
from app.schemas import ClaimData, DenialData


def build_fact_sheet(
    claim: ClaimData,
    denial: DenialData | None,
    *,
    as_of_date: date,
) -> dict:
    selected_line = None
    if denial and denial.service_line_sequence:
        selected_line = next(
            (line for line in claim.service_lines if line.sequence == denial.service_line_sequence),
            None,
        )
    return {
        "as_of_date": as_of_date.isoformat(),
        "claim": {
            "claim_id": claim.claim_id,
            "payer_claim_ref": claim.payer_claim_ref,
            "patient_name": claim.patient_name,
            "member_id": claim.member_id,
            "payer_name": claim.payer_name,
            "date_of_service": claim.date_of_service.isoformat(),
            "billed_amount": str(claim.billed_amount),
            "paid_amount": str(claim.paid_amount),
            "patient_responsibility": str(claim.patient_responsibility),
            "claim_status_835": claim.claim_status_835,
            "clearinghouse_status": claim.clearinghouse_status,
            "clearinghouse_ref": claim.clearinghouse_ref,
            "sources": [source.value for source in claim.sources],
        },
        "service_line": selected_line.model_dump(mode="json") if selected_line else None,
        "denial": (
            {
                **denial.model_dump(mode="json"),
                "carc_description": CARC_DESCRIPTIONS.get(denial.carc or ""),
                "rarc_descriptions": {
                    code: RARC_DESCRIPTIONS.get(code, "Unknown remark code") for code in denial.rarcs
                },
                "group_is_explicit": denial.group_code != "UNKNOWN",
            }
            if denial
            else None
        ),
        "computed": {
            "days_since_dos": (as_of_date - claim.date_of_service).days,
            "appears_in_both_sources": len(claim.sources) > 1,
            "discrepancies": [item.model_dump(mode="json") for item in claim.discrepancies],
            "claim_paid_but_line_denied": bool(
                denial and denial.service_line_sequence and claim.claim_status_835 == "1"
            ),
            "no_actionable_denial": denial is None,
            "external_attachment_likely_required": bool(
                denial and (denial.carc in {"16", "50"} or set(denial.rarcs) & {"M60", "N115"})
            ),
        },
    }

