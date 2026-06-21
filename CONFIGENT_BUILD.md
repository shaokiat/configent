# Configent: Build Plan and Test Anchors

Companion to `CONFIGENT.md`. That doc says what to build; this one breaks it into tasks
small enough to implement one at a time, and pins the concrete test anchors every task
is verified against.

**Read sections 1–2 before starting T1.2/T1.3.** The sentinel facts in section 1 must
be authored into the corpora verbatim, or none of the downstream tests have stable
ground truth.

---

## How to run this plan

1. **One task per session.** Each task is sized to fit comfortably in one focused
   session. Finish and verify one task before starting the next.
2. **Verify before moving on.** Every task ends with a Verify line. Run it. Fix
   failures in the same session.
3. **Commit per task.** One task, one commit, message prefixed with the task ID
   (`T2.3: pgvector search with client scoping`). Makes rollback trivial.
4. **Tasks are strictly ordered** unless a "Depends on" note says otherwise. Frontend
   tasks (marked FE) can run in parallel with backend tasks, but the default is to go
   in order.

A good prompt template for Claude:

```
We are building Configent. Architecture reference: CONFIGENT.md sections <X>.
Previous tasks completed: <list or "see git log">.

Implement task <ID> exactly as scoped below. Do not implement future tasks.

<paste task block>
```

---

## Part 1: Test Anchors

### 1. Sentinel facts (plant these in the corpora verbatim)

Generated corpora are nondeterministic, so we pin a small set of facts that must appear
exactly as written. Tests retrieve, cite, and judge against these. Keep them in
`evals/sentinels.yaml` as the single source of truth; the corpus generation prompts in
T1.2/T1.3 must include them.

#### Acme Fab Equipment

| ID | Fact (verbatim sentence to plant) | Document |
|----|------------------------------------|----------|
| AF-1 | "The PX-900 plasma etcher requires chamber seal replacement every 1,200 RF hours." | `px900-maintenance-manual.md` |
| AF-2 | "Error code E-417 indicates a helium backside cooling leak and requires immediate chamber vent." | `px900-troubleshooting-guide.md` |
| AF-3 | "The recommended idle standby temperature for the LT-200 load lock is 45 degrees Celsius." | `lt200-operations-manual.md` |
| AF-4 | "Field service response time for Tier 1 contracts is 4 business hours." | `service-contracts-faq.md` |
| AF-5 | Part `PX900-SEAL-A2` exists in the spare parts catalog with description "chamber seal kit, fluoroelastomer". | `spare-parts-catalog.md` |

Mock `pricing_lookup` canned data (must agree with the catalog):

```json
{
  "PX900-SEAL-A2": {"unit_price_usd": 1840.00, "volume_discount": {"min_qty": 10, "pct": 8}, "lead_time_days": 21},
  "LT200-VALVE-B1": {"unit_price_usd": 412.50, "volume_discount": {"min_qty": 25, "pct": 5}, "lead_time_days": 10}
}
```

#### Meridian Insurance

| ID | Fact (verbatim sentence to plant) | Document |
|----|------------------------------------|----------|
| MI-1 | "Clause 4.2.1: Water damage arising from gradual seepage over a period exceeding 14 days is excluded from coverage." | `home-policy-wording.md` |
| MI-2 | "The standard excess for accidental damage claims under the HomeShield Plus plan is $500." | `home-policy-wording.md` |
| MI-3 | "Claims must be lodged within 30 days of the insured event unless exceptional circumstances apply." | `claims-process-faq.md` |
| MI-4 | "Properties located within 100 metres of a coastline require a flood risk assessment before underwriting." | `underwriting-guidelines.md` |
| MI-5 | "Jewellery items valued above $5,000 must be individually listed on the policy schedule." | `coverage-exclusions-list.md` |

Mock `coverage_check` canned data (must agree with the policy wording):

```json
{
  "burst_pipe_sudden": {"covered": true, "excess_usd": 500, "clause": "3.1.4"},
  "gradual_seepage": {"covered": false, "clause": "4.2.1"},
  "unlisted_jewellery_over_5000": {"covered": false, "clause": "7.3.2"}
}
```

#### Cross-client isolation sentinel

AF-1 must appear only in the Acme corpus and MI-1 only in the Meridian corpus. The
isolation tests depend on this; do not let corpus generation bleed domain content
across clients.

---

### 2. Anchor use cases

Each use case is an end-to-end scenario with expected observable behavior. They double
as: acceptance criteria during implementation, the backbone of the e2e test suite, the
script for the demo video, and seeds for the golden sets.

#### UC-1: Single-fact answer with citation (the core loop)

