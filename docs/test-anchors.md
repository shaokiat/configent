# Test anchors

End-to-end scenarios with expected observable behaviour. They serve four purposes at
once: acceptance criteria while implementing, the backbone of the e2e suite, the demo
script, and seeds for the golden sets.

Ground truth for every assertion below lives in [`evals/sentinels.yaml`](../evals/sentinels.yaml).

**Conventions.** Test names are `test_<area>_<behavior>`. Unit tests mock the Anthropic
and Voyage APIs. Integration tests (INT) hit real APIs behind `RUN_INTEGRATION=1`. E2E
tests run against docker-compose with real APIs and implement the use cases below.

---

## UC-1 to UC-7 — Retired with the loop engine (D11)

These seven scenarios ran against `acme-fab` and `meridian-insurance` on the free-form loop:
single-fact and multi-document answers, a client-specific tool call, out-of-corpus refusal,
cross-client isolation, a clause citation, and multi-turn caching. Both clients and the loop
were deleted on 2026-09-11. The scenarios as written:
`git show 841a1ba:docs/test-anchors.md`.

What they asserted still holds on the support graph, and is covered there:

- **Cited single-fact answer:** UC-10 below, and `test_a_documented_question_answers_at_level_one`.
- **Out-of-corpus refusal:** the graph never answers with zero passages; see UC-11.
- **Cross-client isolation:** `test_sentinels_do_not_leak_across_corpora`, the ownership tests.
- **Multi-turn follow-up:** UC-14's follow-up case, answered at Level 2. It shows no cache
  reads: nothing is prompt-cached on Haiku 4.5 (P5).

## UC-8 — Budget guard trips

- **Client:** any, with `daily_budget_usd` temporarily set to `0.01`.
- **Expected:** the second or third request returns 429 with the friendly JSON body;
  conversation history is not corrupted; a clock-mocked reset restores service.

## UC-9 — New client onboarding

- **Steps:** write `config/newco.yaml`, drop 5 docs in `corpora/newco/`, copy a prompt
  directory to `prompts/newco/`, run `configent --client newco`, open `/c/newco`.
- **Expected:** a branded assistant answering corpus questions with citations, zero code
  changes. Keep `newco` out of version control.

## UC-10 — Streaming event contract

`POST /api/c/gcp-platform-support/chat/stream` with "My Cloud Run container fails to start —
what does the PORT error mean?". **The frontend is built against exactly this.** Change this
block first if the contract needs to change.

```
event: run       data: {"run_id": "3f2b…", "conversation_id": "f3a1…"}
event: step      data: {"seq": 1, "stage": "retrieve", "level": 1, "n_hits": 5, "top_similarity": 0.62, …}
event: step      data: {"seq": 2, "stage": "grade", "level": 1, "confidence": 0.95, "kind": "question", …}
event: text      data: {"delta": "That error means the container never listened on the port "}
event: citation  data: {"index": 1, "source": "corpus://gcp-platform-support/cloud-run-troubleshooting",
                        "title": "Cloud Run troubleshooting",
                        "cited_text": "Container failed to start. Failed to start and then listen on the port defined by the PORT environment variable."}
event: text      data: {"delta": "Cloud Run expects."}
event: step      data: {"seq": 3, "stage": "answer", "level": 1, "n_citations": 1, …}
event: done      data: {"conversation_id": "f3a1…", "run_id": "3f2b…", "outcome": "answer",
                        "confidence": 0.95, "ticket_id": null, "input_tokens": 5123,
                        "output_tokens": 411, "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0, "cost_usd": 0.0072, "latency_ms": 2140}
```

- `done` carries `conversation_id` (the frontend needs it to continue the turn) and `outcome`.
  `cost_usd` is priced at the client model's row in `config/pricing/claude.yaml` (D8).
- On failure the stream emits `event: error` with `{"message": …}` instead of `done`,
  and the turn's messages are not persisted. The steps already committed stay on the run.
- **Amended 2026-09-11 for D11:** the contract previously opened with `tool` start/end
  events from the loop engine, and ran against `acme-fab`. Both are gone.

## UC-11 — Forced escalation (support agent) · planned, W1

