# Test anchors

End-to-end scenarios with expected observable behaviour. They serve four purposes at
once: acceptance criteria while implementing, the backbone of the e2e suite, the demo
script, and seeds for the golden sets.

Ground truth for every assertion below lives in [`evals/sentinels.yaml`](../evals/sentinels.yaml).

**Conventions.** Test names are `test_<area>_<behavior>`. Unit tests mock the Anthropic
and Voyage APIs. Integration tests (INT) hit real APIs behind `RUN_INTEGRATION=1`. E2E
tests run against docker-compose with real APIs and implement the use cases below.

---

## UC-1 — Single-fact answer with citation (the core loop)

- **Client:** `acme-fab`
- **User:** "How often does the chamber seal on the PX-900 need replacing?"
- **Expected:** exactly one `search_docs` call (query mentions seal/PX-900); answer
  states 1,200 RF hours; at least one `search_result_location` citation whose `title`
  matches the PX-900 maintenance manual and whose `cited_text` contains AF-1.

## UC-2 — Multi-document synthesis

- **Client:** `acme-fab`
- **User:** "The PX-900 is showing error E-417. What does it mean and how fast can a
  field engineer get here on a Tier 1 contract?"
- **Expected:** answer covers both AF-2 (helium leak, chamber vent) and AF-4 (4 business
  hours); citations reference two distinct documents.

## UC-3 — Agent chooses a client-specific tool

- **Client:** `acme-fab`
- **User:** "Quote me 50 chamber seal kits for the PX-900."
- **Expected:** the loop resolves `PX900-SEAL-A2`, then calls `pricing_lookup` with that
  part number and qty 50; the answer includes the $1,840 unit price, the 8% volume
  discount (50 > min 10) and the 21-day lead time; the trace shows both tool spans in
  order.

## UC-4 — Out-of-corpus refusal (grounding)

- **Client:** `acme-fab`
- **User:** "What's your CEO's opinion on quantum computing?"
- **Expected:** no hit above the similarity floor; the assistant says it doesn't have
  that in its documentation, offers what it can help with, and invents nothing. Zero
  citations in the answer.

## UC-5 — Cross-client isolation

- **Client:** `meridian-insurance`
- **User:** UC-1's question.
- **Expected:** `search_docs` returns nothing relevant (AF-1 is not in Meridian's
  corpus); Meridian's assistant refuses per UC-4 and must not answer with Acme data.

## UC-6 — Policy exclusion with clause citation

- **Client:** `meridian-insurance`
- **User:** "My ceiling has been leaking slowly for about a month. Am I covered?"
- **Expected:** not covered; names gradual seepage and the 14-day threshold; cites
  clause 4.2.1 (MI-1) through a `search_result_location`. If `coverage_check` is called
  with `gradual_seepage`, its verdict must agree with the cited clause.

## UC-7 — Multi-turn follow-up with caching

- **Client:** `meridian-insurance`
- **Turn 1:** "What's the excess on accidental damage claims for HomeShield Plus?"
  ($500, cites MI-2). **Turn 2:** "And how long do I have to lodge a claim?" (30 days,
  cites MI-3 — the pronoun-free follow-up must resolve in conversation context).
- **Expected:** turn 2's usage shows `cache_read_input_tokens > 0`.

## UC-8 — Budget guard trips

- **Client:** any, with `daily_budget_usd` temporarily set to `0.01`.
- **Expected:** the second or third request returns 429 with the friendly JSON body;
  conversation history is not corrupted; a clock-mocked reset restores service.

## UC-9 — New client onboarding

- **Steps:** write `config/newco.yaml`, drop 5 docs in `corpora/newco/`, run
  `configent ingest --client newco`, open `/c/newco`.
- **Expected:** a branded assistant answering corpus questions with citations, zero code
  changes. Keep `newco` out of version control.

## UC-10 — Streaming event contract

`POST /api/c/acme-fab/chat/stream` with UC-1's question. **The frontend is built against
exactly this.** Change this block first if the contract needs to change.

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
  `cache_creation_input_tokens` (turn 1 shows creation, turn 2 shows reads).
- On failure the stream emits `event: error` with `{"message": …}` instead of `done`,
  and the turn is not persisted.

## UC-11 — Forced escalation (support agent) · planned, W1

- **Client:** `gcp-platform-support`
- **User:** a question the docs cannot answer (e.g. "Can you raise my Cloud Run
  instance quota for europe-west1?").
- **Expected:** `step` events for `retrieve`, `score`, `escalate`, `ticket`; the score
  step reports a confidence below the configured threshold; a ticket is POSTed to the
  mock ticket service exactly once; the final answer carries `escalated: true` and the
  ticket id. The answering model is never offered `create_escalation_ticket`.

## UC-12 — Crash and resume (support agent) · planned, W2

- **Client:** `gcp-platform-support`, run with `CRASH_AFTER=ticket_created`.
- **Expected:** the process exits after the ticket POST; the stream closes without
  `done`; `POST /runs/{run_id}/resume` replays from the checkpoint, skips retrieve,
  score and ticket, and emits the final response. The mock service records **one**
  ticket for that `run_id`.

## UC-13 — Ticket service down (support agent) · planned, W3

- **Client:** `gcp-platform-support`, mock service with `FAIL_RATE=1.0`.
- **Expected:** 3 attempts with exponential backoff, visible as separate `step` events;
  the run ends with status `failed_ticket` and the last error recorded in `Run.steps`; the
  user still receives a response saying the question was recorded.

---

## Judge fixtures

One pinned pair, so judge-prompt changes are regression-testable. Stored at
`evals/fixtures/judge_pair_uc2.json`.

- **Question:** UC-2's.
- **Correct answer:** covers helium leak, immediate vent, and 4 business hours, citing
  both documents.
- **Degraded answer:** "Error E-417 is a general system fault. A field engineer typically
  arrives within 1 to 2 business days." (wrong meaning, fabricated SLA, no citations)
- **Expected:** correct beats degraded on correctness and groundedness; degraded scores
  ≤ 2 on citation accuracy and gets a "fail" verdict.
