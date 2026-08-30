# Support Agent: four-week implementation plan

**Status:** approved, not started · **Drafted:** 2026-08-30

The primary reference during implementation. Decisions referenced as `D1`–`D8` and
`P1`–`P11` live in [`docs/decisions.md`](decisions.md); scenario assertions live in
[`docs/test-anchors.md`](test-anchors.md). The Week 1 stage machine is drawn in
[`docs/support-agent-pipeline.html`](support-agent-pipeline.html) — open it in a browser
for the flow diagram, the tool round trip that disappears, and the foreign-key trap.

---

## What is being built

A deployment and infrastructure support agent — client `gcp-platform-support`,
assistant **DeployBot** — that answers Cloud Run, GKE and IAM questions from public Google
Cloud documentation with citations, and escalates to a structured ticket when the question
needs a human: account-specific configuration, quota or billing, a suspected incident, an
access request, or anything the docs don't cover.

The knowledge base is a curated snapshot of public Google Cloud documentation
(CC BY 4.0, attributed per file) in `corpora/gcp-platform-support/`. It contains nothing
about any user's own project — which is exactly what makes the escalation branch load-bearing
rather than decorative: "what does the platform do?" is answerable, "what is *my* project
doing?" structurally is not.

```
question → retrieve → score confidence → ┬→ answer with citations
                                          └→ [forced] escalate → file ticket
```

with a durable audit trail, checkpoint/resume, and retries that end in a recorded
failure rather than a silent one.

**Scope discipline.** Single-tenant, single-loop. Multi-tenancy is one line if asked
("the underlying platform is config-driven for multi-tenant deployment") and nothing
more. Acme, Meridian and `configent-support` stay in the repo on the free-form loop (D5), dormant, out of
the demo and out of the eval matrix.

## How to run this plan

1. **One task per session.** Each `W<n>-<m>` is sized to finish and verify in one go.
2. **One task, one commit,** message prefixed with the task ID.
3. **Tasks are ordered within a week** unless marked *(parallel)*.
4. **Do not start a week until the previous week's exit gate passes.** The gates are
   the point of the plan — an unverified week compounds into an undemoable week 4.

---

## Objectives at a glance

| Week | Objective (one sentence) | Exit gate |
|---|---|---|
| 1 | The escalate/answer decision is made by code, not by the model, and every stage is visible. | A question below threshold escalates and files a ticket over real HTTP, with four `step` events rendered in the UI. |
| 2 | A run survives the process dying. | `make crash-demo` kills the process after ticket creation; resume completes the run and the ticket service holds exactly one ticket. |
| 3 | The system's behaviour is measured, not asserted. | Two eval runs on a 25–30 case golden set produce decision accuracy, citation accuracy and $/query from logged tokens. |
| 4 | The work is defensible in two registers. | A cold walkthrough of the engineer story and the VP story, both backed by numbers from week 3. |

---

# Week 1 — Pipeline, guardrail, real tool call, audit trail

### Objective

Turn the free-form agent loop into an explicit pipeline for this one client, so that the
escalation decision is a branch in Python (D2) rather than a model's choice — and make
every stage of that pipeline observable as it happens.

### Two API facts the design rests on

Both verified against the Messages API docs on 2026-08-30; both would be expensive to
discover mid-build.

1. **`search_result` blocks are valid as top-level user content**, not only inside a
   `tool_result` — *"As top-level content: you provide search results directly in user
   messages for pre-fetched or cached content."* This is what lets retrieval be a plain
   function call while citations keep working exactly as they do today.
2. **Citations and `output_config.format` cannot be combined** (400). That splits cleanly
   along stage lines — `score` and `escalate` take structured output, `answer` takes
   citations — but it means `SupportAnswer` **cannot be a model output**. Python assembles
   and validates it from the stage results. That is the stronger claim anyway: the response
   contract is constructed, not generated and hoped for.

Structured outputs are supported on Haiku 4.5, so the cheap scoring model works as planned.

### Exit gate — all four must pass

- [ ] **G1.1** An answerable question produces four `step` SSE events (`retrieve`,
      `score`, `answer`, `done`) followed by a cited answer.
