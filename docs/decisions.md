# Decision log

Every non-obvious choice in Configent, with the reasoning that produced it. Decisions
are referenced by ID from [`docs/support-agent-plan.md`](support-agent-plan.md) and from
code comments.

**Status key:** LOCKED — settled, build to it. OPEN — must be settled before the task
that depends on it. SUPERSEDED — kept for the reasoning, no longer in force.

---

## Part 1 — Platform decisions (pre-pivot, in force)

### P1 — Single deployment, config-switched tenancy · LOCKED
One codebase and one deployment serve every client; a client is a YAML file plus a
corpus directory. **Why:** the platform's claim is repeatability — a per-client fork
disproves it. Adding a client requires no code change.
**Consequence:** `client_id` is a column on every table and a filter in every query.
Correctness depends on discipline in the retrieval and conversation layers rather than
on database-enforced isolation; see P8.

### P2 — pgvector, not a dedicated vector database · LOCKED
**Why:** one database for chunks, conversations, traces and eval runs. No second vendor
to provision, approve or explain. Enterprise prospects already run Postgres.
**Consequence:** a very large corpus would eventually want HNSW tuning per client. Not a
constraint at demo scale.

### P3 — Manual agent loop, no framework · LOCKED
The loop is a `while` over `messages.create` in `apps/api/app/agent/loop.py`.
**Why:** tracing, cost accounting, budget enforcement and streaming all live inside the
loop. Owning it means owning those. It is also short enough to whiteboard.
**Consequence:** features a framework would supply (retries, checkpointing, structured
output enforcement) are hand-built — which is the point of the support-agent pivot.

### P4 — Citations via `search_result` blocks · LOCKED
`search_docs` returns Anthropic `search_result` content blocks with `citations.enabled`,
so the API attaches `search_result_location` citations at generation time.
**Why:** citations parsed by the API cannot reference a document that wasn't retrieved.
Prompt-based quoting can, and does.
**Consequence:** citations are all-or-nothing per request — every search result in a
request must enable them, which `search_docs` does unconditionally.

### P5 — Prompt caching with a per-turn breakpoint · LOCKED
System prompt cached once; a cache breakpoint is applied to the last content block of
the latest message, per call, never baked into stored history.
**Why:** a breakpoint written into history accumulates one marker per loop iteration and
blows the four-breakpoint request limit.
**Consequence:** tool definitions must serialise in a stable order — hence
`_sorted_tool_defs`. Reordering `tools:` in a YAML must not invalidate the cache prefix.

### P6 — Voyage AI embeddings (`voyage-3`) · LOCKED
**Why:** asymmetric query/document embeddings, strong retrieval scores on technical
corpora. **Consequence:** a second API key and a second vendor outage surface.

### P7 — SSE, not WebSockets · LOCKED
**Why:** chat streaming is one-directional; SSE is proxy-friendly and needs no
connection lifecycle management. **Consequence:** no server-push outside a live request,
and no automatic reconnect in the current `fetch` + `ReadableStream` client (see D15).

### P8 — Application-level tenancy, no row-level security · LOCKED
**Why:** demo scale, single trusted deployment, and RLS adds a policy layer to explain
without changing observable behaviour. **Consequence:** the `client_id` path param is a
trusted value guarded by explicit ownership checks (`_prepare_conversation`, D9), not by
the database. Say this plainly when asked; it is a real limitation, not a hidden one.

### P9 — Homegrown tracing into Postgres · LOCKED
**Why:** the trace data is needed anyway for cost and eval tables, so a third-party
tracing service adds setup without adding capability.
**Consequence:** no distributed tracing UI. The `Trace` table is the source of truth for
every cost number in this repo.

### P10 — Config validated at startup, never at request time · LOCKED
Unknown tool names, bad enums and missing fields fail the process at load, naming the
field and the file. **Why:** a config error should be visible before a user sees it.

### P11 — Markdown-only corpora · SUPERSEDED-IN-PART (deferred 2026-06-12)
PDF ingestion was deferred until the agent loop was solid. `parse_pdf` exists but is
untested against real corpus files. When picked up: convert 2–3 Acme docs to PDF and
ingest the PDF *instead of* the `.md` (move the markdown originals to a `sources/`
subfolder the ingester skips) — indexing both formats double-indexes the same text.

---

## Part 2 — Support-agent pivot decisions

