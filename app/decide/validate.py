from __future__ import annotations

from app.constants import FAX_ACTIONS, PROMPT_VERSION, RECOVERY_ACTIONS
from app.schemas import Actor, DecisionCandidate, NextAction, Outcome, ValidatedDecision


class GuardrailViolation(ValueError):
    def __init__(self, flags: list[str]) -> None:
        self.flags = list(dict.fromkeys(flags))
        super().__init__("; ".join(self.flags))


def guardrail_violations(candidate: DecisionCandidate, fact_sheet: dict) -> list[str]:
    """Return safety/consistency violations, never an answer-key mismatch."""
    flags: list[str] = []
    denial = fact_sheet.get("denial")
    action = candidate.next_action.value
    is_recovery_action = action in RECOVERY_ACTIONS
    is_fax_action = action in FAX_ACTIONS

    if denial is None and (
        candidate.outcome != Outcome.NOT_RECOVERABLE
        or candidate.next_action != NextAction.NONE
        or candidate.actor != Actor.SYSTEM
        or candidate.fax_required
    ):
        flags.append("no_denial_conflict")

    if denial:
        group = denial.get("group_code") or "UNKNOWN"
        carc = denial.get("carc")

        if group == "PR" and (
            candidate.outcome == Outcome.RECOVERABLE or is_recovery_action or candidate.fax_required
        ):
            flags.append("patient_responsibility_conflict")
        if carc == "18" and (is_recovery_action or candidate.fax_required):
            flags.append("duplicate_requires_investigation")
        if group == "UNKNOWN" and carc != "18" and (is_recovery_action or candidate.fax_required):
            flags.append("denial_group_unverified")
        if not carc and (is_recovery_action or candidate.fax_required):
            flags.append("denial_code_missing")
        if group == "CO" and carc == "197" and (is_recovery_action or candidate.fax_required):
            flags.append("prior_auth_window_unknown")

    if candidate.fax_required and not is_fax_action:
        flags.append("fax_action_conflict")
    if is_fax_action and not candidate.fax_required:
        flags.append("fax_required_for_payer_action")
    if is_fax_action and candidate.actor != Actor.BILLER:
        flags.append("fax_requires_biller_handoff")
    if candidate.outcome == Outcome.RECOVERABLE and not is_recovery_action:
        flags.append("recoverable_without_recovery_action")
    if candidate.outcome == Outcome.NOT_RECOVERABLE and is_recovery_action:
        flags.append("nonrecoverable_with_recovery_action")
    if candidate.next_action == NextAction.BILL_PATIENT and candidate.actor != Actor.BILLER:
        flags.append("bill_patient_requires_biller")

    return list(dict.fromkeys(flags))


def validate_candidate(
    candidate: DecisionCandidate,
    fact_sheet: dict,
    *,
    raw: dict,
    model_name: str,
) -> ValidatedDecision:
    violations = guardrail_violations(candidate, fact_sheet)
    if violations:
        raise GuardrailViolation(violations)

    flags = ["low_confidence"] if candidate.confidence < 0.6 else []
    return ValidatedDecision(
        **candidate.model_dump(),
        validator_flags=flags,
        llm_raw=raw,
        model_name=model_name,
        prompt_version=PROMPT_VERSION,
    )
