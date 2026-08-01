# Mini Denials Engine - decisions

## Data model

The model is run-scoped: `Run -> Claim -> ServiceLine / Adjustment / Denial -> Decision -> Artifact`. Run scoping is necessary because repeated uploads cannot safely share a global claim business key. `Run` also carries the status the progress UI polls, so nothing about a run's state lives outside the database.

API and LLM contracts are separate from the persistence models rather than mirroring the tables one to one. A Pydantic schema that doubles as a table definition ends up serving two masters: the model's tool schema needs to be narrow and enum-constrained, while the table needs to store whatever the run actually produced, including a rejected answer.

Denial is the recovery work unit. CLM-1008 proves a paid claim can still contain a denied service line, so denials optionally point to service lines. Decisions also point to the claim and may have no denial: the assignment says the model must produce an outcome for every claim, so CLM-1001 and CLM-1002 receive explicit no-action work items instead of disappearing from the decision stage or handoff.

Every CAS is retained as an adjustment. CO-45 is never promoted. PR-1 is promoted so the system can explicitly hand the deductible to the biller without treating it as payer-recoverable. Bare clearinghouse CARCs retain `group_code=UNKNOWN`; code descriptions can inform the model, but missing provenance is not fabricated.

The 835 parser reads payer identity from `N1*PR`, patient member ID from the positional NM108/NM109 pair, and service-level RARCs from the 2110 `LQ` loop. It uses an internal incomplete-claim draft while segments are arriving, but the canonical `ClaimData` cannot be created without a real service date. This avoids fake sentinel values in normalized data. Files fail loudly on malformed required segments; a production ingest service would quarantine individual transactions and report all segment errors.

Uploads are not trusted on their file extension. Each file is size-capped, decoded as UTF-8, and structurally parsed before anything is persisted, and every rejection says what was wrong rather than failing generically.

## Reconciliation

The business key is claim ID within a run. When both sources contain a claim, the 835 wins fields that conflict because it is the payer adjudication record. The clearinghouse values are retained as structured discrepancies. CLM-1006 therefore keeps $1,450 and `LIN CHEN` while surfacing the CSV's $1,465 and abbreviated patient name.

Expected sample totals are 12 normalized claims, 10 denial records, and 12 decision work items.

## LLM boundary and safety

Code creates a compact fact sheet containing normalized claim/line/denial facts, source provenance, code descriptions, discrepancies, days since service, and whether a paid claim contains a denied line. The model makes the operational decision for each work item. Strict Pydantic and safety validation allow one correction retry. Provider failures or repeated invalid responses fail the run visibly; the application does not convert them into fabricated `unsure` decisions or generate artifacts from them.

Deterministic post-validation blocks these unsafe combinations:

- PR responsibility with a payer-recovery action or fax
- CARC 18 followed by a payer-recovery action before duplicate investigation
- payer-recovery actions when the group, denial code, or required authorization-timeliness fact is missing
- inconsistent action/fax/actor combinations
- `recoverable` without an action capable of recovering payer money
- an actionable decision when the work item has no denial

These are safety constraints, not an answer key: a safe model recommendation is retained even when a human might have chosen differently. Low confidence is flagged for human review without replacing the model's decision. The raw response, model name, prompt version, fact sheet, and validator flags remain visible. The model rationale may explain the request, but claim identifiers and cover-sheet facts always come from normalized records.

## Actors and fax semantics

Sending a fax is arguably a `system -> payer` handoff, but `actor` is a single-value enum and this application does not own a fax transport. Fax actions therefore use actor `biller`. The system prepares one combined PDF (cover sheet followed by letter), and the biller verifies attachments and sends it. The packet does not falsely claim external files are present; it names what still has to be attached.

The letter carries only what the payer needs to act. The model's rationale is an audit record, so it lives in the handoff summary and the results UI rather than on a page addressed to the payer's claims review team.

Letter content is driven by the denial, not by the chosen action. The requested enclosure comes from the CARC and RARCs — M60 asks for the CMN, CO-50 asks for clinical records supporting necessity, CO-197 asks for the authorization request — and the remark-code sentence is omitted entirely when the payer sent no remark. A letter that misstates the payer's own reason for denying is worse than no letter.

The fact sheet supplies HCPCS descriptions alongside the CARC and RARC descriptions, so the model never has to describe a procedure from memory. Codes the application cannot describe are labelled unknown, and prompt rule 11 forbids supplying a descriptor.

## Timeliness

Each upload is stamped with the server's current date, shown read-only in the UI, and code computes `days_since_dos` from that date. No 90-day retro-authorization rule is enforced because the primer says only that the window is limited and payer-specific.

The consequence is deliberate and worth stating plainly: because nothing in the supplied files carries a payer-specific retro-authorization deadline, the CO-197 guardrail currently blocks `request_retro_auth` on every CO-197 denial, so CLM-1006 always routes to a payer call. The retro-authorization letter template exists and is tested, but no claim in this dataset can reach it. The alternative was inventing a deadline, which would turn an undocumented assumption into policy. The real fix is a payer-contract table supplying the window, which is listed under what I would build next.

## Runtime model policy

Runtime decisions use Anthropic's native Messages API, with the model ID read from a single `LLM_MODEL` setting so a different model needs no code change. The model is forced to call one strict `record_denial_decision` tool whose schema matches the application contract; Pydantic and the deterministic safety constraints still validate the result afterward. There is no fixture or dummy-decision mode: missing configuration blocks the run with an explicit error rather than inventing a decision, and the test doubles cannot be selected by the running application.

One complete run against the provided files is committed under `artifacts/runs/` so the reviewer does not have to regenerate anything. Those decisions came from a live model call, not from a fixture. Only that one run is committed: the decide stage is genuinely non-deterministic on the ambiguous claims, and shipping several runs would leave the reviewer guessing which set is authoritative. CLM-1005 and CLM-1008 are where repeated runs disagree most, both CO-50 medical-necessity denials that a model can legitimately route to either `submit_appeal` or `submit_records`. The guardrails accept both because both are safe; only the framing of the outgoing letter differs.

## QA performed

35 deterministic tests, no live provider calls:

- Exact claim, line, RARC, BPR, CSV-format, merge, discrepancy, promotion, and guardrail assertions
- Dynamic payer-name, positional member-ID, line-level LQ, alternate-terminator, multiple-transaction, and BPR-reconciliation assertions
- Ingest negative paths: a non-835 upload, a truncated CLP segment, a missing CSV column, and an unparseable amount that must name the offending row
- Letter-content assertions: no CMN demand on a CO-50 that never cited one, no remark sentence when the payer sent no RARC, remark codes expanded when they exist, and a readable letter when the CARC itself is missing
- Fact-sheet assertions that a known HCPCS carries its supplied description and an unknown one is labelled unknown, so the model is never left to supply a procedure description from memory
- Handoff assertion that validator flags and source discrepancies stay in separate columns, and a packet assertion that the model rationale never reaches the payer
- Malformed model output correction/failure tests
- Provider HTTP failures surface the provider's own message (billing, rate limit, model access) rather than a bare status code
- Provider-failure persistence test proving the run fails and produces no artifacts
- PDF required-field, non-empty, and page-count checks
- Visual inspection of every committed fax packet and the handoff pages
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