- [ ] **G1.2** An unanswerable question produces `retrieve`, `score`, `escalate`,
      `ticket` steps; the score step shows the confidence value and the threshold it
      failed; a ticket exists in the mock service, created by an HTTP POST.
- [ ] **G1.3** The answering model's request payload contains no `create_escalation_ticket`
      tool definition. Asserted in a test, not by inspection.
- [ ] **G1.4** Killing the API mid-run leaves the completed steps in the `Run` row
      (proves D3 — this is the week-2 foundation and is cheap to check now).

### Tasks

| ID | Component | Change | Why |
|---|---|---|---|
| **W1-1** | `app/config/schema.py`, `config/gcp-platform-support.yaml` | `AgentConfig.mode: "loop"\|"pipeline"` (default `loop`), `confidence_threshold`, `escalate_below`. Also rename `search()`'s existing `floor` to `retrieval_drop_floor` and surface it in config | D5, D2. **Two different floors:** `retrieval_drop_floor` (today's `0.3`) *discards* weak chunks; `escalate_below` *escalates* on the ones that survive. If `escalate_below` ≤ `retrieval_drop_floor` it can never fire — `hits[0]` is ≥ the drop floor by construction, or `hits` is empty. Validate that relationship at config load. |
| **W1-2** | `app/models.py`, `alembic/versions/0003_*.py` | New `Run`: `id`, `conversation_id`, `client_id`, `status`, `current_stage`, `steps` (JSON list of `{seq, stage, status, reasoning, confidence?, tokens, cost_usd, latency_ms, started_at, finished_at}`), timestamps | One table, one migration. `Trace` stays span-level (one row per API call); `Run.steps` is the stage-level audit trail the UI renders and resume replays from. **Also commit the conversation row before the pipeline starts** — `_prepare_conversation` currently flushes without committing, so a `Run` written on an independent session (D3) has no visible FK parent and the insert fails. |
| **W1-3** | `app/database.py` | `checkpoint_session()` — independent short-lived `AsyncSession`, commits immediately | **D3. Do this before W1-4.** Everything else in weeks 1–2 depends on it and retrofitting it is painful. |
| **W1-4** | `app/agent/pipeline.py` *(new)* | Stage functions `retrieve` / `score` / `answer` / `escalate` / `ticket` + `run_pipeline()` and `stream_pipeline()`; imports shared primitives from `loop.py`. Answer stage passes `search_result` blocks as **top-level user content**, not through a tool. Zero hits short-circuits straight to escalate without a score call. When history exists, embed the previous user message alongside the current one so pronoun-free follow-ups still retrieve | The core restructure. `loop.py` is untouched and keeps serving the other clients. Empty retrieval has nothing to score, so scoring it wastes a call and invents a number. |
| **W1-5** | `prompts/gcp-platform-support/{answer,score,ticket_draft}.md` | Split the single prompt into three | Each stage has one job. A mega-prompt makes the scoring step unauditable — and scoring is the guardrail. |
| **W1-6** | `apps/mockticket/` *(new)*, `infra/docker-compose.yml` | ~80-line FastAPI service: `POST /tickets` honouring `Idempotency-Key`, `GET /tickets/{id}`, `GET /tickets`; env `FAIL_RATE` and `LATENCY_MS` | "Real schema, real HTTP" as scoped. The chaos switches are what make weeks 2–3 demoable on command instead of hoping something breaks. |
| **W1-7** | `app/agent/pipeline.py` | Pass `run_id` into the ticket executor at the pipeline's single call site | D4. **Smaller than originally scoped:** the pipeline makes no model-driven tool calls — Python invokes the executor directly — so `_execute_tool` and the Acme/Meridian tools need no signature change. |
| **W1-8** | `tools/gcp_platform/create_escalation_ticket.py` | Replace the pure-function mock with an `httpx` POST; server assigns the ticket id; `crc32` demoted to a test fixture seed | D4. A content-derived id is not idempotency. |
| **W1-9** | `.env.example`, `apps/api/Dockerfile`, `Makefile` | `TICKET_API_URL`; `make dev` starts `mockticket` | One command still stands the whole stack up. |
| **W1-10** | `app/agent/pipeline.py` | Emit `step` SSE event per stage: `{stage, status, seq, ts, reasoning, confidence?, cost_usd}` | The renderable deliverable — the thing an interviewer actually wants to see. |
| **W1-11** *(parallel)* | `apps/web/.../ChatPanel.tsx`, `types.ts` | `handleEvent` case for `step`; a step-timeline component | `handleEvent` silently drops unknown event types today, so the backend work is invisible until this lands. |
| **W1-12** | `app/routers/clients.py` | Dispatch on `cfg.agent.mode` | One entry point, two engines. |
| **W1-13** | `tests/test_pipeline.py` *(new)*, `test_tools.py`, `test_e2e_tools.py` | Pipeline branch tests incl. G1.3; rewrite ticket tests against `respx` | Existing tests assert on the old pure function and **will fail** — budget for the rewrite. |

