from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.schemas import (
    AdjustmentData,
    ClaimData,
    Parse835Result,
    ServiceLineData,
    Source,
)


class X12835Error(ValueError):
    pass


def _money(value: str, *, context: str) -> Decimal:
    try:
        return Decimal(value or "0")
    except Exception as exc:
        raise X12835Error(f"Invalid amount {value!r} in {context}") from exc


def _date(value: str, *, context: str):
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise X12835Error(f"Invalid date {value!r} in {context}") from exc


def _segments(text: str) -> list[list[str]]:
    raw = text.strip()
    if not raw.startswith("ISA") or len(raw) < 4:
        raise X12835Error("835 must begin with an ISA segment")
    element_sep = raw[3]
    first_line = raw.splitlines()[0]
    segment_term = raw[105] if len(raw) > 105 and raw[105] not in "\r\n" else first_line[-1]
    normalized = raw.replace("\r", "").replace("\n", "")
    parsed = [segment.strip().split(element_sep) for segment in normalized.split(segment_term) if segment.strip()]
    if not any(segment[0] == "ST" and len(segment) > 1 and segment[1] == "835" for segment in parsed):
        raise X12835Error("Input is not an X12 835 transaction")
    return parsed


def parse_835(text: str) -> Parse835Result:
    claims: list[ClaimData] = []
    current: ClaimData | None = None
    current_line: ServiceLineData | None = None
    last_adjustments: list[AdjustmentData] = []
    bpr_total: Decimal | None = None

    for elements in _segments(text):
        tag = elements[0]
        if tag == "BPR":
            if len(elements) < 3:
                raise X12835Error("BPR segment is missing the payment amount")
            bpr_total = _money(elements[2], context="BPR")
        elif tag == "CLP":
            if len(elements) < 8:
                raise X12835Error("CLP segment is incomplete")
            current = ClaimData(
                claim_id=elements[1].strip(),
                claim_status_835=elements[2].strip(),
                billed_amount=_money(elements[3], context="CLP billed"),
                paid_amount=_money(elements[4], context="CLP paid"),
                patient_responsibility=_money(elements[5], context="CLP patient responsibility"),
                payer_claim_ref=elements[7].strip() or None,
                patient_name="UNKNOWN",
                payer_name="Granite State Health Plan",
                date_of_service=datetime(1900, 1, 1).date(),
                sources=[Source.ERA_835],
            )
            claims.append(current)
            current_line = None
            last_adjustments = []
        elif tag == "NM1" and current and len(elements) > 2 and elements[1] == "QC":
            last = elements[3].strip() if len(elements) > 3 else ""
            first = elements[4].strip() if len(elements) > 4 else ""
            current.patient_name = " ".join(part for part in (first, last) if part).upper() or "UNKNOWN"
            for index, value in enumerate(elements[:-1]):
                if value == "MI":
                    current.member_id = elements[index + 1].strip() or None
                    break
        elif tag == "DTM" and current and len(elements) > 2:
            parsed_date = _date(elements[2], context=f"DTM {elements[1]}")
            if elements[1] == "232":
                current.date_of_service = parsed_date
            elif elements[1] == "472" and current_line:
                current_line.service_date = parsed_date
        elif tag == "SVC" and current:
            if len(elements) < 4:
                raise X12835Error("SVC segment is incomplete")
            hcpcs = elements[1].split(":")[-1].strip()
            units = _money(elements[5], context="SVC units") if len(elements) > 5 and elements[5] else None
            current_line = ServiceLineData(
                sequence=len(current.service_lines) + 1,
                hcpcs=hcpcs,
                billed_amount=_money(elements[2], context="SVC billed"),
                paid_amount=_money(elements[3], context="SVC paid"),
                units=units,
            )
            current.service_lines.append(current_line)
            last_adjustments = []
        elif tag == "CAS" and current:
            if len(elements) < 4:
                raise X12835Error("CAS segment is incomplete")
            group = elements[1].strip().upper() or "UNKNOWN"
            created: list[AdjustmentData] = []
            for index in range(2, len(elements), 3):
                if index + 1 >= len(elements) or not elements[index].strip():
                    continue
                adjustment = AdjustmentData(
                    group_code=group,
                    carc=elements[index].strip(),
                    amount=_money(elements[index + 1], context="CAS adjustment"),
                )
                created.append(adjustment)
                if current_line:
                    current_line.adjustments.append(adjustment)
                else:
                    current.claim_adjustments.append(adjustment)
            last_adjustments = created
        elif tag == "LQ" and current and len(elements) > 2 and elements[1] == "HE":
            rarc = elements[2].strip().upper()
            for adjustment in last_adjustments:
                if rarc and rarc not in adjustment.rarcs:
                    adjustment.rarcs.append(rarc)

    if bpr_total is None:
        raise X12835Error("BPR payment total is missing")
    for claim in claims:
        if claim.date_of_service.year == 1900:
            service_dates = [line.service_date for line in claim.service_lines if line.service_date]
            if service_dates:
                claim.date_of_service = min(service_dates)
            else:
                raise X12835Error(f"Claim {claim.claim_id} has no service date")
        for line in claim.service_lines:
            if line.service_date is None:
                line.service_date = claim.date_of_service
    return Parse835Result(claims=claims, bpr_total=bpr_total)

