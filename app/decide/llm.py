from __future__ import annotations

import json
import os
from typing import Protocol

import httpx
from pydantic import ValidationError

from app.constants import PROMPT_VERSION
from app.decide.prompts import SYSTEM_PROMPT, user_prompt
from app.decide.validate import GuardrailViolation, validate_candidate
from app.schemas import DecisionCandidate, ValidatedDecision


class DecisionClient(Protocol):
    model_name: str

    async def complete(self, fact_sheet: dict, validation_error: str | None = None) -> tuple[str, dict]: ...


class ModelDecisionError(RuntimeError):
    def __init__(self, message: str, *, flag: str, raw: dict, model_name: str) -> None:
        super().__init__(message)
        self.flag = flag
        self.raw = raw
        self.model_name = model_name


DECISION_TOOL = {
    "name": "record_denial_decision",
    "description": "Record exactly one validated operational decision for the supplied claim work item.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "outcome": {
                "type": "string",
                "enum": ["recoverable", "not_recoverable", "needs_info", "unsure"],
            },
            "next_action": {
                "type": "string",
                "enum": [
                    "submit_appeal",
                    "submit_records",
                    "request_retro_auth",
                    "resubmit_corrected_claim",
                    "bill_patient",
                    "verify_duplicate",
                    "call_payer",
                    "none",
                ],
            },
            "actor": {"type": "string", "enum": ["system", "biller", "payer"]},
            "fax_required": {"type": "boolean"},
            "rationale": {"type": "string"},
            "confidence": {"type": "number", "description": "A number from 0 through 1."},
        },
        "required": ["outcome", "next_action", "actor", "fax_required", "rationale", "confidence"],
    },
}


class AnthropicClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.base_url = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
        self.model_name = os.getenv("LLM_MODEL", "")

    async def complete(self, fact_sheet: dict, validation_error: str | None = None) -> tuple[str, dict]:
        if not self.api_key:
            raise RuntimeError("The model API key is not configured")
        if not self.model_name:
            raise RuntimeError("LLM_MODEL is not configured")
        payload = {
            "model": self.model_name,
            "max_tokens": 1024,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_prompt(fact_sheet, validation_error)}],
            "tools": [DECISION_TOOL],
            "tool_choice": {"type": "tool", "name": DECISION_TOOL["name"]},
        }
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                f"{self.base_url}/v1/messages",
                headers={
                    "content-type": "application/json",
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        tool_calls = [
            block
            for block in body.get("content", [])
            if block.get("type") == "tool_use" and block.get("name") == DECISION_TOOL["name"]
        ]
        if len(tool_calls) != 1 or not isinstance(tool_calls[0].get("input"), dict):
            raise ValueError("The model provider did not return exactly one structured decision tool call")
        return json.dumps(tool_calls[0]["input"]), body


def get_client() -> DecisionClient:
    return AnthropicClient()


def _provider_error_message(response: httpx.Response) -> str:
    """Surface the provider's own explanation; a bare status code is not actionable."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:400].strip() or "no response body"
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
    return json.dumps(body)[:400]


async def decide_fact_sheet(client: DecisionClient, fact_sheet: dict) -> ValidatedDecision:
    last_raw: dict = {}
    error_text: str | None = None
    guardrail_flags: list[str] = []
    for _attempt in range(2):
        try:
            content, last_raw = await client.complete(fact_sheet, error_text)
        except (ValueError, KeyError) as exc:
            error_text = str(exc)
        except Exception as exc:
            raw = {"error": str(exc)}
            detail = str(exc)
            if isinstance(exc, httpx.HTTPStatusError):
                raw.update(
                    {
                        "status_code": exc.response.status_code,
                        "url": str(exc.request.url),
                        "response": exc.response.text[:2000],
                    }
                )
                detail = (
                    f"HTTP {exc.response.status_code} from the model provider: "
                    f"{_provider_error_message(exc.response)}"
                )
            raise ModelDecisionError(
                f"Model request failed ({client.model_name}). {detail}",
                flag="model_request_failure",
                raw=raw,
                model_name=client.model_name,
            ) from exc
        else:
            try:
                candidate = DecisionCandidate.model_validate_json(content)
                result = validate_candidate(candidate, fact_sheet, raw=last_raw, model_name=client.model_name)
            except (ValidationError, json.JSONDecodeError, KeyError) as exc:
                error_text = str(exc)
            except GuardrailViolation as exc:
                guardrail_flags = exc.flags
                error_text = "Your decision violated these safety constraints: " + ", ".join(exc.flags)
            else:
                if guardrail_flags:
                    result.validator_flags = list(
                        dict.fromkeys(
                            ["model_revised_after_guardrail", *guardrail_flags, *result.validator_flags]
                        )
                    )
                return result

    if guardrail_flags:
        message = "Model response still violated safety constraints after one correction attempt: " + ", ".join(
            guardrail_flags
        )
    else:
        message = "Model response was not schema-valid after one correction attempt"
    raise ModelDecisionError(
        message,
        flag="model_response_failure",
        raw=last_raw or {"error": error_text or "unknown model response failure"},
        model_name=client.model_name,
    )