- **Client:** acme-fab
- **User:** "How often does the chamber seal on the PX-900 need replacing?"
- **Expected:**
  - Exactly one `search_docs` tool call (input `query` mentions seal/PX-900).
  - Answer states 1,200 RF hours.
  - At least one `search_result_location` citation with `title` matching the PX-900
    maintenance manual and `cited_text` containing the AF-1 sentence.
- **Anchors tasks:** T3.2, T3.3, T3.6.

#### UC-2: Multi-document synthesis

- **Client:** acme-fab
- **User:** "The PX-900 is showing error E-417. What does it mean and how fast can a
  field engineer get here on a Tier 1 contract?"
- **Expected:**
  - Answer covers both AF-2 (helium leak, chamber vent) and AF-4 (4 business hours).
  - Citations reference two distinct documents (`document_title` differs across the
    citations).
- **Anchors tasks:** T3.2, T3.3, T5.3 (good judge fixture: drop one half of the answer
  to make the "wrong" variant).

#### UC-3: Agent chooses a client tool

- **Client:** acme-fab
- **User:** "Quote me 50 chamber seal kits for the PX-900."
- **Expected:**
  - The loop calls `search_docs` or the spare parts knowledge to resolve
    `PX900-SEAL-A2`, then calls `pricing_lookup` with that part number and qty 50.
  - Answer includes $1,840 unit price, the 8% volume discount (qty 50 > min 10), and
    the 21-day lead time.
  - Trace shows both tool spans in order.
- **Anchors tasks:** T3.4, T4.1.

#### UC-4: Out-of-corpus refusal (grounding)

- **Client:** acme-fab
- **User:** "What's your CEO's opinion on quantum computing?"
- **Expected:**
  - Either no search hit above the similarity floor or unhelpful hits; the assistant
    says it does not have that information in its documentation, offers what it can
    help with, and invents nothing.
  - Zero citations in the answer.
- **Anchors tasks:** T2.6 (similarity floor), T3.2 (system prompt grounding rules),
  T5.1 (include 3-5 of these per client in the golden set, judged on refusal).

#### UC-5: Cross-client isolation

