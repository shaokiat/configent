# POC Factory: Test Anchors and Example Use Cases

Companion to `POC_FACTORY_ARCHITECTURE.md` and `POC_FACTORY_BUILD_PLAN.md`. This doc
fixes the concrete examples that the implementation is built and tested against, so
every build-plan task has something deterministic to assert.

Read this before T1.2/T1.3 (corpus generation): the sentinel facts in section 1 must be
authored into the corpora verbatim, or none of the downstream tests have stable ground
truth.

---

## 1. Sentinel facts (plant these in the corpora verbatim)

Generated corpora are nondeterministic, so we pin a small set of facts that must appear
exactly as written. Tests retrieve, cite, and judge against these. Keep them in
`evals/sentinels.yaml` as the single source of truth; the corpus generation prompts in
T1.2/T1.3 must include them.

### Acme Fab Equipment

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

### Meridian Insurance

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

### Cross-client isolation sentinel

AF-1 must appear only in the Acme corpus and MI-1 only in the Meridian corpus. The
isolation tests depend on this; do not let corpus generation bleed domain content
across clients.

---

## 2. Anchor use cases

Each use case is an end-to-end scenario with expected observable behavior. They double
as: acceptance criteria during implementation, the backbone of the e2e test suite, the
script for the demo video, and seeds for the golden sets.

### UC-1: Single-fact answer with citation (the core loop)

- **Client:** acme-fab
- **User:** "How often does the chamber seal on the PX-900 need replacing?"
- **Expected:**
  - Exactly one `search_docs` tool call (input `query` mentions seal/PX-900).
  - Answer states 1,200 RF hours.
  - At least one `search_result_location` citation with `title` matching the PX-900
    maintenance manual and `cited_text` containing the AF-1 sentence.
- **Anchors tasks:** T3.2, T3.3, T3.6.

### UC-2: Multi-document synthesis

- **Client:** acme-fab
- **User:** "The PX-900 is showing error E-417. What does it mean and how fast can a
  field engineer get here on a Tier 1 contract?"
- **Expected:**
  - Answer covers both AF-2 (helium leak, chamber vent) and AF-4 (4 business hours).
  - Citations reference two distinct documents (`document_title` differs across the
    citations).
- **Anchors tasks:** T3.2, T3.3, T5.3 (good judge fixture: drop one half of the answer
  to make the "wrong" variant).

### UC-3: Agent chooses a client tool

- **Client:** acme-fab
- **User:** "Quote me 50 chamber seal kits for the PX-900."
- **Expected:**
  - The loop calls `search_docs` or the spare parts knowledge to resolve
    `PX900-SEAL-A2`, then calls `pricing_lookup` with that part number and qty 50.
  - Answer includes $1,840 unit price, the 8% volume discount (qty 50 > min 10), and
    the 21-day lead time.
  - Trace shows both tool spans in order.
- **Anchors tasks:** T3.4, T4.1.

### UC-4: Out-of-corpus refusal (grounding)

- **Client:** acme-fab
- **User:** "What's your CEO's opinion on quantum computing?"
- **Expected:**
  - Either no search hit above the similarity floor or unhelpful hits; the assistant
    says it does not have that information in its documentation, offers what it can
    help with, and invents nothing.
  - Zero citations in the answer.
- **Anchors tasks:** T2.6 (similarity floor), T3.2 (system prompt grounding rules),
  T5.1 (include 3-5 of these per client in the golden set, judged on refusal).

### UC-5: Cross-client isolation

