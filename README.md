# Mini Denials Engine

Reconciles an X12 835 remittance with a clearinghouse denials export, asks an LLM for a constrained
decision on every normalized claim, validates that decision against deterministic safety rules, and
produces fax-ready packets plus a biller handoff summary.

Stack: Python 3.12, FastAPI, SQLAlchemy on SQLite, React (Vite), WeasyPrint for PDFs.

## Run with Docker

```bash
cp .env.example .env       # then add your ANTHROPIC_API_KEY
docker compose up --build
```

Open <http://127.0.0.1:3000>.

`docker compose` reads `.env` automatically. To pass the key inline instead:

```bash
ANTHROPIC_API_KEY=sk-ant-... docker compose up --build
```

Plain Docker works too:

```bash
docker build -t denials .
docker run -p 3000:3000 -e ANTHROPIC_API_KEY=sk-ant-... -e LLM_MODEL=claude-sonnet-5 denials
```

## Run locally without Docker

One command, from the repository root:

```bash
./scripts/run_local.sh
```

Prerequisites are Python 3.12 and Node.js 22+. The script creates the virtualenv, installs missing
dependencies, builds the frontend into `app/static`, and starts the server on
<http://127.0.0.1:3000>. Press `Ctrl+C` to stop it.

On macOS, WeasyPrint needs Pango and Cairo: `brew install pango cairo gdk-pixbuf libffi`.

<details>
<summary>Equivalent manual commands</summary>

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
(cd frontend && npm install && npm run build:app)
.venv/bin/uvicorn app.main:app --port 3000 --env-file .env
```

</details>

## Configuration

Copy `.env.example` to `.env` and fill in the key. `.env` is gitignored and must never be committed.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | yes | — | Credential for the decision call |
| `LLM_MODEL` | yes | `claude-sonnet-5` | Exact provider model ID; change models without touching code. The committed run used `claude-opus-5` |
| `ANTHROPIC_BASE_URL` | no | `https://api.anthropic.com` | Override for a proxy or gateway |
| `DATABASE_URL` | no | `sqlite:///./denials.db` | SQLAlchemy URL |
| `MAX_UPLOAD_BYTES` | no | `5000000` | Per-file upload ceiling |

There is no fixture or dummy-decision mode. If the key or model is missing the API refuses to start
a decision run rather than fabricating results, and the UI says so.

## Using it

1. Upload `data/sample.835` and `data/denials_export.csv` on the home page.
2. Review the ingest summary, then start the run. Each claim gets one bounded model call.
3. The results page lists every claim with its outcome, next action, actor, confidence, guardrail
   flags, the fact sheet the model saw, and its raw response.
4. Download individual fax packets, the handoff summary as HTML or CSV, or everything as a ZIP.

Expected numbers for the provided files: 8 ERA claims plus 6 CSV rows merge into 12 normalized
claims with 10 denial records and 12 decision work items (CLM-1001 and CLM-1002 are paid, and still
get an explicit no-action decision so the handoff reconciles). BPR total is $3,345.00, with two
overlapping claims and two recorded CLM-1006 discrepancies.

## Committed results

`artifacts/runs/7252eced-6881-410c-b355-7882b3302a3c/` holds a complete run against the provided
files so you do not have to regenerate anything:

- `handoff-summary.html` / `.csv` — one row per normalized claim
- `clm-1004-submit-records.pdf`, `clm-1005-submit-appeal.pdf`, `clm-1008-submit-records.pdf` —
  fax packets, each a cover sheet followed by the letter
- matching `.html` sources and `all-artifacts.zip`

Those decisions came from live calls to **`claude-opus-5`**, recorded on every decision row along
with the prompt version, the fact sheet the model saw, and its raw response. To reproduce the run
against the same model, set `LLM_MODEL=claude-opus-5` in `.env`; any other model ID the endpoint
supports also works without code changes. Re-running lands in a new `artifacts/runs/<run-id>/`
directory and may differ on the genuinely ambiguous claims.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
```

All tests are deterministic and use isolated test doubles, so they consume no API credits and the
doubles cannot be selected by the running application. They cover 835 parsing (including alternate
segment terminators, multiple transaction sets, positional member IDs, and BPR reconciliation), CSV
normalization, merge and discrepancy behavior, every guardrail, the model correction retry and
failure paths, persistence, letter content, and PDF page counts.

## Architecture

```
upload → parse 835 + CSV → merge → fact sheet → model decision → guardrails → packets + handoff
```

`Run → Claim → ServiceLine / Adjustment / Denial → Decision → Artifact` is persisted in SQLite and
scoped per run, so repeated uploads never collide. Parsing, merging, fact construction, validation,
and document generation are all deterministic; only the bounded per-work-item decision call crosses
the LLM boundary. Claim identifiers and every cover-sheet field come from normalized records, never
from model output.

See [DECISIONS.md](DECISIONS.md) for the data model rationale, assumptions, safety constraints, QA,
and what I would build next.
