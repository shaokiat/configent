# Configent

[![API CI](https://github.com/shaokiat/configent/actions/workflows/api-ci.yml/badge.svg)](https://github.com/shaokiat/configent/actions/workflows/api-ci.yml)

**Config-driven, multi-tenant RAG + agent platform: one codebase, one YAML file per
client.**

Enterprise AI demos are usually generic — the prospect asks "does it know our
documents?" and the honest answer is "not yet, give us a few weeks." The gap between
"prospect has documents" and "prospect sees a working, branded demo" is normally
measured in weeks of custom integration work. Configent closes that gap to under an
hour: drop a folder of documents and write one YAML file, and the platform serves a
fully branded, citation-grounded assistant for that client — with zero code changes.

---

## The config is the client

```yaml
# config/acme-fab.yaml
client_id: acme-fab
name: "Acme Fab Equipment"
branding:
  logo: assets/acme-fab/logo.svg
  primary_color: "#1B4F8A"
  assistant_name: "AcmeAssist"
corpus:
  source: corpora/acme-fab/
  chunking:
    chunk_size: 800
    overlap: 100
agent:
  model: claude-sonnet-4-6
  system_prompt_file: prompts/acme-fab.md
  max_tokens: 4096
  effort: medium
  tools:
    - search_docs
    - get_document
    - pricing_lookup
limits:
  rate_limit_per_minute: 20
  daily_budget_usd: 2.00
```

This file *is* the client: its branding, its documents, its system prompt, its
tools, its spend limits. Nothing else changes between tenants — same code, same
deployment, different YAML.

## Architecture

```
 ┌──────────┐  HTTPS   ┌─────────────┐  REST  ┌────────────────┐
 │ Browser  │─────────▶│   Next.js   │───────▶│    FastAPI     │
 │ - Chat UI│  SSE     │  frontend   │        │ - Agent loop   │
 │ - Client │◀─────────│ - Chat UI   │        │ - RAG retrieval│
 │  switcher│ streaming│ - Branding  │        │ - Tool runtime │
 └──────────┘          └─────────────┘        │ - Tracing      │
                                               │ - Rate/budget  │
                                               └───────┬────────┘
                          ┌─────────────────┬───────────┴──────────┐
                          ▼                 ▼                      ▼
                  ┌──────────────┐  ┌───────────────┐    ┌─────────────────┐
                  │ Anthropic API│  │  Postgres +   │    │ Voyage AI       │
                  │ Agent + tools│  │   pgvector    │    │ embeddings      │
                  │ + citations  │  │ Chunks/convos/│    │ (ingest + query)│
                  └──────────────┘  │ traces        │    └─────────────────┘
                                    └───────────────┘

  Offline: corpora/<client>/ ─▶ ingest ─▶ chunk ─▶ embed ─▶ pgvector (per client_id)
```

*(Admin console and an eval-judge service are planned, not built — see Status.
Full write-up: [`docs/architecture.md`](docs/architecture.md).)*

## What's real

- **Agent loop** — hand-rolled tool-use loop against the Anthropic API (no
  framework): parallel tool calls, an iteration cap, per-tool timeouts, and prompt
  caching with per-turn breakpoints so history accrues in cache incrementally.
- **Native citations** — chunks return as `search_result` content blocks; the API
  attaches citations at generation time, and cited text must match the source
  verbatim, so a hallucinated citation is detectable.
- **Per-client isolation** — configs are validated (unknown tools rejected) at
  startup, not request time; retrieval is scoped by `client_id` everywhere;
  conversation loading verifies ownership, so another client's conversation ID
  can't be used to pull its history.
- **Limits** — a per-client rate limit and daily spend budget are enforced
  server-side, both returning a friendly 429 instead of a raw error.
- **Tracing** — every model/tool call is recorded as a trace row (tokens, cache
  reads, cost, latency); conversations carry a running cost/token total, surfaced
  in the `done` SSE event and the chat UI footer.
- **Streaming UI** — SSE chat with live citation popovers, cost/latency footer,
  config-driven branding per client.
- **CI** — ruff + the unit test suite on every push and PR.

## Running the demo

```bash
cp .env.example .env          # add ANTHROPIC_API_KEY and VOYAGE_API_KEY
make dev                      # Postgres + mock ticket service, then API and web

cd apps/api && .venv/bin/alembic upgrade head
.venv/bin/python -m app.cli --client gcp-platform-support   # ~30s, embeds the corpus
```

Then open **http://localhost:3000/c/gcp-platform-support**.

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

**Built:** config-driven multi-tenancy with fail-at-startup validation; RAG
retrieval with client-scoped pgvector search; the agent loop described above;
native citations; prompt caching; per-client rate limiting and daily budget
enforcement; per-span tracing with cost/latency; cross-tenant conversation
ownership checks; streaming chat UI; CI (ruff + unit tests).

**Support agent (week 1 of 4 complete):** a fixed-stage pipeline for the
`gcp-platform-support` client — deterministic retrieval, a cheap-model groundedness
check, and an escalation branch decided in Python; every stage committed to a `runs`
row and streamed as an SSE `step` event; tickets filed over real HTTP with a
positional idempotency key. Plan and exit gates:
[`docs/support-agent-plan.md`](docs/support-agent-plan.md).

**In progress / planned:**
- Checkpoint/resume for interrupted runs (week 2)
- Eval harness — golden sets + LLM judge (10 golden rows for the support client,
  no runner or judge yet)
- Admin console for cost/latency/conversation observability
- Live deployment (no hosted URL yet)
- PDF ingestion (corpora are markdown-only today)

## Docs

- [Architecture](docs/architecture.md)
- [Support agent plan](docs/support-agent-plan.md) · [pipeline diagram](docs/support-agent-pipeline.html)
- [Decision log](docs/decisions.md) — including what this deliberately does not build
- [Full docs site](https://shaokiat.github.io/configent/)
- [Config reference](https://shaokiat.github.io/configent/docs/config-reference/)
- [Examples](https://shaokiat.github.io/configent/docs/examples/)
