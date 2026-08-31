# Support Agent: four-week implementation plan

**Status:** week 1 complete (gates G1.1–G1.4 verified 2026-08-30) · **Drafted:** 2026-08-30 ·
**Resequenced 2026-08-31:** measurement moved ahead of durability — see *Why this order changed*.

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
| 2 | The system's behaviour is measured, not asserted. | Two model profiles scored on a 25–30 case golden set produce decision accuracy, citation accuracy and $/query from logged tokens. |
| 3 | A failure is recorded and recoverable, never silent. | With the ticket API down the user still gets an answer and the failure is on the run; `make crash-demo` plus resume leaves exactly one ticket. |
| 4 | The work is defensible in two registers. | A cold walkthrough of the engineer story and the VP story, both backed by numbers from week 2. |

### Why this order changed

Weeks 2 and 3 are swapped from the 2026-08-30 draft, which put durability first. Three
reasons, worth being able to say out loud:

1. **Durability is already demonstrated.** G1.4 proved the claim that matters — a crash
   leaves completed stages in the `Run` row, because durability writes commit on their own
   session (D3). Resume replays from that row; it is mechanical, and it renders in a demo
   as one button click.
2. **The measurement is the artifact.** Decision accuracy and $/query on a held-out set are
   the only outputs here that cannot be reproduced from a slide. They are also what gets
   asked first.
3. **Every number measured before W2-1 is wrong.** The price constants are Sonnet rates
   applied to Haiku calls (D8), so the longer the price table waits, the more results have
   to be thrown away — including the $0.014 recorded in G1.2 above.

Week 3 is not a cut. It is sequenced behind the thing that is more likely to be asked
about, and it holds the *whole* reliability story — retries, recorded failure, and resume —
in one week instead of splitting it across two.
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

- [x] **G1.1** An answerable question produces four `step` SSE events (`retrieve`,
      `score`, `answer`, `done`) followed by a cited answer.
      *Verified 2026-08-30: 3 steps + `done`, 3 citations, 7.0s.*
- [x] **G1.2** An unanswerable question produces `retrieve`, `score`, `escalate`,
      `ticket` steps; the score step shows the confidence value and the threshold it
      failed; a ticket exists in the mock service, created by an HTTP POST.
      *Verified: PLATFORM-1043, `quota_or_billing`, priority `high`, $0.014, 5.0s.
      Note which signal fired — retrieval was 0.50 (above `escalate_below`), and
      groundedness 0.05 forced the branch. Exactly the "retrieved the right document,
      which does not contain the answer" case the second signal exists for.*
- [x] **G1.3** The answering model's request payload contains no `create_escalation_ticket`
      tool definition. Asserted in a test, not by inspection.
      *Verified: payload keys are `model`, `max_tokens`, `system`, `messages` — no
      `tools` key at all, and the string "escalat" appears nowhere in the request.*
- [x] **G1.4** Killing the API mid-run leaves the completed steps in the `Run` row
      (proves D3 — this is the week-2 foundation and is cheap to check now).
      *Verified: `CRASH_AFTER=score` left `retrieve(ok) -> score(ok)` durable with
      reasoning and confidence 0.95 intact. The run sits at status `running` with no
      way to continue it — which is precisely what W2 builds.*

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

# Week 2 — Real prices, a golden set, and the numbers that come out of it

*(Task IDs `W2-1`–`W2-11` were `W3-1`–`W3-12` in the 2026-08-30 draft.)*

### Objective

Replace claims with measurements: prove what fraction of a held-out golden set the agent
routes correctly, what a query actually costs from logged tokens priced per model, and what
the cheap-router swap does to both.

---

## Eval design

The metrics are not an afterthought of the runner — they decide what the golden set has to
contain, so they are settled first.

### What is measured, and how each one is graded

