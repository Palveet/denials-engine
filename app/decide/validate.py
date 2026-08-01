from __future__ import annotations

from app.constants import FAX_ACTIONS, PROMPT_VERSION, RECOVERY_ACTIONS
from app.decide.policy import policy_guidance
from app.schemas import (
    Actor,
    DecisionCandidate,
    NextAction,
    Outcome,
    ValidatedDecision,
)


def fallback_decision(flag: str, *, raw: dict, model_name: str) -> ValidatedDecision:
    return ValidatedDecision(
        outcome=Outcome.UNSURE,
        next_action=NextAction.CALL_PAYER,
        actor=Actor.BILLER,
        fax_required=False,
        rationale="The model did not return a safe, schema-valid decision. A biller should review the claim and call payer provider services.",
        confidence=0,
        validator_flags=[flag],
        llm_raw=raw,
        model_name=model_name,
        prompt_version=PROMPT_VERSION,
    )


def validate_candidate(
    candidate: DecisionCandidate,
    fact_sheet: dict,
    *,
    raw: dict,
    model_name: str,
) -> ValidatedDecision:
    flags: list[str] = []
    denial = fact_sheet.get("denial")
    action = candidate.next_action.value
    guidance = policy_guidance(fact_sheet)

    if denial is None and (
        candidate.outcome != Outcome.NOT_RECOVERABLE
        or candidate.next_action != NextAction.NONE
        or candidate.fax_required
    ):
        flags.append("no_denial_conflict")
    if denial and denial.get("group_code") == "PR" and (
        action != NextAction.BILL_PATIENT.value or candidate.fax_required
    ):
        flags.append("patient_responsibility_conflict")
    if denial and denial.get("carc") == "18" and (
        candidate.next_action != NextAction.VERIFY_DUPLICATE or candidate.fax_required
    ):
        flags.append("duplicate_requires_investigation")
    if candidate.fax_required and action not in FAX_ACTIONS:
        flags.append("fax_action_conflict")
    if candidate.fax_required and candidate.actor != Actor.BILLER:
        flags.append("fax_requires_biller_handoff")
    if candidate.outcome == Outcome.RECOVERABLE and action not in RECOVERY_ACTIONS:
        flags.append("recoverable_without_recovery_action")
    if candidate.confidence < 0.6:
        flags.append("low_confidence")
    if not guidance.matches(candidate):
        flags.append(guidance.conflict_flag)

    if flags:
        flags = list(dict.fromkeys(flags))
        return ValidatedDecision(
            outcome=guidance.outcome,
            next_action=guidance.next_action,
            actor=guidance.actor,
            fax_required=guidance.fax_required,
            rationale=f"Policy guardrail replaced Claude's recommendation. {guidance.reason}",
            confidence=1 if guidance.certainty == "rule" else 0,
            validator_flags=flags,
            llm_raw=raw,
            model_name=model_name,
            prompt_version=PROMPT_VERSION,
        )
    return ValidatedDecision(
        **candidate.model_dump(),
        validator_flags=[],
        llm_raw=raw,
        model_name=model_name,
        prompt_version=PROMPT_VERSION,
    )