- **Client:** meridian-insurance
- **User:** "How often does the chamber seal on the PX-900 need replacing?"
- **Expected:**
  - `search_docs` returns nothing relevant (AF-1 is not in Meridian's corpus).
  - Meridian's assistant refuses per UC-4 behavior; it must not answer with Acme data.
- **Anchors tasks:** T2.6 (the planted-chunk isolation test is the unit-level version
  of this), T3.2.

#### UC-6: Policy exclusion with clause citation (Meridian flagship)

- **Client:** meridian-insurance
- **User:** "My ceiling has been leaking slowly for about a month. Am I covered?"
- **Expected:**
  - Answer says not covered, names gradual seepage and the 14-day threshold, and cites
    clause 4.2.1 (MI-1) via a `search_result_location` whose `cited_text` contains the
    clause sentence.
  - If `coverage_check` is called with `gradual_seepage`, its verdict must agree with
    the cited clause (this is the demo's "tool and corpus agree" moment).
- **Anchors tasks:** T3.3, T3.4.

#### UC-7: Multi-turn follow-up with caching

- **Client:** meridian-insurance
- **Turn 1:** "What's the excess on accidental damage claims for HomeShield Plus?"
  (expects $500, cites MI-2)
- **Turn 2:** "And how long do I have to lodge a claim?" (expects 30 days, cites MI-3;
  the pronoun-free follow-up must still resolve in conversation context)
- **Expected:** turn 2's usage shows `cache_read_input_tokens > 0`.
- **Anchors tasks:** T3.7, T3.2 (multi-turn persistence).

#### UC-8: Budget guard trips

- **Client:** any, with `daily_budget_usd` temporarily set to $0.01 in a test config.
- **Expected:** the second or third request returns HTTP 429 with the friendly JSON
  body, the conversation history is not corrupted, and the next calendar day (or a
  clock-mocked reset) restores service.
- **Anchors tasks:** T4.4.

#### UC-9: New client onboarding (the timer story)

- **Steps:** write `config/newco.yaml`, drop 5 docs in `corpora/newco/`, run
  `configent ingest --client newco`, open `/c/newco`.
- **Expected:** branded assistant answering corpus questions with citations, zero code
  changes, under an hour wall clock.
- **Anchors tasks:** the whole architecture; this is T7.4's script. Keep `newco`
  out of version control or delete after the run.

#### UC-10: Streaming event contract

- **Client:** acme-fab, question from UC-1 against `POST /api/c/acme-fab/chat/stream`.
- **Expected SSE sequence (the frontend is built against exactly this):**

```
event: tool      data: {"name": "search_docs", "status": "start"}
event: tool      data: {"name": "search_docs", "status": "end"}
event: text      data: {"delta": "The chamber seal on the PX-900 "}
event: text      data: {"delta": "should be replaced every 1,200 RF hours"}
event: citation  data: {"index": 1, "source": "corpus://acme-fab/px900-maintenance-manual",
                        "title": "PX-900 Maintenance Manual",
                        "cited_text": "The PX-900 plasma etcher requires chamber seal replacement every 1,200 RF hours."}
event: text      data: {"delta": "."}
event: done      data: {"conversation_id": "f3a1…", "input_tokens": 5123, "output_tokens": 411,
                        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 3050,
                        "cost_usd": 0.0241, "latency_ms": 2140}
```

- `done` carries `conversation_id` (the frontend needs it to continue the turn) and
  `cache_creation_input_tokens` (turn 1 shows cache creation, turn 2 shows reads).
- On failure the stream emits `event: error` with `{"message": …}` instead of `done`,
  and the turn is not persisted.
- **Anchors tasks:** T3.5 (producer), T3.6 (consumer). Treat this block as the
  contract; change it in this file first if it needs to change.

---

### 3. Test cases by build-plan task

Conventions: `test_<area>_<behavior>`. Unit tests mock the Anthropic and Voyage APIs;
integration tests (marked INT) hit real APIs behind `RUN_INTEGRATION=1`; e2e tests
(marked E2E) run against docker-compose with real APIs and are the UC scenarios above.

#### Phase 0

| ID | Task | Test | Assert |
|----|------|------|--------|
| TC-0.1 | T0.4 | `test_config_valid_loads` | both shipped YAMLs parse into the Pydantic model |
| TC-0.2 | T0.4 | `test_config_missing_field_names_it` | removing `agent.model` raises an error containing `agent.model` and the filename |
| TC-0.3 | T0.4 | `test_config_duplicate_client_id_rejected` | two files with same `client_id` fail startup |
| TC-0.4 | T0.4 | `test_config_unknown_tool_rejected` | `tools: [nonexistent_tool]` fails at load, not at request time |

#### Phase 2

| ID | Task | Test | Assert |
|----|------|------|--------|
| TC-2.1 | T2.1 | `test_embed_batches_and_retries` | 300 texts split into Voyage-sized batches; one mocked 429 retried |
| TC-2.2 | T2.3 | `test_chunker_respects_size_and_overlap` | all chunks ≤ chunk_size tokens; consecutive chunks share ~overlap tokens |
| TC-2.3 | T2.3 | `test_chunker_keeps_small_table_intact` | a 20-row Markdown table under the limit lands in one chunk |
| TC-2.4 | T2.5 | `test_ingest_idempotent` | second run: 0 added, all skipped; chunk count unchanged |
| TC-2.5 | T2.5 | `test_ingest_replaces_changed_doc` | editing one doc re-ingests only that doc's chunks |
| TC-2.6 | T2.6 | `test_search_client_isolation` (INT) | AF-1 query: hit #1 for acme-fab contains the AF-1 sentence; same query for meridian returns no hit containing it |
| TC-2.7 | T2.6 | `test_search_similarity_floor` (INT) | an off-domain query ("quantum computing CEO opinion") returns an empty list |

#### Phase 3

| ID | Task | Test | Assert |
|----|------|------|--------|
| TC-3.1 | T3.1 | `test_registry_resolves_client_tools` | acme gets `pricing_lookup`, meridian does not |
| TC-3.2 | T3.2 | `test_loop_appends_full_content` | mocked tool_use response: next request's messages contain the assistant content blocks verbatim |
| TC-3.3 | T3.2 | `test_loop_parallel_tool_calls_one_message` | mocked response with 2 tool_use blocks produces one user message with 2 tool_results, ids matching |
| TC-3.4 | T3.2 | `test_loop_iteration_cap` | a mock that always returns tool_use stops at the cap with a clean error |
| TC-3.5 | T3.3 | `test_search_result_block_shape` | executor output matches §4.3: type, source, title, content list, citations.enabled |
| TC-3.6 | T3.3 | `test_uc1_citation_end_to_end` (E2E) | UC-1 assertions |
| TC-3.7 | T3.4 | `test_uc3_pricing_tool` (E2E) | UC-3 assertions |
| TC-3.8 | T3.5 | `test_sse_event_contract` (E2E) | UC-10: event names, ordering (tool before first text, done last), citation fields present |
| TC-3.9 | T3.7 | `test_uc7_cache_hit_on_turn_two` (E2E) | UC-7 cache assertion |
| TC-3.10 | T3.2 | `test_uc4_refusal` (E2E) | UC-4: no citations, no fabricated facts (judge or keyword assertion) |
| TC-3.11 | T3.2 | `test_uc5_cross_client_refusal` (E2E) | UC-5 assertions |

#### Phase 4

| ID | Task | Test | Assert |
|----|------|------|--------|
| TC-4.1 | T4.1 | `test_cost_math` | given usage {input 5000, output 700, cache_read 3000, cache_write 3000}, cost = 5000*3 + 700*15 + 3000*0.3 + 3000*3.75 per MTok, to the cent |
| TC-4.2 | T4.1 | `test_uc3_trace_spans` (E2E) | UC-3 produces spans: model, search/pricing tools, model; latencies > 0 |
| TC-4.3 | T4.2 | `test_admin_aggregates` | seeded traces produce correct totals, p50/p95, cache hit rate |
| TC-4.4 | T4.4 | `test_rate_limit_429` | requests beyond the window limit get 429 with the JSON body |
| TC-4.5 | T4.4 | `test_budget_guard_and_reset` | UC-8 with a mocked clock |

#### Phase 5

| ID | Task | Test | Assert |
|----|------|------|--------|
| TC-5.1 | T5.1 | `test_golden_schema` | every JSONL row has question, golden_answer, source_document_id; ids exist in `documents` |
| TC-5.2 | T5.2 | `test_retrieval_eval_sentinels` (INT) | the 10 sentinel-derived golden questions all hit@5 |
| TC-5.3 | T5.3 | `test_judge_orders_answers` (INT) | UC-2 correct vs degraded answer: correct scores strictly higher on correctness and groundedness |
| TC-5.4 | T5.3 | `test_judge_output_parses` | mocked response validates against the §4.5 schema |
| TC-5.5 | T5.4 | `test_scorecard_renders` | eval run writes `eval_runs` row and emits the §5.4 Markdown table |

#### Phase 6

| ID | Task | Test | Assert |
|----|------|------|--------|
| TC-6.1 | T6.1 | smoke: UC-1 against the containerized stack | passes |
| TC-6.2 | T6.3 | `test_reset_preserves_corpus` | reset truncates conversations/messages/traces; documents/chunks/eval data intact |

---

### 4. Golden set seed entries

Format for `evals/<client>/golden.jsonl`. The sentinel-derived entries below are
mandatory; generate the rest with Claude and hand-review (T5.1). `refusal: true` rows
are judged on declining gracefully, not on content.

```jsonl
{"id": "af-g1", "question": "How often should the chamber seal on the PX-900 be replaced?", "golden_answer": "Every 1,200 RF hours.", "source_document_id": "px900-maintenance-manual", "refusal": false}
{"id": "af-g2", "question": "What does error code E-417 on the PX-900 mean and what should I do?", "golden_answer": "It indicates a helium backside cooling leak; the chamber must be vented immediately.", "source_document_id": "px900-troubleshooting-guide", "refusal": false}
{"id": "af-g3", "question": "What's the standby temperature for the LT-200 load lock?", "golden_answer": "45 degrees Celsius.", "source_document_id": "lt200-operations-manual", "refusal": false}
{"id": "af-g4", "question": "How quickly does a field engineer respond under a Tier 1 contract?", "golden_answer": "Within 4 business hours.", "source_document_id": "service-contracts-faq", "refusal": false}
{"id": "af-g5", "question": "Who is Acme's biggest competitor?", "golden_answer": "Not in the documentation; the assistant should say it doesn't know.", "source_document_id": null, "refusal": true}
{"id": "mi-g1", "question": "Is slow water seepage over several weeks covered?", "golden_answer": "No. Clause 4.2.1 excludes water damage from gradual seepage exceeding 14 days.", "source_document_id": "home-policy-wording", "refusal": false}
{"id": "mi-g2", "question": "What's the excess for accidental damage on HomeShield Plus?", "golden_answer": "$500.", "source_document_id": "home-policy-wording", "refusal": false}
{"id": "mi-g3", "question": "How long do I have to lodge a claim?", "golden_answer": "30 days from the insured event, unless exceptional circumstances apply.", "source_document_id": "claims-process-faq", "refusal": false}
{"id": "mi-g4", "question": "Do coastal properties need anything special before underwriting?", "golden_answer": "Properties within 100 metres of a coastline require a flood risk assessment.", "source_document_id": "underwriting-guidelines", "refusal": false}
{"id": "mi-g5", "question": "Should I invest in flood insurance stocks?", "golden_answer": "Out of scope; the assistant should decline.", "source_document_id": null, "refusal": true}
```

---

### 5. Judge fixtures (for TC-5.3 / TC-5.4)

One pinned pair so judge changes are regression-testable:

- **Question:** UC-2's question (E-417 + Tier 1 response time).
- **Correct answer:** covers helium leak, immediate vent, and 4 business hours, citing
  both documents.
- **Degraded answer:** "Error E-417 is a general system fault. A field engineer
  typically arrives within 1 to 2 business days." (wrong meaning, fabricated SLA, no
  citations)
- **Expected:** correct beats degraded on correctness and groundedness; degraded gets
  citation_accuracy ≤ 2; degraded verdict is "fail".

Store both answers in `evals/fixtures/judge_pair_uc2.json` so the comparison is stable
across judge prompt iterations.

---

## Part 2: Build Plan

### Phase 0: Foundations

#### T0.1: Repo scaffold + FastAPI skeleton

Reference: `CONFIGENT.md` §7 (repo structure).

- Create the monorepo layout from §7 (empty dirs with `.gitkeep` where needed).
- `apps/api`: FastAPI app with `uv` (or `pip-tools`) project setup, a `/healthz`
  endpoint returning `{"status": "ok"}`, and a `make dev` (or task runner) target.
- Add `ruff` + `pytest` config and one trivial passing test.
- `.env.example` with `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `DATABASE_URL`.

Verify: `pytest` passes; `curl localhost:8000/healthz` returns ok.

#### T0.2: Next.js scaffold (FE)

- `apps/web`: Next.js (App Router, TypeScript, Tailwind). One placeholder page.
- Dev rewrite/proxy so `/api/*` reaches the FastAPI app in development.

Verify: `npm run dev` serves the placeholder; a fetch to `/api/healthz` from the
browser returns ok.

#### T0.3: Local Postgres with pgvector

- `infra/docker-compose.yml`: `pgvector/pgvector:pg16` service, volume, healthcheck.
- A `db/init.sql` (or first migration) enabling `CREATE EXTENSION IF NOT EXISTS vector`.
- Async SQLAlchemy (or `asyncpg` + a thin layer) wired into FastAPI with a
  `/healthz/db` endpoint that runs `SELECT 1`.

Verify: `docker compose up -d` then `/healthz/db` returns ok.

#### T0.4: Client config schema + registry

Reference: `CONFIGENT.md` §3.

- Pydantic models mirroring the §3 YAML exactly (branding, corpus, agent, evals,
  limits). Validation errors must name the offending field and file.
- A `ConfigRegistry` that loads every `config/*.yaml` at startup and exposes
  `get(client_id)` and `all()`. Hot-reload in dev (file watcher or per-request reload
  behind a dev flag).
- `GET /api/clients` returning id, name, and branding for all clients.
- Unit tests: TC-0.1 through TC-0.4.

Verify: tests pass; a deliberately broken YAML makes startup fail with an error that
names the field.

---

### Phase 1: Clients exist

#### T1.1: Discovery briefs (writing task, not code)

- Write `briefs/acme-fab.md` and `briefs/meridian-insurance.md`: one page each with
  stakeholders, pain points, current process, success criteria, proposed scope.

Verify: both read like something you would hand a client VP.

#### T1.2: Generate the Acme corpus

- Use Claude to generate 10 to 15 Markdown docs for a semiconductor fab equipment
  vendor: equipment manuals (with tables), maintenance FAQs, spare parts catalog,
  troubleshooting guides. Realistic part numbers, cross-references between docs.
- The generation prompt must include the Acme sentinel facts (AF-1 to AF-5 from
  Part 1 §1) verbatim, placed in their assigned documents.
- ~~Convert 2 or 3 to PDF and keep both formats in `corpora/acme-fab/`.~~
  Deferred 2026-06-12: corpora stay markdown-only until the core agent loop is solid.
  See "Deferred enhancements" below.

Verify: docs are domain-plausible and reference each other; `grep` finds every AF
sentinel sentence verbatim in its assigned document.

#### T1.3: Generate the Meridian corpus

- Same for a general insurer: policy wording documents, claims FAQs, underwriting
  guidelines, coverage exclusion lists. Include the kind of nested clause numbering
  real policy docs have.
- Plant the Meridian sentinel facts (MI-1 to MI-5) verbatim per Part 1 §1. No Acme
  content may appear in this corpus.

Verify: same bar as T1.2, including the sentinel `grep` check.

#### T1.4: Client YAMLs + system prompts

Reference: `CONFIGENT.md` §3, §4.4 (the 2048-token cache minimum).

- `config/acme-fab.yaml` and `config/meridian-insurance.yaml`, complete per the schema.
- `prompts/acme-fab.md` and `prompts/meridian-insurance.md`: persona, domain context,
  grounding rules (answer only from retrieved sources, cite everything, say "I don't
  know" on empty retrieval), tone. Each must exceed 2048 tokens so the prefix caches.

Verify: registry loads both; a token count of each prompt exceeds 2048 (use the
`count_tokens` endpoint with `model: claude-sonnet-4-6`).

#### T1.5: Branded shell + client switcher (FE)

Reference: `CONFIGENT.md` §5.1.

- `GET /api/clients/{id}/branding` on the backend.
- `/c/[client_id]` route rendering logo, colors (CSS variables from
  `primary_color`), assistant name, and an empty chat layout.
- A switcher component (dropdown or landing grid) listing all clients.

Verify: flipping between the two client URLs visibly rebrands with no code change.

---

### Phase 2: Retrieval

#### T2.1: Embeddings wrapper

Reference: `CONFIGENT.md` §4.6.

- `apps/api/app/retrieval/embed.py`: `async def embed(texts: list[str]) ->
  list[list[float]]` calling Voyage AI. Batching (Voyage caps batch size), retry with
  backoff on 429/5xx, dimension constant exported.
- Unit test with the HTTP call mocked (TC-2.1); one optional integration test behind
  an env flag.

Verify: mocked test passes; integration test returns vectors of the expected dimension.

#### T2.2: Documents/chunks migrations

Reference: `CONFIGENT.md` §6.

- Migrations for `clients`, `documents`, `chunks` per §6, with
  `embedding vector(<dim>)`, an HNSW (or IVFFlat) index on `chunks.embedding`, and an
  index on `chunks.client_id`.

Verify: migration applies cleanly on a fresh database; rollback works.

#### T2.3: Chunker

- Token-aware chunker: target `chunk_size` tokens with `overlap`, splitting on
  paragraph then sentence boundaries before falling back to hard splits. Keep per-chunk
  metadata: document title, source path, position.
- Tests: TC-2.2, TC-2.3.

Verify: tests pass.

#### T2.4: Document parsing

- Loaders for `.md` (plain read), `.pdf` (pypdf or pdfplumber), `.html`
  (BeautifulSoup text extraction). Normalize to plain text + title.
- Test against 3 real files from `corpora/`.

Verify: each loader produces non-empty, sane text from a real corpus file.

#### T2.5: Ingest CLI

Reference: `CONFIGENT.md` §5.3.

- `configent ingest --client <id>` (Typer): walk the corpus dir, parse, hash
  content, skip unchanged docs, delete-and-replace changed docs, chunk, embed, upsert.
  Print a summary table (added / skipped / replaced, chunk counts).
- Tests: TC-2.4, TC-2.5.

Verify: first run ingests everything; second run reports all skipped; touching one doc
re-ingests only that doc.

#### T2.6: Vector search

- `async def search(client_id, query, k=5, floor=0.x) -> list[Hit]`: embed the query,
  cosine top-k over `chunks` filtered by `client_id`, drop hits under the similarity
  floor, return text + document metadata.
- Tests: TC-2.6, TC-2.7.

Verify: the cross-client isolation test passes.

---

### Phase 3: The agent

#### T3.1: Tool registry + shared tool definitions

Reference: `CONFIGENT.md` §5.2.

- A registry mapping tool name -> (definition dict, async executor). Client configs
  select tools by name; unknown names fail at config load.
- Definitions for `search_docs` (input: `query`, optional `k`) and `get_document`
  (input: `document_id`), each with 3-4 sentence descriptions stating when to use them.
- Executors: `search_docs` calls T2.6; `get_document` returns full document text.
- Test: TC-3.1.

Verify: unit test resolves each client's tool list from config; unknown tool name in a
YAML fails at startup.

#### T3.2: Agent loop, non-streaming

Reference: `CONFIGENT.md` §4.1, §4.2.

- `apps/api/app/agent/loop.py`: the manual loop from §4.2 with
  `client.messages.create` (streaming comes in T3.5). Model, max_tokens, effort, and
  system prompt from config. `thinking: {"type": "disabled"}`,
  `output_config: {"effort": cfg.agent.effort}`.
- Handle parallel tool calls (all results in one user message), typed exception
  handling, and a hard cap on loop iterations (e.g. 8) with a clean error.
- `POST /api/c/{client_id}/chat` (non-streaming JSON for now) creating/continuing a
  conversation, persisting messages.
- Tests: TC-3.2, TC-3.3, TC-3.4.

Verify: `curl` a corpus question to each client and get a correct answer that used
`search_docs` (assert `tool_use` appears in the stored message history).

#### T3.3: Citations via search_result blocks

Reference: `CONFIGENT.md` §4.3.

- Change the `search_docs` executor's result formatting to `search_result` blocks
  (source, title, content text block, `citations: {enabled: true}`) per §4.3.
- Map response content into a frontend-friendly shape: ordered segments of
  `{text, citations: [{source, title, cited_text}]}` and persist it on the message row.
- Tests: TC-3.5, TC-3.6.

Verify: the citation assertion test passes for both clients.

#### T3.4: Client-specific mock tools

- `tools/acme_fab/pricing_lookup.py`: takes part number + quantity, returns canned
  JSON (unit price, volume discount, lead time). `tools/meridian/coverage_check.py`:
  takes policy type + scenario, returns canned coverage verdict.
- Wire into the registry; enable via each client's YAML.
- Tests: TC-3.7.

Verify: Acme answers "quote 50 units of part X" by calling `pricing_lookup` (visible in
history); the same question to Meridian does not have the tool available.

#### T3.5: Streaming SSE

Reference: `CONFIGENT.md` §4.2, §4.3 (citations_delta).

- Swap the loop to `client.messages.stream(...)`. New SSE endpoint
  `POST /api/c/{client_id}/chat/stream` emitting events: `text` (delta), `citation`
  (from `citations_delta`), `tool` (name, when a tool call starts), `done` (usage
  summary).
- Keep persistence identical to T3.2 (use `get_final_message()` after the stream).
- Tests: TC-3.8. The UC-10 event contract in Part 1 §2 is the binding spec.

Verify: `curl -N` shows text deltas, at least one `citation` event, and a `done` event
for a corpus question.

#### T3.6: Chat UI with live citations (FE)

Reference: `CONFIGENT.md` §5.1.

- Wire the chat layout from T1.5 to the SSE endpoint: streaming text, a "Searching
  documents..." indicator on `tool` events, inline citation markers ([1], [2]) that
  expand to show `cited_text` + title on click.

Verify: in the browser, ask each client a corpus question; answer streams with working
citation popovers.

#### T3.7: Prompt caching

Reference: `CONFIGENT.md` §4.4.

- `cache_control: {"type": "ephemeral"}` on the last system block; deterministic tool
  ordering; a breakpoint on the latest turn's last content block for multi-turn reuse.
- Log `cache_read_input_tokens` / `cache_creation_input_tokens` per call.
- Tests: TC-3.9.

Verify: turn 1 of a conversation shows cache creation; turn 2 shows nonzero
`cache_read_input_tokens`.

---

### Phase 4: Observability

#### T4.1: Trace capture

Reference: `CONFIGENT.md` §5.5, §6.

- Migration for `conversations`, `messages` (if not already), `traces` per §6.
- Tracing wrapper around every model call and tool execution: span type, tool name,
  input/output (truncated), `tokens_in`, `tokens_out`, `cache_read_tokens`,
  `cost_usd` (computed per §4.7 rates: $3 input, $15 output, $0.30 cache read, $3.75
  cache write per MTok), `latency_ms`.
- Tests: TC-4.1, TC-4.2.

Verify: one chat turn produces spans whose summed cost matches a hand-computed number
from the usage fields.

#### T4.2: Admin API

- Basic-auth-protected endpoints: list conversations (filter by client), get one
  conversation with messages + spans, per-client aggregates (conversations, total
  cost, mean cost/turn, p50/p95 latency, cache hit rate).
- Tests: TC-4.3.

Verify: endpoints return correct numbers against seeded data in a test.

#### T4.3: Admin console (FE)

- `/admin`: client stats cards, conversation table, conversation detail with a span
  timeline (who called what, tokens, cost per span).

Verify: replay any conversation end to end in the browser and see its full cost.

#### T4.4: Budget guard + rate limiting

- Middleware: per-IP sliding-window rate limit (from config), per-client daily spend
  computed from `traces`, checked before each model call; both trip a 429 with a
  friendly JSON body. Daily reset by date boundary, not a cron.
- Tests: TC-4.4, TC-4.5.

Verify: tests simulate exceeding each limit and assert the 429 and the reset.

---

### Phase 5: Evals

#### T5.1: Golden sets

- Start from the mandatory seed entries in Part 1 §4, then generate the remaining
  candidate Q&A pairs with Claude from the corpus (question, golden answer, source
  document id, refusal flag). Hand-review and keep 25-40 per client in
  `evals/<client>/golden.jsonl`, including 3-5 refusal rows.
- A loader + schema validation for the JSONL.
- Tests: TC-5.1.

Verify: loader validates both files; all §4 seed entries present; spot-check 5
generated pairs per client by hand.

#### T5.2: Retrieval eval

- `configent eval --client <id> --retrieval-only`: for each golden question, run
  T2.6 search, score hit@k (golden source document in top k). Print per-client table.
- Tests: TC-5.2.

Verify: command prints hit@5 for both clients; numbers are plausible (>70%).

#### T5.3: LLM judge

Reference: `CONFIGENT.md` §4.5.

- Judge module calling `claude-sonnet-4-6` with the §4.5 structured-output schema.
  Input: question, golden answer, assistant answer, cited chunks. No citations on this
  call (structured outputs and citations are incompatible).
- Unit test with a mocked API response; one real-call test behind an env flag with an
  obviously-correct and obviously-wrong answer pair.
- Judge fixtures from Part 1 §5 anchor the regression test.
- Tests: TC-5.3, TC-5.4.

Verify: the wrong answer scores lower than the correct one on the real-call test.

#### T5.4: Full eval run + scorecard

- `configent eval --client <id>`: run every golden question through the real agent
  loop, collect judge scores plus p50/p95 latency and cost/query from the trace data,
  write a row to `eval_runs`, emit a Markdown scorecard.
- `--all` flag for both clients; paste the table into the README.
- Tests: TC-5.5.

Verify: the §5.4 target table renders with real numbers for both clients.

#### T5.5: Evals in CI

- GitHub Actions: lint + unit tests on every PR; eval suite on main (or nightly, to
  bound API spend) with a README badge showing the latest answer-quality score.

Verify: a PR that intentionally breaks retrieval shows the failure in CI.

---

### Phase 6: Ship

#### T6.1: Containerize

- Production Dockerfiles for `apps/api` (uvicorn, non-root) and `apps/web`
  (standalone Next.js build). Compose file runs the full stack locally in prod mode.
- Tests: TC-6.1.

Verify: full stack runs from containers locally; chat works end to end.

#### T6.2: Cloud Run deploy

- Provision: Artifact Registry, two Cloud Run services, Cloud SQL (or Neon)
  Postgres with pgvector, Secret Manager for API keys. Script or document every step
  in `infra/README.md`. Deploy and run ingestion against the prod database.

Verify: the public URL serves both clients with citations working.

#### T6.3: Demo hardening

- Cloud Scheduler job hitting an authenticated reset endpoint nightly (truncate
  conversations/messages/traces, keep corpus and eval data). Confirm rate limits and
  budget guard work on prod. Add a "this is a demo, data resets nightly" notice.
- Tests: TC-6.2.

Verify: trigger the reset manually; demo data clears, corpus survives.

#### T6.4: Switcher and UI polish (FE)

- Loading states, empty states, error toasts (including the friendly 429s), switcher
  transition, mobile pass.

Verify: you would happily open it in an interview.

---

### Phase 7: Packaging (human tasks)

These are yours to own, though Claude can draft copy.

- **T7.1**: 2-3 minute demo video told as a client story: brief, config file, live
  branded assistant, eval dashboard.
- **T7.2**: README: pitch line, architecture diagram, eval table, video link, all
  above the fold.
- **T7.3**: Blog post "Anatomy of a one-hour enterprise AI POC" + portfolio card
  (Problem / Built / Result with real numbers).
- **T7.4 (stretch)**: record the onboarding timer run: doc dump to working POC in
  under an hour, visible clock.

---

## Deferred enhancements

Decisions made during implementation that consciously trim or postpone scope.

- **E1: PDF corpus ingestion** (deferred from T1.2, decided 2026-06-12). Corpora are
  markdown-only until the core agent loop (Phase 3) is solid. When picked up: convert
  2-3 Acme docs to PDF and ingest the PDF *instead of* the `.md` (move the markdown
  originals to a `sources/` subfolder the ingester skips) — do not index both formats,
  that double-indexes the same text. This exercises `parse_pdf` against real files and
  restores the "it eats PDFs" demo line. Until then, `parse_pdf` is untested against
  real corpus files and the T2.4 PDF verify is waived.

---

## Dependency notes

- FE tasks (T0.2, T1.5, T3.6, T4.3, T6.4) only depend on their backend counterparts
  being done, not on the rest of the sequence.
- T3.7 (caching) can slot anywhere after T3.2.
- Phase 5 needs Phase 3 complete and Phase 4's trace data for the cost/latency columns.
- Nothing in Phases 0-5 requires GCP; everything runs on docker-compose until T6.2.