### Build order

Not the table order. `checkpoint_session()` and the `Run` row come first because
everything downstream commits through them, and the mock ticket service comes early
because the escalate branch cannot be tested end to end without it — and it is eighty
lines you can write while the pipeline design is still settling.

`W1-3` → `W1-2` → `W1-1` → `W1-6` → `W1-4` → `W1-8` → `W1-10` → `W1-12` → `W1-11` → `W1-13`

`W1-5` (the three prompts) slots in beside `W1-4`; `W1-9` (env and compose wiring) beside
`W1-6`.

### Risks

- **W1-4 is the largest single task in the plan.** If it overruns, cut the follow-up query
  concatenation and accept single-turn retrieval for the demo — not the scoring stage.
- **The pipeline client's `agent.tools` becomes documentation.** Retrieval is deterministic
  and the ticket call is made from Python, so no tool definition is ever sent for this
  client. Leave `search_docs` / `get_document` in the YAML until `mode: pipeline` actually
  ships — the client runs on `loop` today and needs them — then drop them in `W1-12`.
- Threading `run_id` (W1-7) touches Acme/Meridian tools. Keep the parameter optional in
  their signatures so `loop.py` behaviour is unchanged.

---

# Week 2 — Structured outputs, validation, checkpoint and resume

### Objective

Make every inter-stage hand-off a validated schema, and make a run a durable, resumable
object — so that a process death after a side effect (the filed ticket) costs the
remaining stages, not the whole run, and never files twice.

### Exit gate

- [ ] **G2.1** Every stage output validates against a Pydantic model before the next
      stage runs; a deliberately corrupted model response triggers exactly one re-ask,
      then routes to escalate.
- [ ] **G2.2** `make crash-demo` kills the process after ticket creation. The UI shows
      "interrupted — Resume".
- [ ] **G2.3** Resume completes the run without re-running retrieve, score, or the
      ticket POST — provable from `Run.steps` and the mock service log.
- [ ] **G2.4** `GET /tickets` on the mock service shows **one** ticket for that
      `run_id`. This is the claim; prove it in a test, not just a demo.
- [ ] **G2.5** A resume attempt with a mismatched `client_id` returns 404, mirroring conversation ownership.

### Tasks

| ID | Component | Change | Why |
|---|---|---|---|
| **W2-1** | `app/agent/schemas.py` *(new)* | `RetrievalResult`, `GroundednessScore`, `TicketDraft`, `TicketResult`, `SupportAnswer{answer, citations[], confidence, escalated, ticket_id?}`. `GroundednessScore` and `TicketDraft` are model outputs via `output_config.format`; `SupportAnswer` is **assembled in Python** and validated there | The final response is a schema, not free text — and because citations rule out structured output on the answer call, it has to be constructed rather than generated. |
| **W2-2** | `app/agent/pipeline.py` | `validate_or_fail()` between every stage; a `ValidationError` routes straight to escalate | Fail-closed. "What if the model returns garbage" has a one-sentence answer: it doesn't get to proceed, and the escalate path already exists. |
| **W2-3** | `app/agent/checkpoint.py` *(new)* | `save(run_id, stage, state)` / `load(run_id)` on `checkpoint_session()` | D3. The one place the old transaction model actively fights the feature. |
| **W2-4** | `app/routers/clients.py` | `POST /c/{id}/chat` accepts optional `run_id`; new `POST /c/{id}/runs/{run_id}/resume` (SSE) and `GET /c/{id}/runs/{run_id}`; both `client_id`-scoped | There is no resume entry point today — chat only starts turns. Scoping mirrors the existing conversation-ownership check. |
| **W2-5** | `tools/gcp_platform/create_escalation_ticket.py` | Idempotency-Key `{run_id}:{seq}`; short-circuit on the run's stored `ticket_id` | D4 — belt and braces, because the failure is a duplicate ticket in a customer's queue. |
| **W2-6** | `app/agent/pipeline.py` | Honour `CRASH_AFTER=<stage>` fault injection | D6. Deterministic beats dramatic. |
| **W2-7** | `Makefile` | `make crash-demo` | Repeatable in an interview, on a laptop, at 4pm. |
| **W2-8** *(parallel)* | `apps/web/.../ChatPanel.tsx` | Persist `run_id`; on stream close without `done`, show "interrupted — Resume" | D3. Otherwise the kill/resume demo is a terminal screenshot, not a demo. |
| **W2-9** | `tests/test_resume.py` *(new)* | Crash after ticket creation → resume → assert one POST reached the service; assert stage skipping; assert G2.5 | G2.3 and G2.4 are the week's entire value. |

