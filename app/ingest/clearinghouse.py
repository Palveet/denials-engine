from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.schemas import ClaimData, DenialData, Source


class ClearinghouseCSVError(ValueError):
    pass


REQUIRED_COLUMNS = {
    "CH Ref #",
    "Claim ID",
    "Payer",
    "Patient Name",
    "DOS",
    "Billed Amt",
    "Status",
    "CARC",
    "Payer Reason Text",
    "Date Rcvd",
}


def _patient_name(value: str) -> str:
    if "," in value:
        last, first = (part.strip() for part in value.split(",", 1))
        return " ".join(part for part in (first, last) if part).upper()
    return " ".join(value.upper().split())


def normalize_carc(value: str | None) -> tuple[str, str | None]:
    cleaned = (value or "").strip().upper()
    if not cleaned:
        return "UNKNOWN", None
    if "-" in cleaned:
        group, code = cleaned.split("-", 1)
        if group not in {"CO", "PR"} or not code:
            raise ClearinghouseCSVError(f"Invalid CARC value: {value!r}")
        return group, code
    return "UNKNOWN", cleaned


def parse_clearinghouse_csv(text: str) -> list[ClaimData]:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
    if missing:
        raise ClearinghouseCSVError(f"CSV is missing columns: {', '.join(sorted(missing))}")
    claims: list[ClaimData] = []
    for row_number, row in enumerate(reader, 2):
        try:
            dos = datetime.strptime(row["DOS"].strip(), "%m/%d/%Y").date()
            received_date = datetime.strptime(row["Date Rcvd"].strip(), "%m/%d/%Y").date()
            billed = Decimal(row["Billed Amt"].strip())
        except (ValueError, InvalidOperation) as exc:
            raise ClearinghouseCSVError(f"Invalid value on CSV row {row_number}") from exc
        group, carc = normalize_carc(row.get("CARC"))
        clearinghouse_ref = row["CH Ref #"].strip() or None
        denial = DenialData(
            group_code=group,
            carc=carc,
            denied_amount=billed,
            payer_reason_text=row["Payer Reason Text"].strip() or None,
            source=Source.CLEARINGHOUSE_CSV.value,
            clearinghouse_ref=clearinghouse_ref,
        )
        claims.append(
            ClaimData(
                claim_id=row["Claim ID"].strip(),
                patient_name=_patient_name(row["Patient Name"]),
                payer_name=row["Payer"].strip(),
                date_of_service=dos,
                billed_amount=billed,
                clearinghouse_ref=clearinghouse_ref,
                clearinghouse_status=row["Status"].strip() or None,
                clearinghouse_received_date=received_date,
                sources=[Source.CLEARINGHOUSE_CSV],
                denials=[denial],
            )
        )
    return claims
