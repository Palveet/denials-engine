# CARC cheat sheet

Everything below is plain English for the codes that appear in this exercise's data. No outside knowledge is needed.

## Group codes

| Group | Means | Who absorbs it |
|---|---|---|
| `CO` | Contractual obligation | Provider writes it off; the patient may not be billed |
| `PR` | Patient responsibility | The patient owes it; bill the patient, not the payer |

Some clearinghouses drop the group prefix and report just the bare number. The group changes the meaning, so a bare code remains `UNKNOWN` in this application.

## Reason codes (CARCs)

| Code | Plain English |
|---|---|
| **1** (as PR-1) | Deductible. The claim was processed; the patient owes it. This is not a payer denial. |
| **16** (CO-16) | The claim lacks information needed to adjudicate it. The RARC says what is missing. |
| **18** (CO-18) | Exact duplicate claim or service. |
| **45** (CO-45) | Charge exceeds the contracted fee schedule; a routine write-off on paid claims. |
| **50** (CO-50) | Not deemed medically necessary by the payer; a candidate for an appeal with clinical support. |
| **197** (CO-197) | Precertification or prior authorization is absent. |

## Remark codes (RARCs)

| Code | Plain English |
|---|---|
| **M60** | Missing Certificate of Medical Necessity. |
| **N115** | The decision followed a Local Coverage Determination. |

