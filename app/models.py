from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class RunRecord(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default="uploaded", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    as_of_date: Mapped[date] = mapped_column(Date)
    bpr_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    claims: Mapped[list["ClaimRecord"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list["ArtifactRecord"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ClaimRecord(Base):
    __tablename__ = "claims"
    __table_args__ = (UniqueConstraint("run_id", "claim_id", name="uq_run_claim"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    claim_id: Mapped[str] = mapped_column(String(64), index=True)
    payer_claim_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    patient_name: Mapped[str] = mapped_column(String(160))
    member_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    payer_name: Mapped[str] = mapped_column(String(200))
    date_of_service: Mapped[date] = mapped_column(Date)
    billed_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    patient_responsibility: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    claim_status_835: Mapped[str | None] = mapped_column(String(8), nullable=True)
    clearinghouse_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sources: Mapped[list[str]] = mapped_column(JSON, default=list)
    discrepancies: Mapped[list[dict]] = mapped_column(JSON, default=list)
    normalized_json: Mapped[dict] = mapped_column(JSON)

    run: Mapped[RunRecord] = relationship(back_populates="claims")
    service_lines: Mapped[list["ServiceLineRecord"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )
    adjustments: Mapped[list["AdjustmentRecord"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )
    denials: Mapped[list["DenialRecord"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )
    decisions: Mapped[list["DecisionRecord"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )


class ServiceLineRecord(Base):
    __tablename__ = "service_lines"
    __table_args__ = (UniqueConstraint("claim_id", "sequence", name="uq_claim_line"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    hcpcs: Mapped[str] = mapped_column(String(24))
    billed_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    units: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    service_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    claim: Mapped[ClaimRecord] = relationship(back_populates="service_lines")
    adjustments: Mapped[list["AdjustmentRecord"]] = relationship(back_populates="service_line")


class AdjustmentRecord(Base):
    __tablename__ = "adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    service_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_lines.id", ondelete="CASCADE"), nullable=True
    )
    group_code: Mapped[str] = mapped_column(String(16))
    carc: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    rarcs: Mapped[list[str]] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(40))

    claim: Mapped[ClaimRecord] = relationship(back_populates="adjustments")
    service_line: Mapped[ServiceLineRecord | None] = relationship(back_populates="adjustments")


class DenialRecord(Base):
    __tablename__ = "denials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    service_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_lines.id", ondelete="SET NULL"), nullable=True
    )
    group_code: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    carc: Mapped[str | None] = mapped_column(String(16), nullable=True)
    rarcs: Mapped[list[str]] = mapped_column(JSON, default=list)
    payer_reason_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    denied_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    source: Mapped[str] = mapped_column(String(100))
    clearinghouse_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)

    claim: Mapped[ClaimRecord] = relationship(back_populates="denials")
    service_line: Mapped[ServiceLineRecord | None] = relationship()
    decision: Mapped["DecisionRecord | None"] = relationship(back_populates="denial")


class DecisionRecord(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    denial_id: Mapped[int | None] = mapped_column(
        ForeignKey("denials.id", ondelete="CASCADE"), unique=True, nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    next_action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor: Mapped[str | None] = mapped_column(String(24), nullable=True)
    fax_required: Mapped[bool | None] = mapped_column(nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    fact_sheet: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    llm_raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    validator_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    model_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    claim: Mapped[ClaimRecord] = relationship(back_populates="decisions")
    denial: Mapped[DenialRecord | None] = relationship(back_populates="decision")
    artifacts: Mapped[list["ArtifactRecord"]] = relationship(back_populates="decision")


class ArtifactRecord(Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    decision_id: Mapped[int | None] = mapped_column(
        ForeignKey("decisions.id", ondelete="CASCADE"), nullable=True
    )
    claim_business_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(64))
    file_path: Mapped[str] = mapped_column(Text)
    preview_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    run: Mapped[RunRecord] = relationship(back_populates="artifacts")
    decision: Mapped[DecisionRecord | None] = relationship(back_populates="artifacts")
