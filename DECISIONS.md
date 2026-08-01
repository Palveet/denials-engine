# Mini Denials Engine - decisions and review notes

## Data model

The model is run-scoped: `Run -> Claim -> ServiceLine / Adjustment / Denial -> Decision -> Artifact`. Run scoping is necessary because repeated uploads cannot safely share a global claim business key. The build plan's six entities omitted both the run/status record it later relied on and any upload isolation.

Denial is the recovery work unit. CLM-1008 proves a paid claim can still contain a denied service line, so denials optionally point to service lines. Decisions also point to the claim and may have no denial: the assignment says the model must produce an outcome for every claim, so CLM-1001 and CLM-1002 receive explicit no-action work items instead of disappearing from the decision stage or handoff.

Every CAS is retained as an adjustment. CO-45 is never promoted. PR-1 is promoted so the system can explicitly hand the deductible to the biller without treating it as payer-recoverable. Bare clearinghouse CARCs retain `group_code=UNKNOWN`; code descriptions can inform the model, but missing provenance is not fabricated.

The 835 parser reads payer identity from `N1*PR`, patient member ID from the positional NM108/NM109 pair, and service-level RARCs from the 2110 `LQ` loop. It uses an internal incomplete-claim draft while segments are arriving, but the canonical `ClaimData` cannot be created without a real service date. This avoids fake sentinel values in normalized data. Files fail loudly on malformed required segments; a production ingest service would quarantine individual transactions and report all segment errors.

## Reconciliation

The business key is claim ID within a run. When both sources contain a claim, the 835 wins fields that conflict because it is the payer adjudication record. The clearinghouse values are retained as structured discrepancies. CLM-1006 therefore keeps $1,450 and `LIN CHEN` while surfacing the CSV's $1,465 and abbreviated patient name.

Expected sample totals are 12 normalized claims, 10 denial records, and 12 decision work items. The build plan's illustrative UI text said “8 claims, 5 denials,” which is inconsistent with the supplied data.

## LLM boundary and safety

Code creates a compact fact sheet containing normalized claim/line/denial facts, source provenance, code descriptions, discrepancies, days since service, and whether a paid claim contains a denied line. The model makes the operational decision for each work item. Strict Pydantic and safety validation allow one correction retry. Provider failures or repeated invalid responses fail the run visibly; the application does not convert them into fabricated `unsure` decisions or generate artifacts from them.

Deterministic post-validation blocks these unsafe combinations:

- PR responsibility with a payer-recovery action or fax
- CARC 18 followed by a payer-recovery action before duplicate investigation
- payer-recovery actions when the group, denial code, or required authorization-timeliness fact is missing
- inconsistent action/fax/actor combinations
- `recoverable` without an action capable of recovering payer money
- an actionable decision when the work item has no denial

These are safety constraints, not an answer key: a safe model recommendation is retained even when it differs from an illustrative expected answer. Low confidence is flagged for human review without replacing the model's decision. The raw response, model name, prompt version, fact sheet, and validator flags remain visible. The model rationale may explain the request, but claim identifiers and cover-sheet facts always come from normalized records.

## Actors and fax semantics

The plan's oracle used `system->payer`, but the allowed actor is a single enum and this application does not own a fax transport. Fax actions therefore use actor `biller`. The system prepares one combined PDF (cover sheet followed by letter), and the biller verifies attachments and sends it. CO-16/M60 and CO-50 packets explicitly call out the required CMN or clinical records; the generated packet does not falsely claim those external files are present.

## Timeliness

Each upload is stamped with the server's current date, shown read-only in the UI, and code computes `days_since_dos` from that date. No 90-day retro-authorization rule is enforced because the primer says only that the window is limited and payer-specific. For CLM-1006, the guardrail blocks a retro-authorization request unless the required payer-specific timeliness fact exists. This avoids turning an undocumented assumption into policy while leaving the safe decision to the model.

## Runtime model policy

Runtime decisions use Anthropic's native Messages API, configured by `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, and the model-agnostic `LLM_MODEL` setting. Any model ID supported by that endpoint can be selected without changing application code. The model is forced to call one strict `record_denial_decision` tool whose schema matches the application contract; Pydantic and deterministic safety constraints still validate the result afterward. There is no fixture or dummy-decision mode, and no generated result set is committed. Missing configuration blocks the decision run with an explicit error. Unit tests use isolated test doubles that cannot be selected by the running application.

## QA performed

- Exact claim, line, RARC, BPR, CSV-format, merge, discrepancy, promotion, and guardrail assertions
- Dynamic payer-name, positional member-ID, line-level LQ, alternate-terminator, multiple-transaction, and BPR-reconciliation assertions
- Malformed model output correction/failure tests without a live key
- Provider-failure persistence test proving the run fails and produces no artifacts
- PDF required-field, non-empty, and page-count checks
- Deterministic ingestion, validation, persistence, document, and page-count tests
- Visual inspection of generated fax-packet and handoff pages
- Frontend production build and npm audit
- Fresh Docker build/run, browser upload/run/results/download flow

Live-provider calls are intentionally excluded from the default test suite because CI and reviewers may not share a key. The running application itself is live-provider-only.

## What I would build next

- certified EDI validation plus 999/277 acknowledgements rather than a known-subset parser
- payer-contract tables for retro-authorization and appeal deadlines
- explicit human approval before any real fax transport
- encryption at rest, a BAA-covered model provider, PHI-redacted telemetry, access controls, and audit retention for real data
- durable jobs/leases for multi-process deployments instead of in-process background tasks
- migrations and object storage rather than `create_all()` plus local files
- an eval set that grows with each novel CARC/RARC and records provider/model drift

## Other build-plan corrections

- The plan switched from React to “htmx polish” in its final build-order step; this implementation stays consistently React.
- “Pydantic models mirror database tables 1:1” was rejected. API/LLM contracts and persistence models serve different purposes.
- The fax output requirement is a document containing cover sheet + letter; separate downloads would make the grader reconstruct a packet.
- Extension-only upload validation was insufficient, so files also have a size limit, UTF-8 decoding, structural parsing, and explicit errors.
- A static hard-coded `days_since_dos=197` value would drift. Each run stores an explicit as-of date and computes the value from that date.
