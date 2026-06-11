# POC Factory: Sequential Build Plan

Companion to `POC_FACTORY_ARCHITECTURE.md`. That doc says what to build; this one
breaks it into tasks small enough for Claude (claude-sonnet-4-6) to implement one at a
time without losing the plot.

## How to run this plan with Claude

1. **One task per session.** Each task below is sized to fit comfortably in one
   focused Claude Code session. Do not batch tasks; finishing and verifying one task
   before starting the next is the entire point.
2. **Give context, not the whole doc.** Each task lists which architecture sections to
   reference. Paste or point Claude at those sections plus the task block itself.
3. **Verify before moving on.** Every task ends with a Verify line. Run it. If it
   fails, fix it in the same session before starting the next task.
4. **Commit per task.** One task, one commit, message prefixed with the task ID
   (`T2.3: pgvector search with client scoping`). This makes rollback trivial when a
   later task reveals an earlier mistake.
5. **Tasks are strictly ordered** unless a "Depends on" note says otherwise. Frontend
   tasks (marked FE) can run in parallel with backend tasks if you want, but the
   default is just to go in order.
6. **Test anchors live in `POC_FACTORY_TEST_ANCHORS.md`.** It defines the sentinel
   facts the corpora must contain, the anchor use cases (UC-1 to UC-10), and the
   concrete test cases (TC-x.y) each task below must satisfy. Include the relevant
   UC/TC blocks in the prompt for any task that references them.

A good prompt template:

```
We are building POC Factory. Architecture reference: POC_FACTORY_ARCHITECTURE.md
sections <X>. Previous tasks completed: <list or "see git log">.

Implement task <ID> exactly as scoped below. Do not implement future tasks.

<paste task block>
```

---

## Phase 0: Foundations

### T0.1: Repo scaffold + FastAPI skeleton

Reference: architecture §7 (repo structure).

- Create the monorepo layout from §7 (empty dirs with `.gitkeep` where needed).
- `apps/api`: FastAPI app with `uv` (or `pip-tools`) project setup, a `/healthz`
  endpoint returning `{"status": "ok"}`, and a `make dev` (or task runner) target.