- **Client:** `gcp-platform-support`
- **User:** a question the docs cannot answer (e.g. "Can you raise my Cloud Run
  instance quota for europe-west1?").
- **Expected:** `step` events for `retrieve`, `score`, `escalate`, `ticket`; the score
  step reports a confidence below the configured threshold; a ticket is POSTed to the
  mock ticket service exactly once; the final answer carries `escalated: true` and the
  ticket id. The answering model is never offered `create_escalation_ticket`.
- **Amended 2026-09-09 for D9 (W2-2a/b), and this is now the behaviour:** the escalate
  draft also returns `route: "ticket"`, and the ticket is POSTed only after the user confirms
  the proposal — so `escalate` → `ticket` in one turn becomes `escalate` → `ticket_proposal`
  event → `POST /runs/{run_id}/ticket` → `ticket`. Still exactly one ticket per run (D4), and
  a second confirmation returns the first ticket. `escalated: true` becomes
  `outcome: "ticket"`, and `ticket_id` is `null` on the `done` event of the proposing turn.
- **Amended 2026-09-11 for D10:** the steps before the proposal are `retrieve`, `grade`,
  `rewrite`, `hybrid_retrieve`, `regrade`, `escalate`, and `ticket` arrives after the
  confirmation. The graph pauses on `interrupt()` between the two; confirming resumes it.
  Verified live: `PLATFORM-1042`, idempotency key `{run_id}:7`, one ticket after two confirms.

## UC-12 — Crash and resume (support agent) · planned, W2

- **Client:** `gcp-platform-support`, run with `CRASH_AFTER=ticket_created`.
- **Expected:** the process exits after the ticket POST; the stream closes without
  `done`; `POST /runs/{run_id}/resume` replays from the checkpoint, skips retrieve,
  score and ticket, and emits the final response. The mock service records **one**
  ticket for that `run_id`.
- **Amended 2026-09-11 for D10:** still not built. LangGraph writes a checkpoint after every
  node and `CRASH_AFTER` now names a graph node (`retrieve`, `grade`, …). Resume would call
  `astream(None, thread)` behind the endpoint described above.

## UC-13 — Ticket service down (support agent) · planned, W3

- **Client:** `gcp-platform-support`, mock service with `FAIL_RATE=1.0`.
- **Expected:** 3 attempts with exponential backoff, visible as separate `step` events;
  the run ends with status `failed_ticket` and the last error recorded in `Run.steps`; the
  user still receives a response saying the question was recorded.

## UC-14 — A non-question does not file a ticket (support agent) · shipped, W2-2b

- **Client:** `gcp-platform-support`.
- **Users, one per case:** `hey` · `thanks` · `what can you do?` · a bare follow-up on the
  previous answer (`so is that the same as the health check timing out?`).
- **Expected:** each gets a short reply; the escalate draft returns `route: "converse"`;
  `outcome` is `converse`; **zero** POSTs reach the mock ticket service across all four.
  The follow-up case runs with prior turns in the conversation, since that is what makes it
  answerable at all.
- **Why it exists:** every one of these filed a ticket on the week-1 pipeline (D9). This is
  the regression test for the queue-precision criterion in
  [`briefs/gcp-platform-support.md`](../briefs/gcp-platform-support.md), and it is gate G2.6.
- **Adversarial companion:** a real technical question phrased casually (`quick one — whats
  the default cloud run cpu again`) must route to `answer`, never `converse`. `converse` is
  the only path that skips scoring, so a platform fact stated there is ungrounded by
  construction — the failure D2 exists to prevent, arriving through the new door.
- **Amended 2026-09-11 for D10:** triage is the `kind` field on the grade call. `hey`,
  `thanks` and `what can you do?` leave at Level 1 through a `converse` node, with one model
  call. The bare follow-up is now a *question*: it goes to Level 2, is rewritten with the
  conversation in view, and is answered (verified live, three citations). Still zero POSTs.

---

## Judge fixtures

> **Retired with UC-2 (D11).** The pair below judged an Acme answer; a replacement should pin
> a `gcp-platform-support` pair before the judge is built.

One pinned pair, so judge-prompt changes are regression-testable. Stored at
`evals/fixtures/judge_pair_uc2.json`.

- **Question:** UC-2's.
- **Correct answer:** covers helium leak, immediate vent, and 4 business hours, citing
  both documents.
- **Degraded answer:** "Error E-417 is a general system fault. A field engineer typically
  arrives within 1 to 2 business days." (wrong meaning, fabricated SLA, no citations)
- **Expected:** correct beats degraded on correctness and groundedness; degraded scores
  ≤ 2 on citation accuracy and gets a "fail" verdict.