### Risks

- Partial state is real (D3): committed steps, uncommitted conversation turn. Resume
  must read `Run.steps`, never `Message`. Get this wrong and resume silently duplicates
  the user's turn.
- W2-9 depends on W2-5's response shape. Agree the `run_id` field name first.

---

# Week 3 — Retries, golden set, evals, cost

### Objective

Replace claims with measurements: prove what fraction of a held-out golden set the agent
routes correctly, what a query costs from real logged tokens, and what happens when the
ticket API is down.

### Exit gate

- [ ] **G3.1** With `FAIL_RATE=1.0`, a run makes 3 attempts with visible backoff, ends in
      `failed_ticket`, logs the last error, and the user still receives a `SupportAnswer`
      telling them the question was recorded.
- [ ] **G3.2** The golden set has 25–30 cases and was committed **before**
      `run_evals.py` existed. Verifiable from `git log`.
- [ ] **G3.3** `configent eval` produces decision accuracy, citation accuracy,
      escalation precision/recall, and cost/latency per case.
- [ ] **G3.4** Two model profiles are scored side by side, and the reported $ figures
      come from `Trace.cost_usd`, not from an estimate.

### Tasks

| ID | Component | Change | Why |
|---|---|---|---|
| **W3-1** | `app/agent/loop.py` | **Replace `_PRICE_*` constants with a per-model price table; price each call by its own model** | D8. Every cost number in the repo is currently wrong (Sonnet rates on Haiku calls). **Do this first** — it invalidates everything measured before it. |
| **W3-2** | `app/tools/http.py` *(new)* | `post_with_retry()` — 1s/2s/4s backoff, max 3, retry only on 5xx/timeout/connect | Retrying a 422 is a bug, not resilience. |
| **W3-3** | `app/agent/loop.py` | Tool timeout becomes per-attempt; add a separate total budget | Today's single 30s `asyncio.wait_for` can't contain 3 attempts plus 1+2+4s backoff — it kills the retry chain and reports a timeout, masking the failure you're demonstrating. |
| **W3-4** | `app/models.py` | Add `failed_ticket` to `Run.status`; record `last_error` and `attempts` in `Run.steps` | An explicit terminal state, no new table. Silent failure is what's being engineered away — a queue nobody drains is not what fixes that. |
| **W3-5** | `app/agent/pipeline.py` | On exhausted retries: set `failed_ticket`, emit `step{stage:"ticket", status:"failed"}` with the error, log it, and still return a `SupportAnswer` telling the user their question was recorded | "What happens if the ticket API is down" is the VP-level question. Have a user-facing answer. |
| **W3-6** | `app/config/schema.py`, `config/gcp-platform-support.yaml` | `AgentConfig.models: {router, answer}`; single `model` back-fills both | Week 3's swap needs two models per client; today it's one field. |
| **W3-7** | `evals/gcp-platform-support/golden.jsonl` | Grow 10 → 25–30. Add `expected_outcome: answer\|escalate`, `expected_citations: [doc_id]`, `expected_ticket_category`, `rationale`. ~15 answerable, ~10 escalate, ~3 adversarial (plausible but out of corpus) | The seed set already uses this schema (10 rows, 6 answer / 4 escalate). The adversarial cases — questions that sit next to answerable ones in the corpus but whose specific number is absent — are what separate this from a happy-path demo. |
| **W3-8** | — | **Commit W3-7 whole, in one commit, before W3-9 is written** | D7. Commit order is the evidence. |
| **W3-9** | `evals/runner/run_evals.py` *(new)*, `app/cli.py` | `configent eval --client --model-profile`; scores the metrics in G3.3 | `evals/runner/` is an empty `.gitkeep` and `cli.py`'s docstring already claims eval commands that don't exist. |
| **W3-10** | `app/models.py` | `EvalRun.model_profile` column | Compare runs by profile. |
| **W3-11** | `app/agent/pipeline.py` | Per-stage cost attribution into each `Run.steps` entry; `done` carries the per-stage breakdown | "Cost per query broken out by step" needs attribution at write time; it can't be reconstructed later. |
| **W3-12** | `evals/reports/` *(new)* | Committed JSON + Markdown report per profile | The artifact you actually show. |