Eight decisions govern the four-week build. Each one is here because it answers a question
someone will actually ask; everything else that could have been a decision is in
[Known gaps](#part-3--known-gaps) instead, where it belongs.

If implementation pressure argues for changing one, change it here first with a date;
don't quietly diverge in code.

### D1 — The knowledge base is public Google Cloud documentation · LOCKED
The agent's corpus is a curated snapshot of public Cloud Run, GKE and IAM documentation in
`corpora/gcp-platform-support/`, each file carrying its source URL and a CC BY 4.0
attribution.

**Why:** the docs describe platform behaviour and contain nothing about any user's own
project, so "what is my quota?" is unanswerable *by construction* — not unanswerable
because a fact was withheld from a corpus we also wrote. That makes the escalation branch
structural rather than staged. Ground truth is also externally checkable: a sentinel
verifies against the upstream page, not just against this repo.

**Consequence:** the corpus is a point-in-time snapshot and will drift from upstream — say
so rather than implying a live sync. Google Cloud documentation is licensed CC BY 4.0 and
code samples Apache 2.0, permitting reuse with attribution and a link back; verified
against https://developers.google.com/terms/site-policies on 2026-08-30.

### D2 — The guardrail is two signals, evaluated in code · LOCKED
Escalate when `retrieval_confidence < escalate_below` **OR**
`groundedness.confidence < confidence_threshold`, where:

1. `retrieval_confidence` is max cosine similarity across hits — deterministic, no model.
2. `groundedness.confidence` is a float 0–1 from a cheap-model call returning a validated
   `GroundednessScore{supported, confidence, missing_info, reasoning}`.

The comparison is an `if` in `pipeline.py`. Both thresholds live in
`config/gcp-platform-support.yaml`. The answering model is never given
`create_escalation_ticket` in its tool list and is never asked whether to escalate.

Zero hits is a third path: escalate immediately without a score call, since there is
nothing to score. And `escalate_below` is a *different* floor from the pre-existing
`retrieval_drop_floor` that discards weak chunks inside `search()` — set the escalation
floor at or below the drop floor and it can never fire.

**Why:** one signal alone is either brittle (similarity misses "retrieved the right
document, which doesn't contain the answer") or unfalsifiable (a model score with no
floor). And a guardrail expressed in a prompt is a suggestion — if the model is the thing
whose confidence is in doubt, it can't also be the thing that decides what to do about low
confidence. A model cannot be talked out of an `if` statement.

**Consequence:** thresholds are hand-tuned against the golden set — say so, a tuned
threshold with a stated method beats a magic number. The answering stage has no escape
hatch when retrieval is thin; if retrieval was thin, the branch shouldn't have routed
there. The cheap scoring model is also the router in the week-3 cost comparison, so this
decision carries that artifact too. Because the answer call uses citations, it cannot also
use `output_config.format` — so the final `SupportAnswer` is assembled in Python from the
stage outputs rather than generated.

### D3 — Durability writes commit independently; resume is explicit · LOCKED
Run state is written through `checkpoint_session()` — a short-lived `AsyncSession` that
commits immediately — never the request-scoped session. A stream that closes without
`done` surfaces an "interrupted — Resume" control carrying the `run_id`. No automatic
reconnect.

**Why:** `stream_turn` commits once at the end and calls `db.rollback()` on any failure, so
checkpoints written on that session are erased by exactly the crash they exist for. And
`ChatPanel.tsx` reads the stream with `fetch` + `ReadableStream`, not `EventSource`, so
there is no built-in reconnect to lean on.

**Consequence:** partial state is possible — a run can have committed steps and an
uncommitted conversation turn, so resume treats run state as truth, not `Message`. Explicit
resume is the better demo anyway: the interruption and the recovery read as two events
rather than a stream that silently heals.

### D4 — A ticket is filed exactly once · LOCKED
Two independent guards: `Idempotency-Key: {run_id}:{stage_seq}` on the HTTP call, and a
check of the run's stored `ticket_id` before issuing it. The ticket service assigns the id;
the client never computes it.

**Why:** belt and braces, because the failure mode is a duplicate ticket in someone's
queue. The key covers the crash-and-resume path; the state check covers the same-turn path,
where `asyncio.gather` over two tool_use blocks would file twice with no crash involved.
Content-derived ids (`crc32(subject + category)`) fail both: they collide across unrelated
sessions, and no real ticketing system behaves that way.

**Consequence:** ticket ids stop being deterministic across test runs — tests assert on
call count and payload, not on a literal id. The tool needs `run_id` in its executor
kwargs, a signature change touching every tool; do it once, in W1.

### D5 — Pipeline and loop coexist, selected by config · LOCKED
`AgentConfig.mode: "loop" | "pipeline"`, default `loop`. `gcp-platform-support` runs
`pipeline`; Acme, Meridian and `configent-support` stay on `loop`, dormant.

**Why:** deleting the loop throws away working code and the "when would you *not* use a
fixed pipeline" answer, which is a good one — exploratory tool use wants a loop, a workflow
with a mandatory guardrail wants explicit stages.

**Consequence:** two engines to keep tested. Shared primitives (`_execute_tool`,
`_collect_segments`, `UsageTotals`, pricing) live in `loop.py` and are imported by
`pipeline.py`, never copied.

### D6 — The crash is injected, not signalled · LOCKED
`CRASH_AFTER=<stage>` raises `SystemExit` at a defined point; `make crash-demo` wraps it.

**Why:** `kill -9` mid-sentence is unrepeatable and lands wherever it lands. A named
injection point is deterministic and assertable in a test.

**Consequence:** if challenged that it isn't a real crash — the process still dies with
uncommitted work and an open SSE connection, so the failure mode is identical and only the
timing is chosen. Keep `kill -9` as a live backup.

### D7 — The golden set is committed before the runner exists · LOCKED
All 25–30 expected outcomes land in one dated commit before any line of
`evals/runner/run_evals.py` is written. The README states plainly that the ticket API is a
mock service in this repo.

**Why:** commit order is the only evidence the expectations weren't backfilled after seeing
outputs, and it's the claim most likely to be probed.

**Consequence:** some expectations will turn out ambiguous. Fix them in a separate, later
commit with a note — never amend the original.

### D8 — Cost is priced per model · LOCKED
Replace the module-level `_PRICE_*` constants with `_PRICES: dict[str, ModelPrice]` keyed
by model id; price each call by the model that served it. An unknown model id raises at
config load.

**Why:** the current constants are Sonnet 4.6 rates applied to every call, and
`gcp-platform-support.yaml` already runs Haiku — so every cost number in the repo is wrong
today. Week 3's headline artifact is a cost comparison; it has to be built on real prices.

**Consequence:** prices are hardcoded and will drift. Date the comment; don't build a price
API.

---

## Part 3 — Known gaps

Things this deliberately does not do. This is a POC: the point is that each of these was a
choice, and that the choice can be named. Saying "I didn't build that, here's why, here's
what it would take" is a better answer than a half-built version of it.

| Gap | Why it's acceptable here | What production would need |
|---|---|---|
| **One ticket per run, not per conversation.** A user rephrasing the same unanswerable question files a second ticket. | Run-level idempotency (D4) covers the crash path, which is the one being demonstrated. Conversation-level dedupe is product policy, not a reliability property. | A `conversation_id → open ticket` lookup, and the escalate branch referencing the existing ticket. |
| **Exhausted ticket retries mark the run `failed_ticket` and log it.** No dead-letter table, no drain endpoint. | The user is still told their question was recorded, and the failure is visible. A queue nobody drains isn't a queue — and at POC scale the operator is you, reading logs. | A dead-letter table with list and retry endpoints, and someone on the hook for draining it. |
| **Schema validation failure escalates rather than re-asking.** | Fail-closed is easier to defend than a retry budget, and the escalate path already exists. | A bounded re-ask before falling through, if the failure rate justifies it. |
| **Runs that never finish stay `running`.** No sweeper. | A worker is real infrastructure with real failure modes for a problem that, at this scale, is a manual `UPDATE`. | A TTL and a background sweep. |
| **Daily budget is checked at entry only.** A run that exhausts budget mid-flight completes. | Killing a run to save a cent leaves orphaned state and a filed ticket with no confirmation — worse than the overspend, which is bounded by one run's cost. | Mid-run checks at stage boundaries. |
| **`client_id` is a trusted path parameter** guarded by application-level ownership checks, not row-level security (P8). | Single trusted deployment, demo scale. | Postgres RLS, so isolation holds even when application code has a bug. |
| **The rate limiter is in-memory and single-process.** | One API instance. | Redis, or any shared store. |
| **The ticket service is a mock in this repo.** | It exercises the real integration shape — HTTP, schema, idempotency key, retries, failure injection — without a vendor account. | A real ticketing API. The client swaps; the retry and idempotency paths don't. |
