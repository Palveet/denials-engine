import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.decide.facts import build_fact_sheet
from app.decide.llm import AnthropicClient, ModelDecisionError, decide_fact_sheet, get_client
from app.decide.prompts import SYSTEM_PROMPT
from app.decide.validate import GuardrailViolation, validate_candidate
from app.schemas import (
    Actor,
    ClaimData,
    DecisionCandidate,
    DenialData,
    NextAction,
    Outcome,
    ServiceLineData,
    Source,
)


def claim_with(denial: DenialData | None) -> tuple[ClaimData, DenialData | None]:
    claim = ClaimData(
        claim_id="TEST-1",
        patient_name="TEST PATIENT",
        payer_name="TEST PAYER",
        date_of_service=date(2026, 1, 1),
        billed_amount=Decimal("100"),
        sources=[Source.ERA_835],
        denials=[denial] if denial else [],
    )
    return claim, denial


def test_fact_sheet_supplies_the_hcpcs_description_so_the_model_cannot_invent_one():
    """A0433 was once described to a payer as "ALS1 emergency"; the primer says ALS level 2."""
    claim = ClaimData(
        claim_id="CLM-1005",
        patient_name="ELEANOR BRAND",
        payer_name="GRANITE STATE HEALTH PLAN",
        date_of_service=date(2026, 6, 20),
        billed_amount=Decimal("1620"),
        sources=[Source.ERA_835],
        service_lines=[
            ServiceLineData(
                sequence=1,
                hcpcs="A0433",
                billed_amount=Decimal("1620"),
                paid_amount=Decimal("0"),
            )
        ],
    )
    denial = DenialData(
        group_code="CO",
        carc="50",
        denied_amount=Decimal("1620"),
        source="era_835",
        service_line_sequence=1,
    )
    facts = build_fact_sheet(claim, denial, as_of_date=date(2026, 7, 28))
    assert facts["service_line"]["hcpcs_description"] == "ALS level 2 transport."
    assert "ALS level 2" in SYSTEM_PROMPT
    assert "only as the supplied descriptions define them" in SYSTEM_PROMPT


def test_unknown_hcpcs_is_labelled_unknown_rather_than_guessed():
    claim = ClaimData(
        claim_id="CLM-9999",
        patient_name="TEST PATIENT",
        payer_name="TEST PAYER",
        date_of_service=date(2026, 6, 20),
        billed_amount=Decimal("100"),
        sources=[Source.ERA_835],
        service_lines=[
            ServiceLineData(
                sequence=1,
                hcpcs="A9999",
                billed_amount=Decimal("100"),
                paid_amount=Decimal("0"),
            )
        ],
    )
    denial = DenialData(
        group_code="CO",
        carc="50",
        denied_amount=Decimal("100"),
        source="era_835",
        service_line_sequence=1,
    )
    facts = build_fact_sheet(claim, denial, as_of_date=date(2026, 7, 28))
    assert facts["service_line"]["hcpcs_description"] == "Unknown procedure code"


def test_prompt_uses_the_tool_schema_without_an_inline_answer_key():
    assert "Required schema:" not in SYSTEM_PROMPT
    assert "Choose needs_info, call_payer" not in SYSTEM_PROMPT
    assert "Make the operational decision yourself" in SYSTEM_PROMPT


def test_pr_appeal_is_rejected_and_never_faxed():
    claim, denial = claim_with(
        DenialData(group_code="PR", carc="1", denied_amount=Decimal("100"), source="era_835")
    )
    facts = build_fact_sheet(claim, denial, as_of_date=date(2026, 7, 28))
    candidate = DecisionCandidate(
        outcome=Outcome.RECOVERABLE,
        next_action=NextAction.SUBMIT_APPEAL,
        actor=Actor.BILLER,
        fax_required=True,
        rationale="PR-1 should be appealed even though it is patient responsibility.",
        confidence=0.9,
    )
    with pytest.raises(GuardrailViolation) as exc_info:
        validate_candidate(candidate, facts, raw={}, model_name="test")
    assert "patient_responsibility_conflict" in exc_info.value.flags


def test_low_confidence_is_flagged_without_replacing_model_decision():
    claim, denial = claim_with(
        DenialData(group_code="CO", carc="50", denied_amount=Decimal("100"), source="era_835")
    )
    facts = build_fact_sheet(claim, denial, as_of_date=date(2026, 7, 28))
    candidate = DecisionCandidate(
        outcome=Outcome.RECOVERABLE,
        next_action=NextAction.SUBMIT_APPEAL,
        actor=Actor.BILLER,
        fax_required=True,
        rationale="CO-50 may be recoverable with clinical records and a supported appeal.",
        confidence=0.4,
    )
    result = validate_candidate(candidate, facts, raw={}, model_name="test")
    assert result.outcome == Outcome.RECOVERABLE
    assert result.next_action == NextAction.SUBMIT_APPEAL
    assert result.fax_required is True
    assert "low_confidence" in result.validator_flags


