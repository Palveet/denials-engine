from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyContext:
    review_required: bool
    reason: str
    evidence: tuple[str, ...]


def policy_context(fact_sheet: dict) -> PolicyContext:
    """Explain the applicable safety context without deciding for the model."""
    denial = fact_sheet.get("denial")
    if denial is None:
        return PolicyContext(
            review_required=False,
            reason="The source files contain no actionable denial for this work item.",
            evidence=("No denial record",),
        )

    group = denial.get("group_code") or "UNKNOWN"
    carc = denial.get("carc")
    rarcs = set(denial.get("rarcs") or [])

    if group == "PR":
        return PolicyContext(
            review_required=False,
            reason="PR identifies patient responsibility; payer-recovery actions and faxes are blocked.",
            evidence=(f"Group {group}", f"CARC {carc or 'missing'}"),
        )
    if carc == "18":
        return PolicyContext(
            review_required=True,
            reason="CARC 18 identifies a possible duplicate that must be investigated before payer recovery.",
            evidence=(f"Group {group}", "CARC 18: exact duplicate"),
        )
    if group == "UNKNOWN":
        return PolicyContext(
            review_required=True,
            reason="The clearinghouse omitted the group code, so responsibility must be verified before payer recovery.",
            evidence=(f"Bare CARC {carc or 'missing'}", "Group code UNKNOWN"),
        )
    if not carc:
        return PolicyContext(
            review_required=True,
            reason="No CARC was supplied, so the denial basis is not established.",
            evidence=(f"Group {group}", "CARC missing"),
        )
    if group == "CO" and carc == "197":
        return PolicyContext(
            review_required=True,
            reason="The files do not supply the payer-specific retro-authorization deadline needed to establish timeliness.",
            evidence=("CO-197: prior authorization absent", "Retro-authorization window not supplied"),
        )
    if group == "CO" and carc == "16" and "M60" in rarcs:
        return PolicyContext(
            review_required=False,
            reason="The model evaluated a missing-information denial with a missing-CMN remark.",
            evidence=("CO-16: information missing", "RARC M60: missing CMN"),
        )
    if group == "CO" and carc == "50":
        return PolicyContext(
            review_required=False,
            reason="The model evaluated a medical-necessity denial using the supplied claim facts.",
            evidence=("CO-50: medical necessity", *(('RARC N115: coverage determination',) if "N115" in rarcs else ())),
        )
    return PolicyContext(
        review_required=True,
        reason="The supplied materials do not establish a deterministic answer for this denial.",
        evidence=(f"Group {group}", f"CARC {carc}"),
    )


def policy_view(
    fact_sheet: dict,
    *,
    outcome: str,
    next_action: str,
    actor: str,
    fax_required: bool,
    validator_flags: list[str],
) -> dict:
    context = policy_context(fact_sheet)
    flags = set(validator_flags)

    if flags & {"model_request_failure", "model_response_failure"}:
        status = "model_failed"
        label = "Model request failed"
        reason = "No usable model decision was returned."
    elif "model_revised_after_guardrail" in flags:
        status = "guardrail_corrected"
        label = "Model revised"
        reason = "The first model response violated a safety constraint. The model corrected its own decision on retry."
    elif context.review_required or outcome in {"needs_info", "unsure"} or "low_confidence" in flags:
        status = "human_review"
        label = "Human review"
        reason = context.reason
    else:
        status = "model_decision"
        label = "Model decision"
        reason = "The model made this recommendation and deterministic safety checks passed."

    return {
        "status": status,
        "label": label,
        "reason": reason,
        "evidence": list(context.evidence),
    }