| Metric | Graded by | Applies to | Why this way |
|---|---|---|---|
| **Decision accuracy** | exact match: `PipelineResult.escalated` vs `expected_outcome` | every case | The guardrail's own claim (D2), and the headline number. A string compare — no judge, no cost, no flake. |
| **Escalation precision / recall** | confusion matrix over the same field | every case | A single accuracy figure hides the asymmetry below. Report both, always. |
| **Citation recall / precision** | set compare of cited `source` doc ids against `expected_citations` | cases that answered | Recall: did it find the right document. Precision: did it avoid padding with wrong ones. Deterministic, no judge. |
| **Answer correctness** | structured-output judge returning `{correct: bool, reasoning: str}`, given question + `golden_answer` + the produced answer | cases that answered | The only metric that needs a model. Everything else is a string or set compare — keep it that way, because a judge is an instrument with its own error. |
| **Ticket category accuracy** | exact match on the escalate draft's `category` | cases that escalated | Free: the draft is already structured output with an enum. |
| **$ / query, latency** | sum `Trace.cost_usd`; `Run.steps[].latency_ms` | every case | Logged, never estimated (D8). Per-stage breakdown already lands in `Run.steps` today. |

Only one of six needs a model. That is deliberate: the metric an interviewer will push
hardest on — decision accuracy — is the one with no judge in the loop and therefore no
"how do you know the judge is right" regress.

### The asymmetry to report, not average away

The two escalation errors do not cost the same:

- **False escalate** — an answerable question sent to a human. Cost: some support time.
- **False answer** — an unanswerable question answered anyway. Cost: a confident,
  cited-looking answer about a project the corpus knows nothing about. This is the exact
  failure the two-signal guardrail exists to prevent.

So the reported figure is escalation **recall** (of the questions that should have gone to
a human, how many did), with precision alongside it as the price paid. Say which one the
thresholds were tuned toward and why. Averaging them into one F1 throws away the whole
point.

### The threshold sweep, for free

`escalate_below` and `confidence_threshold` only affect the `if` in `should_escalate()`.
Neither changes retrieval similarity, and neither changes what the scoring model returns.
So record `retrieval_confidence` and `groundedness.confidence` per case on the single eval
pass, then sweep both thresholds **offline over the recorded numbers** — no extra model
calls, no extra dollars, ~20 lines of pure Python over the results JSON.

That produces a precision/recall curve either side of the shipped thresholds, which turns
"why 0.45?" from an opinion into a chart.

**Its one limit, state it in the report:** a swept threshold that flips a case from
escalate to answer has no generated answer to grade, so the sweep scores decision accuracy
and escalation precision/recall only — never citation or answer correctness.

### Repeatability

Model calls are not deterministic and a single pass is a sample, not a truth. The honest
cheap position, in order of what it costs:

- Every report records `git_sha`, both model ids, and the three threshold values. A run
  is reproducible in configuration even when it is not reproducible token for token.
- The golden set is committed **whole, before the runner exists** (D7). Commit order is
  the only evidence the expectations were not backfilled after seeing outputs, and it is
  the claim most likely to be probed.
- Single pass per profile. If a number is close enough to matter, say "n=1, ±1 case" out
  loud rather than implying a precision that isn't there. Repeat runs are a `for` loop when
  a result is genuinely borderline — not a default that triples the bill.

### Deliberately out of scope

- **Evals in CI.** Thirty live model calls per push needs a funded key and turns a red
  build into a billing question. `make eval` locally, reports committed to the repo. The
  GitHub Action is four lines if it is ever asked for — say that, don't build it.
- **A judge-agreement study.** Hand-check the judge's disagreements once, in the report.
  Measuring the measurer is a second project.
- **A third model profile.** Two is a comparison. Three is a hobby.

---

### Exit gate

- [ ] **G2.1** A run containing both a Haiku call and a Sonnet call prices each at its own
      rate, asserted in a test. An unknown model id raises at config load (D8).
- [ ] **G2.2** The golden set has 25–30 cases and was committed **before**
      `run_evals.py` existed. Verifiable from `git log`.
- [ ] **G2.3** `configent eval` produces decision accuracy, citation precision/recall,
      escalation precision/recall, ticket category accuracy, and cost and latency per case.
- [ ] **G2.4** Two model profiles are scored side by side, and the reported $ figures come
      from `Trace.cost_usd`, not from an estimate.
