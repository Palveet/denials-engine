from __future__ import annotations

from datetime import date

PROVIDER = {
    "name": "Skyline Ambulance Service",
    "npi": "1999999984",
    "address": "4400 Airport Road, Nashua, NH 03063",
}

PAYER = {
    "name": "Granite State Health Plan",
    "fax": "(603) 555-0188",
    "phone": "(603) 555-0142",
    "address": "PO Box 91000, Concord, NH 03301",
}

CARC_DESCRIPTIONS = {
    "1": "Deductible; patient responsibility, not a payer denial.",
    "16": "Information needed to adjudicate the claim is missing.",
    "18": "Exact duplicate claim or service.",
    "45": "Routine contracted-fee write-off on an otherwise processed claim.",
    "50": "Service was not deemed medically necessary by the payer.",
    "197": "Required precertification or prior authorization is absent.",
}

RARC_DESCRIPTIONS = {
    "M60": "Missing Certificate of Medical Necessity.",
    "N115": "The decision followed a Local Coverage Determination.",
}

ACTIONABLE_CARCS = {"1", "16", "18", "50", "197"}
FAX_ACTIONS = {"submit_appeal", "submit_records", "request_retro_auth"}
RECOVERY_ACTIONS = FAX_ACTIONS | {"resubmit_corrected_claim"}
PROMPT_VERSION = "2026-07-28.2"


def iso_today() -> date:
    """Separate clock access so tests can pass a stable as-of date."""
    return date.today()

