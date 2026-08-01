# Mini Denials Engine

A local web application that reconciles an X12 835 with a clearinghouse denials export, asks Claude for a constrained decision on every normalized claim, validates the answer, and produces biller handoffs plus combined fax packets.

## Run locally (no Docker)

Prerequisites: Python 3.12 and Node.js 22 or newer.

```bash
cd "/Users/palveetsaluja/Documents/New project"
cp .env.example .env
```

Open `.env` and add your Anthropic settings:

```dotenv
ANTHROPIC_API_KEY=your-key
ANTHROPIC_BASE_URL=https://api.anthropic.com
ANTHROPIC_MODEL=claude-sonnet-5
```

Then start the application:

```bash
./scripts/run_local.sh
```

The script creates the Python environment if needed, installs missing dependencies, builds the frontend, and starts the server. Open <http://127.0.0.1:3000> and upload:

- `data/sample.835`
- `data/denials_export.csv`

Press `Ctrl+C` in Terminal to stop the server.

Runtime decisions use Anthropic's native Messages API and a strict structured tool call. There is no fixture or dummy-decision mode. If `ANTHROPIC_API_KEY` is absent, the API refuses to start a decision run instead of creating fake results.

### Manual local commands

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd frontend
npm install
npm run build:app
cd ..
.venv/bin/uvicorn app.main:app --reload --port 3000 --env-file .env
```

## Expected sample ingest

- 8 ERA claims + 6 CSV rows
- 12 unique claims after merging CLM-1004 and CLM-1006
- 10 denial records
- 12 model work items because the prompt requires an outcome for every claim
- 2 overlaps and 2 recorded CLM-1006 discrepancies
- BPR total of $3,345.00

The two files above are assignment-provided test inputs. They are not precomputed AI answers. Bare CSV codes remain group `UNKNOWN`; the code never silently changes them to `CO`.

## Outputs

Fax actions produce one PDF packet containing the required cover sheet followed by the letter. The biller remains the actor because this app prepares but does not transmit faxes. Packets call out missing external attachments instead of pretending they were included. The handoff is available as HTML and CSV, one row per normalized claim, and all outputs can be downloaded as a ZIP.

Generated files are created only after your live run under `artifacts/runs/<run-id>/`. No generated sample results are committed.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
```

Tests use isolated test doubles so they do not consume API credits. They cover parsing, deduplication, discrepancies, line-level denials, missing codes, guardrails, malformed provider output, persistence, required fax fields, and PDF page counts. Test doubles are never selectable by the running application.

## Architecture

`Run -> Claim -> ServiceLine/Adjustment/Denial -> Decision -> Artifact` is persisted in SQLite. Parsing, merge, fact construction, validation, and document generation are deterministic. Only the bounded per-work-item decision call crosses the configured LLM boundary.

See [ANSWER_KEY.md](ANSWER_KEY.md) for the sample claim-by-claim policy baseline and [DECISIONS.md](DECISIONS.md) for assumptions, plan corrections, safety decisions, QA, and known limitations.

## Optional Docker path

Docker support remains available for the assignment reviewer, but it is not required for local use:

```bash
ANTHROPIC_API_KEY=your-key ANTHROPIC_MODEL=claude-sonnet-5 docker compose up --build
```