- [ ] **G2.5** The offline threshold sweep reproduces the shipped thresholds' decision
      accuracy exactly, and shows the curve either side of them.

### Tasks

| ID | Component | Change | Why |
|---|---|---|---|
| **W2-1** | `app/agent/loop.py` | **Replace `_PRICE_*` constants with `_PRICES: dict[str, ModelPrice]`; price each call by the model that served it; unknown id raises at config load** | D8. Every cost number in the repo is currently wrong (Sonnet rates on Haiku calls). **Do this first** — it invalidates everything measured before it. |
| **W2-2** | `app/agent/pipeline.py` | `json.loads` in `_structured_call` gets a try/except: re-ask once, then raise. Ticket-draft failure falls back to a hardcoded draft (`category: other`, subject = truncated question) | ~8 lines, and 30 cases × 2 profiles is exactly where a malformed structured response surfaces. The fallback exists because "route to escalate on failure" is meaningless when the failing call *is* the escalate draft. |
| **W2-3** | `app/config/schema.py`, `config/gcp-platform-support.yaml` | `AgentConfig.models: {router, answer}`; a single `model` back-fills both | The profile swap needs two models per client; today it is one field. |
| **W2-4** | `evals/gcp-platform-support/golden.jsonl` | Grow 10 → 25–30, same schema the seed set already uses. ~15 answerable, ~10 escalate, ~3 adversarial. Spread the answerable cases across all ten corpus documents | The adversarial cases — questions that sit *next to* an answerable one in the corpus but whose specific number is absent — are what separate this from a happy-path demo. Ten documents and ten cases today means some documents are untested. |
| **W2-5** | — | **Commit W2-4 whole, in one commit, before W2-6 is written** | D7. Commit order is the evidence. |
| **W2-6** | `evals/runner/run_evals.py` *(new)*, `app/cli.py` | `configent eval --client --model-profile`; scores the six metrics above; writes one JSON result row per case including `retrieval_confidence` and `groundedness_confidence` | `evals/runner/` is an empty `.gitkeep` and `cli.py`'s docstring already claims eval commands that do not exist. The two confidences are what W2-8 sweeps. |
| **W2-7** | `app/models.py` | `EvalRun.model_profile` column | Compare runs by profile. The table already exists. |
| **W2-8** | `evals/runner/sweep.py` *(new)* | Offline threshold sweep over a committed results JSON; no model calls | The free artifact. Reads `retrieval_confidence` / `groundedness_confidence` and re-runs `should_escalate()`'s comparison, nothing more. |
| **W2-9** | `app/agent/pipeline.py` | Per-stage cost breakdown on the `done` event | **Mostly done:** `RunRecorder.step` already writes `tokens_in`, `tokens_out`, `cost_usd` per stage. Only the roll-up onto `done` is missing. |
| **W2-10** | `evals/reports/` *(new)* | Committed JSON + Markdown report per profile, each stamped with `git_sha`, model ids, thresholds | The artifact you actually show. |
| **W2-11** | `tests/test_evals.py` *(new)* | G2.1 (per-model pricing), G2.5 (sweep reproduces shipped thresholds), and the W2-2 corrupted-response case | Three assertions, one file. The scorer is pure functions over dicts — test it without a model. |

### Build order

`W2-1` → `W2-3` → `W2-2` → `W2-4` → **`W2-5` (commit)** → `W2-6` → `W2-7` → `W2-9` →
`W2-8` → `W2-10` → `W2-11`

The commit boundary at `W2-5` is load-bearing. Nothing that reads the golden set may exist
in the working tree when it lands.

### Risks

- **W2-1 before anything else.** Measuring with the wrong price table wastes the week.
- **The cheap-router swap may *lose* accuracy.** That is a valid, reportable result — the
  comparison is the artifact (D2), not the swap. Do not tune until it wins; a tuned
  comparison is not a comparison.
- **25–30 cases is a small n.** One case is 3–4 percentage points. Quote the case count
  next to every percentage, every time, or the number sounds more precise than it is.
