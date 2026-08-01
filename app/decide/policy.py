from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.schemas import Actor, DecisionCandidate, NextAction, Outcome


@dataclass(frozen=True)
class PolicyGuidance:
    certainty: Literal["rule", "review"]
    outcome: Outcome
    next_action: NextAction
    actor: Actor
    fax_required: bool
    reason: str
    evidence: tuple[str, ...]
    conflict_flag: str

    def matches(self, decision: DecisionCandidate) -> bool:
        return (
            decision.outcome == self.outcome
            and decision.next_action == self.next_action
            and decision.actor == self.actor
            and decision.fax_required == self.fax_required
        )


def policy_guidance(fact_sheet: dict) -> PolicyGuidance:
    denial = fact_sheet.get("denial")
    if denial is None:
        return PolicyGuidance(
            certainty="rule",
            outcome=Outcome.NOT_RECOVERABLE,
            next_action=NextAction.NONE,
            actor=Actor.SYSTEM,
            fax_required=False,
            reason="No actionable denial exists, so there is no payer balance to pursue.",
            evidence=("No denial record", "Assignment rule: every claim still receives an outcome"),
            conflict_flag="no_denial_policy_conflict",
        )

    group = denial.get("group_code") or "UNKNOWN"
    carc = denial.get("carc")
    rarcs = set(denial.get("rarcs") or [])

    if group == "PR":
        return PolicyGuidance(
            certainty="rule",
            outcome=Outcome.NOT_RECOVERABLE,
            next_action=NextAction.BILL_PATIENT,
            actor=Actor.BILLER,
            fax_required=False,
            reason="PR means patient responsibility; the payer must not be appealed or faxed.",
            evidence=(f"Group {group}", f"CARC {carc or 'missing'}"),
            conflict_flag="patient_responsibility_policy_conflict",
        )

    if carc == "18":
        return PolicyGuidance(
            certainty="rule",
            outcome=Outcome.NEEDS_INFO,
            next_action=NextAction.VERIFY_DUPLICATE,
            actor=Actor.BILLER,
            fax_required=False,
            reason="CARC 18 identifies a duplicate; the original claim must be checked before further action.",
            evidence=(f"Group {group}", "CARC 18: exact duplicate"),
            conflict_flag="duplicate_policy_conflict",
        )

    if group == "UNKNOWN":
        return PolicyGuidance(
            certainty="review",
            outcome=Outcome.NEEDS_INFO,
            next_action=NextAction.CALL_PAYER,
            actor=Actor.BILLER,
            fax_required=False,
            reason="The clearinghouse omitted the group code, which can change who owes the amount. Verify it with the payer before sending records or an appeal.",
            evidence=(f"Bare CARC {carc or 'missing'}", "Group code UNKNOWN"),
            conflict_flag="denial_group_unverified",
        )

    if not carc:
        return PolicyGuidance(
            certainty="review",
            outcome=Outcome.NEEDS_INFO,
            next_action=NextAction.CALL_PAYER,
            actor=Actor.BILLER,
            fax_required=False,
            reason="No CARC was supplied, so the denial basis must be obtained from the payer before choosing an action.",
            evidence=(f"Group {group}", "CARC missing"),
            conflict_flag="denial_code_missing",
        )

    if group == "CO" and carc == "16" and "M60" in rarcs:
        return PolicyGuidance(
            certainty="rule",
            outcome=Outcome.RECOVERABLE,
            next_action=NextAction.SUBMIT_RECORDS,
            actor=Actor.BILLER,
            fax_required=True,
            reason="CO-16 with M60 says the Certificate of Medical Necessity is missing; submit the signed CMN packet.",
            evidence=("CO-16: information missing", "RARC M60: missing CMN"),
            conflict_flag="missing_cmn_policy_conflict",
        )

    if group == "CO" and carc == "50":
        return PolicyGuidance(
            certainty="rule",
            outcome=Outcome.RECOVERABLE,
            next_action=NextAction.SUBMIT_APPEAL,
            actor=Actor.BILLER,
            fax_required=True,
            reason="CO-50 is a medical-necessity denial and is an appeal candidate when clinical support is attached.",
            evidence=("CO-50: medical necessity", *(('RARC N115: coverage determination',) if "N115" in rarcs else ())),
            conflict_flag="medical_necessity_policy_conflict",
        )

    if group == "CO" and carc == "197":
        return PolicyGuidance(
            certainty="review",
            outcome=Outcome.NEEDS_INFO,
            next_action=NextAction.CALL_PAYER,
            actor=Actor.BILLER,
            fax_required=False,
            reason="CO-197 lacks prior authorization, but the supplied material gives no payer-specific retro-authorization deadline. Confirm timeliness before requesting authorization.",
            evidence=("CO-197: prior authorization absent", "Retro-authorization window not supplied"),
            conflict_flag="prior_auth_window_unknown",
        )

    return PolicyGuidance(
        certainty="review",
        outcome=Outcome.UNSURE,
        next_action=NextAction.CALL_PAYER,
        actor=Actor.BILLER,
        fax_required=False,
        reason="The supplied exercise rules do not define a safe automatic action for this denial.",
        evidence=(f"Group {group}", f"CARC {carc}"),
        conflict_flag="no_policy_rule",
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
    guidance = policy_guidance(fact_sheet)
    matches = (
        outcome == guidance.outcome.value
        and next_action == guidance.next_action.value
        and actor == guidance.actor.value
        and fax_required == guidance.fax_required
    )
    if validator_flags:
        status = "guardrail_corrected"
        label = "Claude corrected"
    elif guidance.certainty == "rule" and matches:
        status = "rule_confirmed"
        label = "Rule confirmed"
    else:
        status = "human_review"
        label = "Human review"

    reason = guidance.reason
    if not matches and not validator_flags:
        reason = f"The stored recommendation does not match the policy baseline. {reason}"

    return {
        "status": status,
        "label": label,
        "reason": reason,
        "evidence": list(guidance.evidence),
        "expected": {
            "outcome": guidance.outcome.value,
            "next_action": guidance.next_action.value,
            "actor": guidance.actor.value,
            "fax_required": guidance.fax_required,
        },
    }