def test_prior_auth_without_payer_window_requires_call():
    claim, denial = claim_with(
        DenialData(group_code="CO", carc="197", denied_amount=Decimal("100"), source="era_835")
    )
    facts = build_fact_sheet(claim, denial, as_of_date=date(2026, 7, 28))
    candidate = DecisionCandidate(
        outcome=Outcome.RECOVERABLE,
        next_action=NextAction.REQUEST_RETRO_AUTH,
        actor=Actor.BILLER,
        fax_required=True,
        rationale="A retro-authorization request may recover the denied amount.",
        confidence=0.9,
    )
    with pytest.raises(GuardrailViolation) as exc_info:
        validate_candidate(candidate, facts, raw={}, model_name="test")
    assert "prior_auth_window_unknown" in exc_info.value.flags


def test_bare_medical_necessity_code_requires_group_verification():
    claim, denial = claim_with(
        DenialData(
            group_code="UNKNOWN",
            carc="50",
            payer_reason_text="MEDICAL NECESSITY",
            denied_amount=Decimal("100"),
            source="clearinghouse_csv",
        )
    )
    facts = build_fact_sheet(claim, denial, as_of_date=date(2026, 7, 28))
    candidate = DecisionCandidate(
        outcome=Outcome.UNSURE,
        next_action=NextAction.SUBMIT_RECORDS,
        actor=Actor.BILLER,
        fax_required=False,
        rationale="The denial may need records, but the group code is unavailable.",
        confidence=0.8,
    )
    with pytest.raises(GuardrailViolation) as exc_info:
        validate_candidate(candidate, facts, raw={}, model_name="test")
    assert "denial_group_unverified" in exc_info.value.flags


def test_safe_model_judgment_is_accepted_without_answer_key_matching():
    claim, denial = claim_with(
        DenialData(group_code="CO", carc="50", denied_amount=Decimal("100"), source="era_835")
    )
    facts = build_fact_sheet(claim, denial, as_of_date=date(2026, 7, 28))
    candidate = DecisionCandidate(
        outcome=Outcome.NEEDS_INFO,
        next_action=NextAction.CALL_PAYER,
        actor=Actor.BILLER,
        fax_required=False,
        rationale="The model wants coverage details before deciding whether an appeal is supportable.",
        confidence=0.8,
    )
    result = validate_candidate(candidate, facts, raw={}, model_name="test")
    assert result.outcome == Outcome.NEEDS_INFO
    assert result.next_action == NextAction.CALL_PAYER
    assert result.validator_flags == []


class ValidResponseClient:
    model_name = "test-client"

    async def complete(self, fact_sheet, validation_error=None):
        return (
            '{"outcome":"not_recoverable","next_action":"none","actor":"system",'
            '"fax_required":false,"rationale":"The claim has no actionable denial.",'
            '"confidence":0.99}',
            {"provider_response": "test-only"},
        )


@pytest.mark.asyncio
async def test_schema_valid_provider_response_is_accepted():
    claim, denial = claim_with(None)
    facts = build_fact_sheet(claim, denial, as_of_date=date(2026, 7, 28))
    result = await decide_fact_sheet(ValidResponseClient(), facts)
    assert result.outcome == Outcome.NOT_RECOVERABLE
    assert result.next_action == NextAction.NONE
    assert result.model_name == "test-client"


class MockAnthropicResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "id": "msg_test",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_test",
                    "name": "record_denial_decision",
                    "input": {
                        "outcome": "not_recoverable",
                        "next_action": "none",
                        "actor": "system",
                        "fax_required": False,
                        "rationale": "The claim has no actionable denial.",
                        "confidence": 0.99,
                    },
                }
            ],
        }


