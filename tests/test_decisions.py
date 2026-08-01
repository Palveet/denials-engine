import json
from datetime import date
from decimal import Decimal

import pytest

from app.decide.facts import build_fact_sheet
from app.decide.llm import AnthropicClient, decide_fact_sheet, get_client
from app.decide.validate import validate_candidate
from app.schemas import (
    Actor,
    ClaimData,
    DecisionCandidate,
    DenialData,
    NextAction,
    Outcome,
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


def test_pr_appeal_is_demoted_and_never_faxed():
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
    result = validate_candidate(candidate, facts, raw={}, model_name="test")
    assert result.outcome == Outcome.NOT_RECOVERABLE
    assert result.next_action == NextAction.BILL_PATIENT
    assert result.fax_required is False
    assert "patient_responsibility_conflict" in result.validator_flags


def test_low_confidence_is_demoted():
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
    result = validate_candidate(candidate, facts, raw={}, model_name="test")
    assert result.outcome == Outcome.NEEDS_INFO
    assert result.next_action == NextAction.CALL_PAYER
    assert result.fax_required is False
    assert "prior_auth_window_unknown" in result.validator_flags


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
    result = validate_candidate(candidate, facts, raw={}, model_name="test")
    assert result.outcome == Outcome.NEEDS_INFO
    assert result.next_action == NextAction.CALL_PAYER
    assert result.fax_required is False
    assert "denial_group_unverified" in result.validator_flags


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
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    monkeypatch.setattr("app.decide.llm.httpx.AsyncClient", MockAnthropicHttpClient)

    client = get_client()
    assert isinstance(client, AnthropicClient)
    content, raw = await client.complete({"claim": {"claim_id": "TEST-1"}})

    assert json.loads(content)["next_action"] == "none"
    assert raw["id"] == "msg_test"
    call = MockAnthropicHttpClient.calls[0]
    assert call["url"] == "https://api.anthropic.com/v1/messages"
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
    result = await decide_fact_sheet(client, facts)
    assert client.calls == 2
    assert result.outcome == Outcome.UNSURE
    assert result.fax_required is False
    assert result.validator_flags == ["llm_parse_failure"]