### Risks

- W3-1 before anything else. Measuring with the wrong price table wastes the week.
- The cheap-router swap may *lose* accuracy. That is a valid, reportable result — the
  comparison is the artifact (D2), not the swap. Don't tune until it wins.

---

# Week 4 — Package and defend

### Objective

Make the work legible to two different audiences from a cold start, with every number
traceable to something in the repo.

### Exit gate

- [ ] **G4.1** A cold 10-minute walkthrough of the engineer story: SSE over polling,
      stage-boundary checkpointing, hard branch over soft signal, what broke on the kill.
- [ ] **G4.2** A 3-minute VP story: pain, outcome with three real numbers, risk.
- [ ] **G4.3** Every number in G4.2 traces to `evals/reports/` or the `traces` table.
- [ ] **G4.4** The demo can show the failure path (ticket API down) on command.

### Tasks

| ID | Component | Change | Why |
|---|---|---|---|
| **W4-1** | `docs/architecture.md` | Add the pipeline and durability sections | Public architecture doc is still loop-shaped. |
| **W4-2** | `apps/docs/.../agent-loop.mdx` | Split: free-form loop vs. fixed pipeline, and when each applies | The choice between them *is* the engineering story (D5). |
| **W4-3** | `apps/docs/.../reliability.mdx` *(new)* | Checkpoint/resume, idempotency, retries and the recorded-failure path | The week-2 and week-3 work has no public home otherwise. |
| **W4-4** | `apps/web` demo | Step timeline on by default; three seeded questions — answers, escalates, ticket-API-down | A demo that only shows the happy path invites the question you least want. |
| **W4-5** | `README.md` | One-line multi-tenant mention; lead with the support workflow; state the ticket API is a mock | Framing drop, and the honesty note from D7. |
| **W4-6** | `private/INTERVIEW.md` | New Story Bank entry, separate from Configent-1 | Don't fold these numbers into the old story — that one still lacks its own hard number. |

### Framing

**Engineer.** SSE over polling: the stream already exists, so ordered step events are
free and the audit trail is the same surface the user watches. Checkpoint at stage
boundaries, not token boundaries: a stage is the smallest unit with a validated,
replayable output — a half-generated token stream isn't state. Confidence as a hard
branch: a soft signal is a suggestion the model can talk itself out of (D2). What broke
on the kill: the request-scoped session died with the process, taking uncommitted
checkpoints with it — which is why durability writes commit independently (D3).

**VP.** Pain: unanswered and misrouted questions consume support time and land on the
wrong desk. Outcome: X% of a 25–30 case held-out set routed correctly, $Y per query,
Z% cheaper with the cheap-router swap at equal accuracy. Risk: if the ticket API is
down, three retries, then a recorded failure the user is told about — never a silent drop.

---

## Cut list, in order

If a week overruns, cut from the top:

1. Query expansion inside `retrieve` (W1-4).
2. The step-timeline UI polish — the events still land in `Run.steps` (W1-11).
3. The third model profile, if you were tempted to add one.

**Never cut:** the golden set (W3-7), the resume test (W2-9), or the per-model price
table (W3-1). Those three are the difference between a demo and an artifact.