- Add `ruff` + `pytest` config and one trivial passing test.
- `.env.example` with `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `DATABASE_URL`.

Verify: `pytest` passes; `curl localhost:8000/healthz` returns ok.

### T0.2: Next.js scaffold (FE)

- `apps/web`: Next.js (App Router, TypeScript, Tailwind). One placeholder page.
- Dev rewrite/proxy so `/api/*` reaches the FastAPI app in development.

Verify: `npm run dev` serves the placeholder; a fetch to `/api/healthz` from the
browser returns ok.

### T0.3: Local Postgres with pgvector

- `infra/docker-compose.yml`: `pgvector/pgvector:pg16` service, volume, healthcheck.
- A `db/init.sql` (or first migration) enabling `CREATE EXTENSION IF NOT EXISTS vector`.
- Async SQLAlchemy (or `asyncpg` + a thin layer) wired into FastAPI with a
  `/healthz/db` endpoint that runs `SELECT 1`.

Verify: `docker compose up -d` then `/healthz/db` returns ok.

### T0.4: Client config schema + registry

Reference: architecture §3.

- Pydantic models mirroring the §3 YAML exactly (branding, corpus, agent, evals,
  limits). Validation errors must name the offending field and file.
- A `ConfigRegistry` that loads every `config/*.yaml` at startup and exposes
  `get(client_id)` and `all()`. Hot-reload in dev (file watcher or per-request reload
  behind a dev flag).
- `GET /api/clients` returning id, name, and branding for all clients.
- Unit tests: valid config loads; missing field fails with a readable message;
  duplicate `client_id` fails.

Verify: tests pass; a deliberately broken YAML makes startup fail with an error that
names the field.

---

## Phase 1: Clients exist

### T1.1: Discovery briefs (human + Claude writing task, not code)

- Write `briefs/acme-fab.md` and `briefs/meridian-insurance.md`: one page each with
  stakeholders, pain points, current process, success criteria, proposed scope.

Verify: both read like something you would hand a client VP.

### T1.2: Generate the Acme corpus

- Use Claude to generate 10 to 15 Markdown docs for a semiconductor fab equipment
  vendor: equipment manuals (with tables), maintenance FAQs, spare parts catalog,
  troubleshooting guides. Realistic part numbers, cross-references between docs.
- The generation prompt must include the Acme sentinel facts (AF-1 to AF-5 in
  `POC_FACTORY_TEST_ANCHORS.md` §1) verbatim, placed in their assigned documents.
- Convert 2 or 3 to PDF and keep both formats in `corpora/acme-fab/`.

Verify: docs are domain-plausible and reference each other; `grep` finds every AF
sentinel sentence verbatim in its assigned document.

### T1.3: Generate the Meridian corpus

- Same for a general insurer: policy wording documents, claims FAQs, underwriting
  guidelines, coverage exclusion lists. Include the kind of nested clause numbering
  real policy docs have.
- Plant the Meridian sentinel facts (MI-1 to MI-5) verbatim per
  `POC_FACTORY_TEST_ANCHORS.md` §1. No Acme content may appear in this corpus.

Verify: same bar as T1.2, including the sentinel `grep` check.

### T1.4: Client YAMLs + system prompts

Reference: architecture §3, §4.4 (the 2048-token cache minimum).

- `config/acme-fab.yaml` and `config/meridian-insurance.yaml`, complete per the schema.
- `prompts/acme-fab.md` and `prompts/meridian-insurance.md`: persona, domain context,
  grounding rules (answer only from retrieved sources, cite everything, say "I don't
  know" on empty retrieval), tone. Each must exceed 2048 tokens so the prefix caches.

Verify: registry loads both; a token count of each prompt exceeds 2048 (use the
`count_tokens` endpoint with `model: claude-sonnet-4-6`).

### T1.5: Branded shell + client switcher (FE)

Reference: architecture §5.1.

- `GET /api/clients/{id}/branding` on the backend.
- `/c/[client_id]` route rendering logo, colors (CSS variables from
  `primary_color`), assistant name, and an empty chat layout.
- A switcher component (dropdown or landing grid) listing all clients.

Verify: flipping between the two client URLs visibly rebrands with no code change.

---

## Phase 2: Retrieval

### T2.1: Embeddings wrapper

Reference: architecture §4.6.

- `apps/api/app/retrieval/embed.py`: `async def embed(texts: list[str]) ->
  list[list[float]]` calling Voyage AI. Batching (Voyage caps batch size), retry with
  backoff on 429/5xx, dimension constant exported.
- Unit test with the HTTP call mocked; one optional integration test behind an env
  flag.

Verify: mocked test passes; integration test returns vectors of the expected dimension.

### T2.2: Documents/chunks migrations

Reference: architecture §6.

- Migrations for `clients`, `documents`, `chunks` per §6, with
  `embedding vector(<dim>)`, an HNSW (or IVFFlat) index on `chunks.embedding`, and an
  index on `chunks.client_id`.

Verify: migration applies cleanly on a fresh database; rollback works.

### T2.3: Chunker

- Token-aware chunker: target `chunk_size` tokens with `overlap`, splitting on
  paragraph then sentence boundaries before falling back to hard splits. Keep per-chunk
  metadata: document title, source path, position.
- Tests covering size bounds, overlap, and a Markdown table staying intact within one
  chunk when under the limit.

Verify: tests pass.

### T2.4: Document parsing

- Loaders for `.md` (plain read), `.pdf` (pypdf or pdfplumber), `.html`
  (BeautifulSoup text extraction). Normalize to plain text + title.
- Test against 3 real files from `corpora/`.

Verify: each loader produces non-empty, sane text from a real corpus file.

### T2.5: Ingest CLI

Reference: architecture §5.3.

- `poc-factory ingest --client <id>` (Typer): walk the corpus dir, parse, hash
  content, skip unchanged docs, delete-and-replace changed docs, chunk, embed, upsert.
  Print a summary table (added / skipped / replaced, chunk counts).

Verify: first run ingests everything; second run reports all skipped; touching one doc
re-ingests only that doc.

### T2.6: Vector search

- `async def search(client_id, query, k=5, floor=0.x) -> list[Hit]`: embed the query,
  cosine top-k over `chunks` filtered by `client_id`, drop hits under the similarity
  floor, return text + document metadata.
- Test: plant a distinctive sentence in one client's corpus, ingest both clients,
  assert the planted chunk is hit #1 for that client and absent for the other.

Verify: the cross-client isolation test passes.

---

## Phase 3: The agent

### T3.1: Tool registry + shared tool definitions

Reference: architecture §5.2, shared tool-definition best practices (detailed
descriptions, when-to-use language).

- A registry mapping tool name -> (definition dict, async executor). Client configs
  select tools by name; unknown names fail at config load.
- Definitions for `search_docs` (input: `query`, optional `k`) and `get_document`
  (input: `document_id`), each with 3-4 sentence descriptions stating when to use them.
- Executors: `search_docs` calls T2.6; `get_document` returns full document text.

Verify: unit test resolves each client's tool list from config; unknown tool name in a
YAML fails at startup.

### T3.2: Agent loop, non-streaming

Reference: architecture §4.1, §4.2.

- `apps/api/app/agent/loop.py`: the manual loop from §4.2 with
  `client.messages.create` (streaming comes in T3.5). Model, max_tokens, effort, and
  system prompt from config. `thinking: {"type": "disabled"}`,
  `output_config: {"effort": cfg.agent.effort}`.
- Handle parallel tool calls (all results in one user message), typed exception
  handling, and a hard cap on loop iterations (e.g. 8) with a clean error.
- `POST /api/c/{client_id}/chat` (non-streaming JSON for now) creating/continuing a
  conversation, persisting messages.

Verify: `curl` a corpus question to each client and get a correct answer that used
`search_docs` (assert `tool_use` appears in the stored message history).

### T3.3: Citations via search_result blocks

Reference: architecture §4.3.

- Change the `search_docs` executor's result formatting to `search_result` blocks
  (source, title, content text block, `citations: {enabled: true}`) per §4.3.
- Map response content into a frontend-friendly shape: ordered segments of
  `{text, citations: [{source, title, cited_text}]}` and persist it on the message row.
- Test: ask a corpus question end to end and assert at least one
  `search_result_location` citation is present and its `source` matches an ingested
  document.

Verify: the citation assertion test passes for both clients.

### T3.4: Client-specific mock tools

- `tools/acme_fab/pricing_lookup.py`: takes part number + quantity, returns canned
  JSON (unit price, volume discount, lead time). `tools/meridian/coverage_check.py`:
  takes policy type + scenario, returns canned coverage verdict.
- Wire into the registry; enable via each client's YAML.

Verify: Acme answers "quote 50 units of part X" by calling `pricing_lookup` (visible in
history); the same question to Meridian does not have the tool available.

### T3.5: Streaming SSE

Reference: architecture §4.2, §4.3 (citations_delta).

- Swap the loop to `client.messages.stream(...)`. New SSE endpoint
  `POST /api/c/{client_id}/chat/stream` emitting events: `text` (delta), `citation`
  (from `citations_delta`), `tool` (name, when a tool call starts), `done` (usage
  summary).
- Keep persistence identical to T3.2 (use `get_final_message()` after the stream).

Verify: `curl -N` shows text deltas, at least one `citation` event, and a `done` event
for a corpus question.

### T3.6: Chat UI with live citations (FE)

Reference: architecture §5.1.

- Wire the chat layout from T1.5 to the SSE endpoint: streaming text, a "Searching
  documents..." indicator on `tool` events, inline citation markers ([1], [2]) that
  expand to show `cited_text` + title on click.

Verify: in the browser, ask each client a corpus question; answer streams with working
citation popovers.

### T3.7: Prompt caching

Reference: architecture §4.4.

- `cache_control: {"type": "ephemeral"}` on the last system block; deterministic tool
  ordering; a breakpoint on the latest turn's last content block for multi-turn reuse.
- Log `cache_read_input_tokens` / `cache_creation_input_tokens` per call.

Verify: turn 1 of a conversation shows cache creation; turn 2 shows nonzero
`cache_read_input_tokens`.

---

## Phase 4: Observability

### T4.1: Trace capture

Reference: architecture §5.5, §6.

- Migration for `conversations`, `messages` (if not already), `traces` per §6.
- Tracing wrapper around every model call and tool execution: span type, tool name,
  input/output (truncated), `tokens_in`, `tokens_out`, `cache_read_tokens`,
  `cost_usd` (computed per §4.7 rates: $3 input, $15 output, $0.30 cache read, $3.75
  cache write per MTok), `latency_ms`.

Verify: one chat turn produces spans whose summed cost matches a hand-computed number
from the usage fields.

### T4.2: Admin API

- Basic-auth-protected endpoints: list conversations (filter by client), get one
  conversation with messages + spans, per-client aggregates (conversations, total
  cost, mean cost/turn, p50/p95 latency, cache hit rate).

Verify: endpoints return correct numbers against seeded data in a test.

### T4.3: Admin console (FE)

- `/admin`: client stats cards, conversation table, conversation detail with a span
  timeline (who called what, tokens, cost per span).

Verify: replay any conversation end to end in the browser and see its full cost.

### T4.4: Budget guard + rate limiting

- Middleware: per-IP sliding-window rate limit (from config), per-client daily spend
  computed from `traces`, checked before each model call; both trip a 429 with a
  friendly JSON body. Daily reset by date boundary, not a cron.

Verify: tests simulate exceeding each limit and assert the 429 and the reset.

---

## Phase 5: Evals

### T5.1: Golden sets

- Start from the mandatory seed entries in `POC_FACTORY_TEST_ANCHORS.md` §4, then
  generate the remaining candidate Q&A pairs with Claude from the corpus (question,
  golden answer, source document id, refusal flag). Hand-review and keep 25-40 per
  client in `evals/<client>/golden.jsonl`, including 3-5 refusal rows.
- A loader + schema validation for the JSONL.

Verify: loader validates both files; all §4 seed entries present; spot-check 5
generated pairs per client by hand.

### T5.2: Retrieval eval

- `poc-factory eval --client <id> --retrieval-only`: for each golden question, run
  T2.6 search, score hit@k (golden source document in top k). Print per-client table.

Verify: command prints hit@5 for both clients; numbers are plausible (>70%).

### T5.3: LLM judge

Reference: architecture §4.5.

- Judge module calling `claude-sonnet-4-6` with the §4.5 structured-output schema.
  Input: question, golden answer, assistant answer, cited chunks. No citations on this
  call (structured outputs and citations are incompatible).
- Unit test with a mocked API response; one real-call test behind an env flag with an
  obviously-correct and obviously-wrong answer pair.

Verify: the wrong answer scores lower than the correct one on the real-call test.

### T5.4: Full eval run + scorecard

- `poc-factory eval --client <id>`: run every golden question through the real agent
  loop, collect judge scores plus p50/p95 latency and cost/query from the trace data,
  write a row to `eval_runs`, emit a Markdown scorecard.
- `--all` flag for both clients; paste the table into the README.

Verify: the §5.4 target table renders with real numbers for both clients.

### T5.5: Evals in CI

- GitHub Actions: lint + unit tests on every PR; eval suite on main (or nightly, to
  bound API spend) with a README badge showing the latest answer-quality score.

Verify: a PR that intentionally breaks retrieval shows the failure in CI.

---

## Phase 6: Ship

### T6.1: Containerize

- Production Dockerfiles for `apps/api` (uvicorn, non-root) and `apps/web`
  (standalone Next.js build). Compose file runs the full stack locally in prod mode.

Verify: full stack runs from containers locally; chat works end to end.

### T6.2: Cloud Run deploy

- Provision: Artifact Registry, two Cloud Run services, Cloud SQL (or Neon)
  Postgres with pgvector, Secret Manager for API keys. Script or document every step
  in `infra/README.md`. Deploy and run ingestion against the prod database.

Verify: the public URL serves both clients with citations working.

### T6.3: Demo hardening

- Cloud Scheduler job hitting an authenticated reset endpoint nightly (truncate
  conversations/messages/traces, keep corpus and eval data). Confirm rate limits and
  budget guard work on prod. Add a "this is a demo, data resets nightly" notice.

Verify: trigger the reset manually; demo data clears, corpus survives.

### T6.4: Switcher and UI polish (FE)

- Loading states, empty states, error toasts (including the friendly 429s), switcher
  transition, mobile pass.

Verify: you would happily open it in an interview.

---

## Phase 7: Packaging (human tasks)

These are yours, not Claude's, though Claude can draft copy.

- **T7.1**: 2-3 minute demo video told as a client story: brief, config file, live
  branded assistant, eval dashboard.
- **T7.2**: README: pitch line, architecture diagram, eval table, video link, all
  above the fold.
- **T7.3**: Blog post "Anatomy of a one-hour enterprise AI POC" + portfolio card
  (Problem / Built / Result with real numbers).
- **T7.4 (stretch)**: record the onboarding timer run: doc dump to working POC in
  under an hour, visible clock.

---

## Dependency notes

- FE tasks (T0.2, T1.5, T3.6, T4.3, T6.4) only depend on their backend counterparts
  being done, not on the rest of the sequence.
- T3.7 (caching) can slot anywhere after T3.2.
- Phase 5 needs Phase 3 complete and Phase 4's trace data for the cost/latency columns.
- Nothing in Phases 0-5 requires GCP; everything runs on docker-compose until T6.2.
