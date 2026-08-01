from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from app.schemas import AdjustmentData, ClaimData, Parse835Result, ServiceLineData, Source


class X12835Error(ValueError):
    pass


def _decimal(value: str, *, context: str) -> Decimal:
    try:
        return Decimal(value or "0")
    except Exception as exc:
        raise X12835Error(f"Invalid numeric value {value!r} in {context}") from exc


def _date(value: str, *, context: str) -> date:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise X12835Error(f"Invalid date {value!r} in {context}") from exc


def _segments(text: str) -> list[list[str]]:
    raw = text.strip()
    if not raw.startswith("ISA") or len(raw) < 4:
        raise X12835Error("835 must begin with an ISA segment")

    element_sep = raw[3]
    compact = raw.replace("\r", "").replace("\n", "")
    first_line = raw.splitlines()[0]
    candidates: list[str] = []
    if len(compact) > 105:
        candidates.append(compact[105])
    if first_line:
        candidates.append(first_line[-1])

    for segment_term in dict.fromkeys(candidates):
        if not segment_term or segment_term == element_sep or segment_term.isalnum():
            continue
        parsed = [
            segment.strip().split(element_sep)
            for segment in compact.split(segment_term)
            if segment.strip()
        ]
        if parsed and parsed[0][0] == "ISA" and any(
            segment[0] == "ST" and len(segment) > 1 and segment[1] == "835"
            for segment in parsed
        ):
            return parsed

    raise X12835Error("Could not detect a valid 835 segment terminator")


@dataclass
class _ClaimDraft:
    claim_id: str
    claim_status_835: str
    billed_amount: Decimal
    paid_amount: Decimal
    patient_responsibility: Decimal
    payer_claim_ref: str | None
    payer_name: str
    patient_name: str = "UNKNOWN"
    member_id: str | None = None
    date_of_service: date | None = None
    service_lines: list[ServiceLineData] = field(default_factory=list)
    claim_adjustments: list[AdjustmentData] = field(default_factory=list)


def _finish_claim(draft: _ClaimDraft) -> ClaimData:
    service_date = draft.date_of_service
    if service_date is None:
        line_dates = [line.service_date for line in draft.service_lines if line.service_date]
        if not line_dates:
            raise X12835Error(f"Claim {draft.claim_id} has no service date")
        service_date = min(line_dates)

    for line in draft.service_lines:
        if line.service_date is None:
            line.service_date = service_date

    return ClaimData(
        claim_id=draft.claim_id,
        claim_status_835=draft.claim_status_835,
        billed_amount=draft.billed_amount,
        paid_amount=draft.paid_amount,
        patient_responsibility=draft.patient_responsibility,
        payer_claim_ref=draft.payer_claim_ref,
        patient_name=draft.patient_name,
        member_id=draft.member_id,
        payer_name=draft.payer_name,
        date_of_service=service_date,
        service_lines=draft.service_lines,
        claim_adjustments=draft.claim_adjustments,
        sources=[Source.ERA_835],
    )


def parse_835(text: str) -> Parse835Result:
    claims: list[ClaimData] = []
    current: _ClaimDraft | None = None
    current_line: ServiceLineData | None = None
    payer_name: str | None = None
    bpr_total = Decimal("0")
    saw_bpr = False
    saw_plb = False

    for elements in _segments(text):
        tag = elements[0]
        if tag == "ST":
            payer_name = None
        elif tag == "BPR":
            if len(elements) < 3:
                raise X12835Error("BPR segment is missing the payment amount")
            bpr_total += _decimal(elements[2], context="BPR")
            saw_bpr = True
        elif tag == "N1" and len(elements) > 2 and elements[1] == "PR":
            payer_name = elements[2].strip()
            if not payer_name:
                raise X12835Error("N1*PR segment is missing the payer name")
        elif tag == "CLP":
            if current is not None:
                claims.append(_finish_claim(current))
            if len(elements) < 8:
                raise X12835Error("CLP segment is incomplete")
            if not payer_name:
                raise X12835Error("CLP segment appeared before a payer name in N1*PR")
            current = _ClaimDraft(
                claim_id=elements[1].strip(),
                claim_status_835=elements[2].strip(),
                billed_amount=_decimal(elements[3], context="CLP billed"),
                paid_amount=_decimal(elements[4], context="CLP paid"),
                patient_responsibility=_decimal(elements[5], context="CLP patient responsibility"),
                payer_claim_ref=elements[7].strip() or None,
                payer_name=payer_name,
            )
            current_line = None
        elif tag == "NM1" and current and len(elements) > 2 and elements[1] == "QC":
            last = elements[3].strip() if len(elements) > 3 else ""
            first = elements[4].strip() if len(elements) > 4 else ""
            current.patient_name = " ".join(part for part in (first, last) if part).upper() or "UNKNOWN"
            if len(elements) > 9 and elements[8] == "MI":
                current.member_id = elements[9].strip() or None
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
            units = _decimal(elements[5], context="SVC units") if len(elements) > 5 and elements[5] else None
            current_line = ServiceLineData(
                sequence=len(current.service_lines) + 1,
                hcpcs=hcpcs,
                billed_amount=_decimal(elements[2], context="SVC billed"),
                paid_amount=_decimal(elements[3], context="SVC paid"),
                units=units,
            )
            current.service_lines.append(current_line)
        elif tag == "CAS" and current:
            if len(elements) < 4:
                raise X12835Error("CAS segment is incomplete")
            group = elements[1].strip().upper() or "UNKNOWN"
            for index in range(2, len(elements), 3):
                if index + 1 >= len(elements) or not elements[index].strip():
                    continue
                adjustment = AdjustmentData(
                    group_code=group,
                    carc=elements[index].strip(),
                    amount=_decimal(elements[index + 1], context="CAS adjustment"),
                )
                if current_line:
                    current_line.adjustments.append(adjustment)
                else:
                    current.claim_adjustments.append(adjustment)
        elif tag == "LQ" and current and len(elements) > 2 and elements[1] == "HE":
            if current_line is None:
                raise X12835Error("Service-level LQ segment appeared outside an SVC loop")
            rarc = elements[2].strip().upper()
            if rarc and rarc not in current_line.rarcs:
                current_line.rarcs.append(rarc)
        elif tag == "PLB":
            saw_plb = True
        elif tag == "SE" and current is not None:
            claims.append(_finish_claim(current))
            current = None
            current_line = None

    if current is not None:
        claims.append(_finish_claim(current))
    if not saw_bpr:
        raise X12835Error("BPR payment total is missing")

    claim_payment_total = sum((claim.paid_amount for claim in claims), Decimal("0"))
    if not saw_plb and claim_payment_total != bpr_total:
        raise X12835Error(
            f"BPR payment total {bpr_total} does not reconcile to CLP payments {claim_payment_total}"
        )

    return Parse835Result(claims=claims, bpr_total=bpr_total)