class MockAnthropicHttpClient:
    calls = []

    def __init__(self, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def post(self, url, headers, json):
        self.__class__.calls.append({"url": url, "headers": headers, "payload": json})
        return MockAnthropicResponse()


@pytest.mark.asyncio
async def test_anthropic_client_uses_native_messages_and_strict_tool(monkeypatch):
    MockAnthropicHttpClient.calls.clear()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "claude-fable-5")
    monkeypatch.setattr("app.decide.llm.httpx.AsyncClient", MockAnthropicHttpClient)

    client = get_client()
    assert isinstance(client, AnthropicClient)
    content, raw = await client.complete({"claim": {"claim_id": "TEST-1"}})

    assert json.loads(content)["next_action"] == "none"
    assert raw["id"] == "msg_test"
    call = MockAnthropicHttpClient.calls[0]
    assert call["url"] == "https://api.anthropic.com/v1/messages"
    assert call["payload"]["model"] == "claude-fable-5"
    assert call["headers"]["x-api-key"] == "test-key"
    assert call["headers"]["anthropic-version"] == "2023-06-01"
    assert call["payload"]["tool_choice"] == {
        "type": "tool",
        "name": "record_denial_decision",
    }
    assert call["payload"]["tools"][0]["strict"] is True
    assert "temperature" not in call["payload"]


class AlwaysMalformed:
    model_name = "malformed-test"

    def __init__(self):
        self.calls = 0

    async def complete(self, fact_sheet, validation_error=None):
        self.calls += 1
        return "not-json", {"attempt": self.calls}


@pytest.mark.asyncio
async def test_malformed_json_retries_once_then_degrades():
    claim, denial = claim_with(None)
    facts = build_fact_sheet(claim, denial, as_of_date=date(2026, 7, 28))
    client = AlwaysMalformed()
    with pytest.raises(ModelDecisionError) as exc_info:
        await decide_fact_sheet(client, facts)
    assert client.calls == 2
    assert exc_info.value.flag == "model_response_failure"


class UnsafeThenSafe:
    model_name = "retry-test"

    def __init__(self):
        self.calls = 0
        self.validation_errors = []

    async def complete(self, fact_sheet, validation_error=None):
        self.calls += 1
        self.validation_errors.append(validation_error)
        if self.calls == 1:
            return (
                '{"outcome":"recoverable","next_action":"submit_appeal","actor":"biller",'
                '"fax_required":true,"rationale":"Appeal the patient responsibility amount.",'
                '"confidence":0.9}',
                {"attempt": 1},
            )
        return (
            '{"outcome":"not_recoverable","next_action":"bill_patient","actor":"biller",'
            '"fax_required":false,"rationale":"PR-1 is patient responsibility and is not appealed.",'
            '"confidence":0.95}',
            {"attempt": 2},
        )


@pytest.mark.asyncio
async def test_unsafe_answer_is_returned_to_model_for_one_correction():
    claim, denial = claim_with(
        DenialData(group_code="PR", carc="1", denied_amount=Decimal("100"), source="era_835")
    )
    facts = build_fact_sheet(claim, denial, as_of_date=date(2026, 7, 28))
    client = UnsafeThenSafe()
    result = await decide_fact_sheet(client, facts)
    assert client.calls == 2
    assert "patient_responsibility_conflict" in client.validation_errors[1]
    assert result.outcome == Outcome.NOT_RECOVERABLE
    assert result.next_action == NextAction.BILL_PATIENT
    assert "model_revised_after_guardrail" in result.validator_flags


class RequestFailure:
    model_name = "request-failure-test"

    async def complete(self, fact_sheet, validation_error=None):
        raise RuntimeError("provider unavailable")


@pytest.mark.asyncio
async def test_request_failure_is_not_converted_into_a_fake_decision():
    claim, denial = claim_with(None)
    facts = build_fact_sheet(claim, denial, as_of_date=date(2026, 7, 28))
    with pytest.raises(ModelDecisionError) as exc_info:
        await decide_fact_sheet(RequestFailure(), facts)
    assert exc_info.value.flag == "model_request_failure"


class BillingFailure:
    """Reproduces a provider 400 whose only useful content is the JSON error message."""

    model_name = "billing-test"

    async def complete(self, fact_sheet, validation_error=None):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(
            400,
            request=request,
            json={
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": "Your credit balance is too low to access the Anthropic API.",
                },
            },
        )
        raise httpx.HTTPStatusError("400 Bad Request", request=request, response=response)


@pytest.mark.asyncio
async def test_http_failure_surfaces_the_provider_message_and_model():
    claim, denial = claim_with(None)
    facts = build_fact_sheet(claim, denial, as_of_date=date(2026, 7, 28))
    with pytest.raises(ModelDecisionError) as exc_info:
        await decide_fact_sheet(BillingFailure(), facts)
    message = str(exc_info.value)
    assert "credit balance is too low" in message
    assert "billing-test" in message
    assert "HTTP 400" in message
    assert exc_info.value.raw["status_code"] == 400