- **Client:** meridian-insurance
- **User:** "How often does the chamber seal on the PX-900 need replacing?"
- **Expected:**
  - `search_docs` returns nothing relevant (AF-1 is not in Meridian's corpus).
  - Meridian's assistant refuses per UC-4 behavior; it must not answer with Acme data.
- **Anchors tasks:** T2.6 (the planted-chunk isolation test is the unit-level version
  of this), T3.2.

### UC-6: Policy exclusion with clause citation (Meridian flagship)

- **Client:** meridian-insurance
- **User:** "My ceiling has been leaking slowly for about a month. Am I covered?"
- **Expected:**
  - Answer says not covered, names gradual seepage and the 14-day threshold, and cites
    clause 4.2.1 (MI-1) via a `search_result_location` whose `cited_text` contains the
    clause sentence.
  - If `coverage_check` is called with `gradual_seepage`, its verdict must agree with
    the cited clause (this is the demo's "tool and corpus agree" moment).
- **Anchors tasks:** T3.3, T3.4.

### UC-7: Multi-turn follow-up with caching

- **Client:** meridian-insurance
- **Turn 1:** "What's the excess on accidental damage claims for HomeShield Plus?"
  (expects $500, cites MI-2)
- **Turn 2:** "And how long do I have to lodge a claim?" (expects 30 days, cites MI-3;
  the pronoun-free follow-up must still resolve in conversation context)
- **Expected:** turn 2's usage shows `cache_read_input_tokens > 0`.
- **Anchors tasks:** T3.7, T3.2 (multi-turn persistence).

### UC-8: Budget guard trips

- **Client:** any, with `daily_budget_usd` temporarily set to $0.01 in a test config.
- **Expected:** the second or third request returns HTTP 429 with the friendly JSON
  body, the conversation history is not corrupted, and the next calendar day (or a
  clock-mocked reset) restores service.
- **Anchors tasks:** T4.4.

### UC-9: New client onboarding (the timer story)

- **Steps:** write `config/newco.yaml`, drop 5 docs in `corpora/newco/`, run
  `poc-factory ingest --client newco`, open `/c/newco`.
- **Expected:** branded assistant answering corpus questions with citations, zero code
  changes, under an hour wall clock.
- **Anchors tasks:** the whole architecture; this is T7.4's script. Keep `newco`
  out of version control or delete after the run.

### UC-10: Streaming event contract

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
- **Anchors tasks:** T3.5 (producer), T3.6 (consumer). Treat this block as the contract;
  change it in this file first if it needs to change.

---

## 3. Test cases by build-plan task

Conventions: `test_<area>_<behavior>`. Unit tests mock the Anthropic and Voyage APIs;
integration tests (marked INT) hit real APIs behind `RUN_INTEGRATION=1`; e2e tests
(marked E2E) run against docker-compose with real APIs and are the UC scenarios above.

### Phase 0

| ID | Task | Test | Assert |
|----|------|------|--------|
| TC-0.1 | T0.4 | `test_config_valid_loads` | both shipped YAMLs parse into the Pydantic model |
| TC-0.2 | T0.4 | `test_config_missing_field_names_it` | removing `agent.model` raises an error containing `agent.model` and the filename |
| TC-0.3 | T0.4 | `test_config_duplicate_client_id_rejected` | two files with same `client_id` fail startup |
| TC-0.4 | T0.4 | `test_config_unknown_tool_rejected` | `tools: [nonexistent_tool]` fails at load, not at request time |

### Phase 2

| ID | Task | Test | Assert |
|----|------|------|--------|
| TC-2.1 | T2.1 | `test_embed_batches_and_retries` | 300 texts split into Voyage-sized batches; one mocked 429 retried |
| TC-2.2 | T2.3 | `test_chunker_respects_size_and_overlap` | all chunks ≤ chunk_size tokens; consecutive chunks share ~overlap tokens |
| TC-2.3 | T2.3 | `test_chunker_keeps_small_table_intact` | a 20-row Markdown table under the limit lands in one chunk |
| TC-2.4 | T2.5 | `test_ingest_idempotent` | second run: 0 added, all skipped; chunk count unchanged |
| TC-2.5 | T2.5 | `test_ingest_replaces_changed_doc` | editing one doc re-ingests only that doc's chunks |
| TC-2.6 | T2.6 | `test_search_client_isolation` (INT) | AF-1 query: hit #1 for acme-fab contains the AF-1 sentence; same query for meridian returns no hit containing it |
| TC-2.7 | T2.6 | `test_search_similarity_floor` (INT) | an off-domain query ("quantum computing CEO opinion") returns an empty list |

### Phase 3

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

### Phase 4

| ID | Task | Test | Assert |
|----|------|------|--------|
| TC-4.1 | T4.1 | `test_cost_math` | given usage {input 5000, output 700, cache_read 3000, cache_write 3000}, cost = 5000*3 + 700*15 + 3000*0.3 + 3000*3.75 per MTok, to the cent |
| TC-4.2 | T4.1 | `test_uc3_trace_spans` (E2E) | UC-3 produces spans: model, search/pricing tools, model; latencies > 0 |
| TC-4.3 | T4.2 | `test_admin_aggregates` | seeded traces produce correct totals, p50/p95, cache hit rate |
| TC-4.4 | T4.4 | `test_rate_limit_429` | requests beyond the window limit get 429 with the JSON body |
| TC-4.5 | T4.4 | `test_budget_guard_and_reset` | UC-8 with a mocked clock |

### Phase 5

| ID | Task | Test | Assert |
|----|------|------|--------|
| TC-5.1 | T5.1 | `test_golden_schema` | every JSONL row has question, golden_answer, source_document_id; ids exist in `documents` |
| TC-5.2 | T5.2 | `test_retrieval_eval_sentinels` (INT) | the 10 sentinel-derived golden questions all hit@5 |
| TC-5.3 | T5.3 | `test_judge_orders_answers` (INT) | UC-2 correct vs degraded answer: correct scores strictly higher on correctness and groundedness |
| TC-5.4 | T5.3 | `test_judge_output_parses` | mocked response validates against the §4.5 schema |
| TC-5.5 | T5.4 | `test_scorecard_renders` | eval run writes `eval_runs` row and emits the §5.4 Markdown table |

### Phase 6

| ID | Task | Test | Assert |
|----|------|------|--------|
| TC-6.1 | T6.1 | smoke: UC-1 against the containerized stack | passes |
| TC-6.2 | T6.3 | `test_reset_preserves_corpus` | reset truncates conversations/messages/traces; documents/chunks/eval data intact |

---

## 4. Golden set seed entries

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

## 5. Judge fixtures (for TC-5.3 / TC-5.4)

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
