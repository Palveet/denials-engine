from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Source(str, Enum):
    ERA_835 = "era_835"
    CLEARINGHOUSE_CSV = "clearinghouse_csv"


class Outcome(str, Enum):
    RECOVERABLE = "recoverable"
    NOT_RECOVERABLE = "not_recoverable"
    NEEDS_INFO = "needs_info"
    UNSURE = "unsure"


class NextAction(str, Enum):
    SUBMIT_APPEAL = "submit_appeal"
    SUBMIT_RECORDS = "submit_records"
    REQUEST_RETRO_AUTH = "request_retro_auth"
    RESUBMIT_CORRECTED_CLAIM = "resubmit_corrected_claim"
    BILL_PATIENT = "bill_patient"
    VERIFY_DUPLICATE = "verify_duplicate"
    CALL_PAYER = "call_payer"
    NONE = "none"


class Actor(str, Enum):
    SYSTEM = "system"
    BILLER = "biller"
    PAYER = "payer"


class Discrepancy(BaseModel):
    field: str
    era_value: Any
    csv_value: Any


class AdjustmentData(BaseModel):
    group_code: str
    carc: str
    amount: Decimal
    rarcs: list[str] = Field(default_factory=list)
    source: Source = Source.ERA_835


class ServiceLineData(BaseModel):
    sequence: int
    hcpcs: str
    billed_amount: Decimal
    paid_amount: Decimal
    units: Decimal | None = None
    service_date: date | None = None
    adjustments: list[AdjustmentData] = Field(default_factory=list)


class DenialData(BaseModel):
    group_code: str = "UNKNOWN"
    carc: str | None = None
    rarcs: list[str] = Field(default_factory=list)
    payer_reason_text: str | None = None
    denied_amount: Decimal
    source: str
    clearinghouse_ref: str | None = None
    service_line_sequence: int | None = None

    @field_validator("group_code", mode="before")
    @classmethod
    def normalize_group(cls, value: str | None) -> str:
        return (value or "UNKNOWN").upper()


class ClaimData(BaseModel):
    claim_id: str
    payer_claim_ref: str | None = None
    patient_name: str
    member_id: str | None = None
    payer_name: str
    date_of_service: date
    billed_amount: Decimal
    paid_amount: Decimal = Decimal("0")
    patient_responsibility: Decimal = Decimal("0")
    claim_status_835: str | None = None
    clearinghouse_ref: str | None = None
    clearinghouse_status: str | None = None
    clearinghouse_received_date: date | None = None
    sources: list[Source]
    discrepancies: list[Discrepancy] = Field(default_factory=list)
    service_lines: list[ServiceLineData] = Field(default_factory=list)
    claim_adjustments: list[AdjustmentData] = Field(default_factory=list)
    denials: list[DenialData] = Field(default_factory=list)


class Parse835Result(BaseModel):
    claims: list[ClaimData]
    bpr_total: Decimal


class IngestSummary(BaseModel):
    run_id: str
    era_claims: int
    csv_claims: int
    normalized_claims: int
    denials: int
    decision_work_items: int
    overlapping_claims: int
    discrepancy_count: int
    bpr_total: Decimal
    as_of_date: date


class DecisionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Outcome
    next_action: NextAction
    actor: Actor
    fax_required: bool
    rationale: str = Field(min_length=10, max_length=2000)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def rationale_is_compact(self) -> "DecisionCandidate":
        if not self.rationale.strip():
            raise ValueError("rationale must not be blank")
        return self


class ValidatedDecision(DecisionCandidate):
    validator_flags: list[str] = Field(default_factory=list)
    llm_raw: dict[str, Any] = Field(default_factory=dict)
    model_name: str
    prompt_version: str


class ArtifactView(BaseModel):
    id: int
    claim_id: str | None
    kind: str
    download_url: str
    preview_url: str | None = None
    page_count: int | None = None


class RunStatusView(BaseModel):
    run_id: str
    status: str
    total: int
    completed: int
    error: str | None = None
    items: list[dict[str, Any]]
