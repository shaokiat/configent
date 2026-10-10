# Configent

[![API CI](https://github.com/shaokiat/configent/actions/workflows/api-ci.yml/badge.svg)](https://github.com/shaokiat/configent/actions/workflows/api-ci.yml)

**Configent turns a client's documents or database into an assistant that answers with
sources and says so when it can't, optionally handing off to a human.**

One codebase; each client is one YAML file plus its sources. The config picks a **template**
(the only per-use-case code: it prepares the sources and finds evidence) and a **handoff**
(what happens when the evidence falls short: a fixed message, or a ticket the user
confirms). Everything else (cited answers, the can't-answer decision, the run trail,
checkpoints, cost, limits, streaming) is the shared platform. Python picks every route; the
model only reports what it saw. Templates find evidence; the platform decides what to do
with it.

Two templates ship, each a LangGraph graph in its own module:

- **`documents`** (DeployBot): documents, a groundedness grade, corrective retrieval.
- **`database`** (PitWall, the `f1-analyst` client): the schema in the prompt, a guarded
  read-only SELECT, the rows as evidence.

A new client of an existing pattern is a YAML file plus a sources folder. A new pattern is
code behind a stable seam: [Adding a template](https://shaokiat.github.io/configent/docs/adding-a-template/).

Enterprise AI demos are usually generic — the prospect asks "does it know our
documents?" and the honest answer is "not yet, give us a few weeks." The gap between
"prospect has documents" and "prospect sees a working, branded demo" is normally
measured in weeks of custom integration work. Configent closes that gap to under an
hour: drop a folder of documents and write one YAML file, and the platform serves a
fully branded, citation-grounded assistant for that client — with zero code changes.

---

## The config is the client

```yaml
# config/gcp-platform-support.yaml
client_id: gcp-platform-support
name: "Cloud Platform Support"
branding:
  logo: assets/gcp-platform-support/logo.svg
  primary_color: "#1a73e8"
  assistant_name: "DeployBot"
corpus:
  source: corpora/gcp-platform-support/
  chunking:
    chunk_size: 512
    overlap: 64
agent:
  template: documents
  model: anthropic/claude-haiku-4.5
  system_prompt_file: prompts/gcp-platform-support/answer.md
  max_tokens: 2048
  retrieval_drop_floor: 0.3
  escalate_below: 0.45
  confidence_threshold: 0.6
  corrective:
    enabled: true
    query_rewrites: 3
handoff:
  mode: ticket          # or omit for `mode: message`: reply with fixed text, no ticket
  categories: [account_config, quota_or_billing, incident, access_request, docs_gap, other]
limits:
  rate_limit_per_minute: 60
  daily_budget_usd: 2.00
```

This file *is* the client: its template, its branding, its documents, its prompts, its
guardrail thresholds, its handoff, its spend limits. Nothing else changes between tenants — same code, same
deployment, different YAML.

## Architecture

```
 ┌──────────┐  HTTPS   ┌─────────────┐  REST  ┌────────────────┐
 │ Browser  │─────────▶│   Next.js   │───────▶│    FastAPI     │
 │ - Chat UI│  SSE     │  frontend   │        │ - Support graph│
 │ - Client │◀─────────│ - Chat UI   │        │ - RAG retrieval│
 │  switcher│ streaming│ - Branding  │        │ - Ticket client│
 └──────────┘          └─────────────┘        │ - Tracing      │
                                               │ - Rate/budget  │
                                               └───────┬────────┘
                          ┌─────────────────┬───────────┴──────────┐
                          ▼                 ▼                      ▼
                  ┌──────────────┐  ┌───────────────┐    ┌─────────────────┐
                  │ OpenRouter   │  │  Postgres +   │    │ Voyage AI       │
                  │ Grade, draft │  │   pgvector    │    │ embeddings      │
                  │ + citations  │  │ Chunks/runs/  │    │ (ingest + query)│
                  └──────────────┘  │ checkpoints   │    └─────────────────┘
                                    └───────────────┘

  Offline: corpora/<client>/ ─▶ ingest ─▶ chunk ─▶ embed ─▶ pgvector (per client_id)
```

*(Admin console and an eval-judge service are planned, not built — see Status.
Full write-up: [`docs/architecture.md`](docs/architecture.md).)*

## What's real

- **Support graph** — a LangGraph state graph whose every route is a plain Python
  function; LangGraph supplies checkpoints and the pause before a ticket is filed, and
  model calls go through the Anthropic SDK directly (details under Status).
- **Native citations** — chunks return as `search_result` content blocks; the API
  attaches citations at generation time, and cited text must match the source
  verbatim, so a hallucinated citation is detectable.
- **Per-client isolation** — configs are validated (unknown keys and unpriced
  models rejected) at load, not request time; retrieval is scoped by `client_id` everywhere;
  conversation loading verifies ownership, so another client's conversation ID
  can't be used to pull its history.
- **Limits** — a per-client rate limit and daily spend budget are enforced
  server-side, both returning a friendly 429 instead of a raw error.
- **Tracing** — every model call and ticket filing is recorded as a trace row
  (tokens, cache reads, cost, latency), with cost priced per model from
  `config/pricing/claude.yaml`; conversations carry a running cost/token total, surfaced
  in the `done` SSE event and the chat UI footer.
- **Streaming UI** — SSE chat with live citation popovers, cost/latency footer,
  config-driven branding per client.
- **CI** — ruff + the unit test suite on every push and PR.

## Running the demo

```bash
cp .env.example .env          # add OPENROUTER_API_KEY and VOYAGE_API_KEY
make dev                      # Postgres + mock ticket service, then API and web

cd apps/api && .venv/bin/alembic upgrade head
.venv/bin/python -m app.cli --client gcp-platform-support   # ~30s, embeds the corpus
```

The API also reconciles every client's index on each start, so after this first run,
editing `corpora/` or a `corpus:` setting only needs a restart.

Then open **http://localhost:3000/c/gcp-platform-support**.

The second client, **f1-analyst** (text-to-SQL), needs its database first:
`make data-bird && make ingest CLIENT=f1-analyst`, then open `/c/f1-analyst`. Without the
database file the client loads but chat answers 409.

`make up` runs the same stack in Docker instead; `make docs` serves the docs site on
:4321.

### What to try, and what to watch

The demo is the **Cloud Platform Support** client (DeployBot): it answers Cloud Run,
GKE and IAM questions from a snapshot of public Google Cloud documentation, and
escalates to a ticket when a question depends on your own project. **Expand the step
trail above each reply** — that is the part worth looking at.

| Ask | What happens | What the trail shows |
|---|---|---|
| *"My Cloud Run container fails to start — what does the PORT error mean?"* | Answered with citations | 3 steps; groundedness ~0.95, both signals above threshold |
| *"Why won't my GKE node pool scale down after I deleted the workload?"* | Answered by synthesising the four documented causes | Retrieval names the source document it matched |
| *"Can you raise my Cloud Run instance quota for europe-west1?"* | **Escalated**; a ticket is filed over HTTP | 4 steps, `escalated` badge, and the threshold that failed |

The third one is the interesting case. Retrieval scores ~0.50 — *above* the
escalation floor, because the corpus really does contain Cloud Run autoscaling
documentation. The groundedness check comes back ~0.10 and forces the branch: the
right documents were retrieved, and they do not contain the answer. Neither signal
would have caught it alone.

Nothing about that decision is left to the model. The escalate/answer branch is an
`if` statement, and the answering model is never given the ticket tool at all — see
[D2](docs/decisions.md).

### Watching it fail

```bash
# Ticket service returns 503 on every call
FAIL_RATE=1.0 docker compose -f infra/docker-compose.yml up -d --force-recreate mockticket

# ...and back to healthy
docker compose -f infra/docker-compose.yml up -d --force-recreate mockticket

# Kill the process mid-run, after the ticket has already been filed
CRASH_AFTER=ticket make dev
```

`FAIL_RATE` and `LATENCY_MS` on the mock ticket service, and `CRASH_AFTER=<stage>` on
the API, exist so the failure paths are demonstrable on command rather than by
waiting for something to break.

**The ticket service is a mock** (`apps/mockticket/`) — a real HTTP service with a
real schema and idempotency contract, but written for this repo. It is not an
integration with a real support desk.

## Status

**Built:** config-driven multi-tenancy with fail-at-load validation; RAG
retrieval with client-scoped pgvector search; native citations; cost priced per model; per-client rate limiting and daily budget
enforcement; per-span tracing with cost/latency; cross-tenant conversation
ownership checks; streaming chat UI; CI (ruff + unit tests).

**Support agent:** a three-tier LangGraph graph for the `gcp-platform-support` client
(D10) — dense retrieval and a cheap-model groundedness grade; corrective retrieval (a query
rewrite, then Postgres full-text plus pgvector search) when that falls short; and a drafted
ticket the graph pauses on until the user confirms. Every route is a Python function, every
node commits a `runs` step and streams an SSE `step` event, and tickets are filed over real
HTTP with a positional idempotency key. It replaced a hand-written pipeline; the comparison
and rationale are in
[From Pipeline to Graph](https://shaokiat.github.io/configent/docs/from-pipeline-to-graph/).
The free-form tool-use loop that shipped beside it was then deleted:
[Retiring the Loop](https://shaokiat.github.io/configent/docs/retiring-the-loop/).

**Text-to-SQL:** a second template for the `f1-analyst` client (D13). The model writes one
SELECT; a read-only connection with a deny-by-default authorizer runs it; the rows are the
evidence for a cited answer. Eval results are not in yet (see
[Text-to-SQL](https://shaokiat.github.io/configent/docs/text-to-sql/)).

**In progress / planned:**
- Resume for interrupted runs (checkpoints are written after every node; no endpoint yet)
- LLM judge for the eval runner (`make eval` runs the BIRD and triage suites; no judge yet)
- Admin console for cost/latency/conversation observability
- Live deployment (no hosted URL yet)

## Docs

- [Architecture](docs/architecture.md)
- [Decision log](docs/decisions.md) — including what this deliberately does not build
- [Full docs site](https://shaokiat.github.io/configent/)
- [Config reference](https://shaokiat.github.io/configent/docs/config-reference/)
- [Examples](https://shaokiat.github.io/configent/docs/examples/)
- [Adding a template](https://shaokiat.github.io/configent/docs/adding-a-template/) · [Text-to-SQL](https://shaokiat.github.io/configent/docs/text-to-sql/)

## Data and attribution

The `f1-analyst` client answers from **BIRD** (BIg Bench for LaRge-scale Database Grounded
Text-to-SQL Evaluation), https://bird-bench.github.io/, licensed
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).

- `make data-bird` downloads the `formula_1` database at setup, against a pinned checksum.
- The database is **not redistributed** in this repo; `data/bird/` is gitignored.
- Only the column-description CSVs are copied into `corpora/f1-analyst/descriptions/`,
  unchanged, with a [`NOTICE.md`](corpora/f1-analyst/NOTICE.md). Material derived from them
  carries the same licence.