- **Expectations will turn out ambiguous** (D7). Fix them in a separate, later, clearly
  labelled commit — never quietly inside the run that revealed them.
---

# Week 3 — Retries, recorded failure, resume

### Objective

Make every failure land somewhere a person can see: a ticket API that is down costs three
attempts and a recorded failure the user is told about, and a process that dies costs the
remaining stages rather than the whole run — and never files a second ticket.

*(Combines the retry/dead-letter work from the old week 3 with the resume work from the old
week 2. Both answer the same question — "what happens when it breaks" — and splitting them
across two weeks meant telling the story twice.)*

### Already shipped in week 1

Two tasks from the 2026-08-30 draft are done and are **not** repeated below:

- **`CRASH_AFTER=<stage>` fault injection** — `_maybe_crash()` in `pipeline.py`, called
  after every stage (D6).
- **`Idempotency-Key: {run_id}:{stage_seq}`** — sent by
  `tools/gcp_platform/create_escalation_ticket.py`, honoured by `apps/mockticket/`. It
  becomes an *assertion* in W3-8, not new code.

Resume also needs no new checkpoint store: a crash after `ticket` leaves that stage's
entry — id, url, eta, queue — already committed in `Run.steps`, so resume reconstructs from
the steps list alone and `Run.state` stays the single `ticket_id` it holds today.

### Exit gate

- [ ] **G3.1** With `FAIL_RATE=1.0`, a run makes 3 attempts with visible backoff, ends in
      `failed_ticket`, logs the last error, and the user still receives an answer telling
      them the question was recorded.
- [ ] **G3.2** `make crash-demo` kills the process after ticket creation. The UI shows
      "interrupted — Resume".
- [ ] **G3.3** Resume completes the run without re-running retrieve, score, or the ticket
      POST — provable from `Run.steps` and the mock service log.
- [ ] **G3.4** `GET /tickets` on the mock service shows **one** ticket for that `run_id`.
      This is the claim; prove it in a test, not just a demo.
- [ ] **G3.5** A resume attempt with a mismatched `client_id` returns 404, mirroring
      conversation ownership.

### Tasks

| ID | Component | Change | Why |
|---|---|---|---|
| **W3-1** | `app/tools/http.py` *(new)* | `post_with_retry()` — 1s/2s/4s backoff, max 3, retry only on 5xx/timeout/connect | Retrying a 422 is a bug, not resilience. The tool already classifies errors with a `retryable` flag; this consumes it. |
| **W3-2** | `app/agent/loop.py` | Tool timeout becomes per-attempt; add a separate total budget | Today's single 30s `asyncio.wait_for` cannot contain 3 attempts plus 1+2+4s of backoff — it kills the retry chain and reports a timeout, masking the very failure being demonstrated. |
| **W3-3** | `app/models.py` | Add `failed_ticket` to `Run.status`; record `last_error` and `attempts` in the ticket step | An explicit terminal state, no new table. Silent failure is what is being engineered away — a queue nobody drains does not fix that. |
| **W3-4** | `app/agent/pipeline.py` | On exhausted retries: set `failed_ticket`, emit `step{stage:"ticket", status:"failed"}` with the error, log it, and still return an answer telling the user their question was recorded | "What happens if the ticket API is down" is the VP-level question. Have a user-facing answer, not a stack trace. |
| **W3-5** | `app/agent/pipeline.py` | `resume_pipeline(run_id)`: replay from `Run.steps`, skip every stage already recorded `ok`, finish the remainder | The whole of resume. No new module — `RunRecorder` already saves; loading is `db.get(Run, run_id)`. |
| **W3-6** | `app/routers/clients.py` | `POST /c/{id}/runs/{run_id}/resume` (SSE) and `GET /c/{id}/runs/{run_id}`, both `client_id`-scoped | There is no resume entry point today — chat only starts turns. Scoping mirrors the existing conversation-ownership check (G3.5). |
| **W3-7** | `Makefile`, `apps/web/.../ChatPanel.tsx` | `make crash-demo`; persist `run_id` in the client and, on a stream that closes without `done`, show "interrupted — Resume" | Repeatable in an interview, on a laptop, at 4pm — and rendered, not a terminal screenshot. |
| **W3-8** | `tests/test_reliability.py` *(new)* | `FAIL_RATE=1.0` → 3 attempts → `failed_ticket` + user-facing answer (G3.1); crash after ticket → resume → **one** POST reached the service (G3.3, G3.4); stage skipping; mismatched `client_id` → 404 (G3.5) | G3.3 and G3.4 are the week's entire value. One file, `respx` for the retry cases, the real mock service for the idempotency one. |

