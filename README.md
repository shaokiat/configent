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

## Running locally

```bash
# Start Postgres + API + web
make up

# Docs dev server → http://localhost:4321/configent
make docs
```

Requires `.env` with `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY`. See the
[quickstart](https://shaokiat.github.io/configent/docs/getting-started/) for full
setup steps.

## Status

**Built:** config-driven multi-tenancy with fail-at-startup validation; RAG
retrieval with client-scoped pgvector search; the agent loop described above;
native citations; prompt caching; per-client rate limiting and daily budget
enforcement; per-span tracing with cost/latency; cross-tenant conversation
ownership checks; streaming chat UI; CI (ruff + unit tests).

**In progress / planned:**
- Eval harness — golden sets + LLM judge (currently 6 golden rows for one client,
  no runner or judge yet)
- Admin console for cost/latency/conversation observability
- Live deployment (no hosted URL yet)
- PDF ingestion (corpora are markdown-only today)

## Docs

- [Architecture](docs/architecture.md)
- [Full docs site](https://shaokiat.github.io/configent/)
- [Config reference](https://shaokiat.github.io/configent/docs/config-reference/)
- [Examples](https://shaokiat.github.io/configent/docs/examples/)