### Build order

`W3-1` → `W3-2` → `W3-3` → `W3-4` → `W3-5` → `W3-6` → `W3-7` → `W3-8`

The retry cluster (`W3-1`–`W3-4`) is independent of the resume cluster (`W3-5`–`W3-7`). If
the week overruns, the retry half ships alone and still answers the VP question; resume is
the half to drop, because G1.4 already demonstrates the durability it is built on.

### Risks

- Partial state is real (D3): committed steps, uncommitted conversation turn. Resume must
  read `Run.steps`, never `Message`. Get this wrong and resume silently duplicates the
  user's turn.
- W3-2 is easy to skip and is what makes W3-1 actually work. A retry chain inside a
  too-short outer timeout is worse than no retry chain — it fails later and reports the
  wrong cause.

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
| **W4-3** | `apps/docs/.../evaluation.mdx` *(new)* | The metric definitions, the escalation asymmetry, and the threshold sweep | Week 2 is the headline artifact and has no public home otherwise. Write this one first. |
| **W4-4** | `apps/docs/.../reliability.mdx` *(new)* | Retries, the recorded-failure path, idempotency and resume | Week 3's home. Skip it if week 3's resume half was dropped — document what shipped. |
| **W4-5** | `apps/web` demo | Step timeline on by default; three seeded questions — answers, escalates, ticket-API-down | A demo that only shows the happy path invites the question you least want. |
| **W4-6** | `README.md` | One-line multi-tenant mention; lead with the support workflow; state plainly that the ticket API is a mock | Framing drop, and the honesty note from D7. |
| **W4-7** | `private/INTERVIEW.md` | New Story Bank entry, separate from Configent-1 | Do not fold these numbers into the old story — that one still lacks its own hard number. |

### Framing

**Engineer.** SSE over polling: the stream already exists, so ordered step events are free
and the audit trail is the same surface the user watches. Checkpoint at stage boundaries,
not token boundaries: a stage is the smallest unit with a validated, replayable output — a
half-generated token stream isn't state. Confidence as a hard branch: a soft signal is a
suggestion the model can talk itself out of (D2). What broke on the kill: the
request-scoped session died with the process, taking uncommitted checkpoints with it —
which is why durability writes commit independently (D3).

**Measurement.** Decision accuracy is graded by string compare, not by a judge, so there is
no "how do you know the judge is right" regress on the headline number. Escalation
precision and recall are reported separately because the two errors cost differently — a
false escalate wastes support time, a false answer ships a confident hallucination. The
thresholds are defended with a sweep over recorded confidences, which costs nothing because
the thresholds only move an `if`.

**VP.** Pain: unanswered and misrouted questions consume support time and land on the wrong
desk. Outcome: X% of a 25–30 case held-out set routed correctly, $Y per query, Z% cheaper
with the cheap-router swap at equal accuracy. Risk: if the ticket API is down, three
retries, then a recorded failure the user is told about — never a silent drop.

---

## Cut list, in order

If a week overruns, cut from the top:

1. Query expansion inside `retrieve` (W1-4).
2. The step-timeline UI polish — the events still land in `Run.steps` (W1-11).
3. The third model profile, if you were tempted to add one.
4. Resume (`W3-5`–`W3-7`). G1.4 already demonstrates the durability underneath it, and
   "resume replays from the committed steps; I scoped it out because the durability
   guarantee is the interesting half" is a better answer than a button.

**Never cut:** the golden set (W2-4), the per-model price table (W2-1), or the threshold
sweep (W2-8). Those three are the difference between a demo and an artifact.
