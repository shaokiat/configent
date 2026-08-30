# Configent: Architecture

A config-driven, multi-tenant RAG + agent platform. One codebase serves a branded,
client-specific assistant per tenant, defined entirely by a YAML config file and a
document corpus — no per-client code.

**Stack:** Next.js frontend, FastAPI backend, Anthropic Claude (Sonnet), Postgres +
pgvector, Voyage AI embeddings.

---

## 1. What it does

Given a client config file and a folder of documents, the system produces:

1. A branded chat assistant (logo, colors, name, tone) at a client-specific route.
2. A RAG pipeline over that client's document corpus, with citations in every answer.
3. An agent loop with client-specific tools (a mock pricing API for one client, a
   coverage checker for another, a support-ticket filer for a third).
4. Per-client rate limiting and a daily spend budget, enforced server-side.
5. Per-span tracing (model calls and tool calls) with tokens, cache reads, cost, and
   latency, rolled up into a running conversation total.

Adding a new client requires no code changes for a documents-only assistant: drop
documents in a folder, write one YAML file and one system prompt, run the ingestion
command.

## 2. System architecture

```
 ┌──────────┐   HTTPS     ┌─────────────┐  REST   ┌────────────────┐
 │ Browser  │────────────▶│   Next.js   │────────▶│    FastAPI     │
 │          │             │  frontend   │         │    backend     │
 │ - Chat UI│   SSE       │             │         │                │
 │ - Client │◀────────────│ - Chat UI   │         │ - Agent loop   │
 │  switcher│  streaming  │ - Branding  │         │ - RAG retrieval│
 └──────────┘             └─────────────┘         │ - Tool runtime │
                                                   │ - Tracing      │
                                                   │ - Rate/budget  │
                                                   └───────┬────────┘
                                                           │
                          ┌─────────────────┬──────────────┴───────────┐
                          ▼                 ▼                          ▼
                  ┌──────────────┐  ┌───────────────┐        ┌─────────────────┐
                  │ Anthropic API│  │  Postgres +   │        │ Voyage AI       │
                  │              │  │   pgvector    │        │ embeddings      │
                  │ - Agent LLM  │  │               │        │                 │
                  │ - Tool use   │  │ - Chunks +    │        │ - Used by       │
                  │ - Citations  │  │   embeddings  │        │   ingestion +   │
                  └──────────────┘  │ - Conversations│       │   query embed   │
                                    │ - Traces      │        └─────────────────┘
                                    └───────────────┘

        Offline pipeline (CLI, run per client):
        corpora/<client>/ ──▶ ingest ──▶ chunk ──▶ embed ──▶ pgvector (scoped by client_id)
```

### Request flow for one chat turn

1. Browser sends the message plus `client_id` (from the URL path) to the FastAPI
   backend, along with a `conversation_id` if continuing a thread.
2. Backend loads the client config (system prompt, enabled tools, branding) and, if a
   `conversation_id` is present, verifies it belongs to that client before loading its
   history — a mismatch returns 404 rather than exposing another tenant's thread.
3. The request is checked against that client's rate limit and daily budget; either
   guard trips a 429 with a friendly JSON body before any model call is made.
4. The agent loop calls the Anthropic API with the client's tool definitions,
   streaming. The model issues tool calls (`search_docs`, `get_document`,
   client-specific tools).
5. `search_docs` runs vector search scoped to that client's rows in pgvector and
   returns the chunks as `search_result` content blocks with citations enabled.
   `get_document` resolves a document's full text from its `corpus://` source URI,
   scoped to the same client.
6. The final answer streams back to the browser via SSE. Citation deltas arrive
   alongside text deltas and the frontend renders them as inline source popovers.
7. Every model call and tool call is recorded as a trace row (tokens, cache reads,
   computed cost, latency). The conversation's running `total_cost` and
   `total_tokens` are updated, and the turn's cost is sent in the `done` SSE event.

## 3. The client config schema

One file fully defines a client. Validated with Pydantic at startup; a bad config
fails loudly with a clear, field-named error, never at request time.

```yaml
# config/acme-fab.yaml
client_id: acme-fab
name: "Acme Fab Equipment"
branding:
  logo: assets/acme-fab/logo.svg
  primary_color: "#1B4F8A"
  assistant_name: "AcmeAssist"
corpus:
  source: corpora/acme-fab/          # local dir in dev, gs:// URI in prod
  chunking:
    chunk_size: 800                  # tokens
    overlap: 100
agent:
  model: claude-sonnet-4-6
  system_prompt_file: prompts/acme-fab.md
  max_tokens: 4096
  effort: medium
  tools:
    - search_docs                    # shared, always on
    - get_document                   # shared, always on
    - pricing_lookup                 # client-specific, defined in tools/acme_fab/
evals:
  golden_set: evals/acme-fab/golden.jsonl
  judge_model: claude-sonnet-4-6
limits:
  rate_limit_per_minute: 20
  daily_budget_usd: 2.00
```

Startup validation rejects: a malformed `client_id`, duplicate `client_id` values
across files, an invalid `effort` value, and any tool name under `agent.tools` that
is not registered — the last of these means a typo in a tool name can never reach a
live request.

## 4. Agent loop design

The loop is a manual, hand-rolled tool-use loop against the Anthropic API rather than
a framework's built-in tool runner — the parts that matter for this project (cost
tracking, tracing, streaming, limits) all live in the loop, and it is short enough to
read end to end.

Shape:

- Call the model with the system prompt, tool definitions, and message history,
  streaming.
- If the model calls one or more tools, execute all of them and return every result
  in a single follow-up message (parallel tool calls are supported — the model may
  request several before it needs the results back).
- Append the model's full response content (not just the text) back into history, or
  tool-use blocks are lost on the next turn.
- Repeat until the model stops requesting tools, or a hard iteration cap is hit (a
  clean error, not a hang).
- Per-tool execution has a timeout so a hung tool cannot hang the whole stream.

Tool definitions are resolved per client from a single registry (name → definition +
executor); a client only ever sees the tool definitions listed in its own YAML, so it
cannot call a tool it does not know exists.

## 5. Citations

Citations are attached by the Anthropic API at generation time, not extracted or
regexed out of the answer afterward. When `search_docs` returns retrieved chunks,
they're returned as `search_result` content blocks (each with a `source` URI, a
`title`, and the passage text) with citations enabled. The model's answer comes back
as text blocks that can each carry a `citations` array of
`search_result_location` objects — source, title, and the exact `cited_text`, which
must appear verbatim in the source document. That verbatim requirement is what makes
a hallucinated citation detectable: if the cited text isn't actually in the source,
the citation is invalid.

While streaming, citation data arrives as `citations_delta` events alongside the text
deltas, and the frontend renders them as inline, expandable source popovers.

The system prompt still instructs the model to ground every claim in retrieved
sources and to say "I don't know" when retrieval comes back empty or irrelevant — the
API guarantees citation *validity*, not citation *presence*.

## 6. Prompt caching

The per-client system prompt is marked with a cache breakpoint
(`cache_control: {"type": "ephemeral"}`), so the (typically 1,500+ token) prompt and
the tool definitions are read from cache on every call after the first, at a fraction
of the input-token price. A second breakpoint sits on the last content block of the
latest turn, so conversation history accumulates in cache incrementally across a
multi-turn conversation — by turn 3 or 4, most of the input tokens are cache reads
rather than fresh input.

Caching is a strict prefix match over `tools` then `system` then `messages`: any
change earlier in that prefix invalidates everything after it, so tool definitions
are serialized in a fixed order per client and nothing volatile (timestamps, request
IDs) is interpolated into the system prompt.

## 7. Data model (Postgres)

```
clients        config snapshot, status (denormalized from YAML at load time)
documents      client_id, source_uri, title, content_hash, ingested_at
chunks         document_id, client_id, text, embedding vector(1024), metadata jsonb
conversations  client_id, started_at, total_cost, total_tokens
messages       conversation_id, role, content jsonb, citations jsonb
traces         conversation_id, span_type, tool_name, input, output,
               tokens_in, tokens_out, cache_read_tokens, cost_usd, latency_ms
eval_runs      client_id, git_sha, scores jsonb, ran_at (schema exists; not yet written)
```

Multi-tenancy is a `client_id` column on every table, enforced at the retrieval and
query layer — every search and every conversation load is filtered by `client_id`.
Row-level security is not implemented at the database layer today; `client_id` is a
trusted path parameter, filtered by the application rather than enforced by the
database.

## 8. Repo structure

```
configent/
├── apps/
│   ├── web/                  # Next.js: chat UI, client switcher
│   └── api/                  # FastAPI: agent loop, RAG, tools, tracing, limits
│       └── app/
│           ├── agent/        # loop, streaming, citations, limits
│           ├── retrieval/    # pgvector search, embed()
│           ├── tools/        # registry, shared/, acme_fab/, meridian/, configent_support/
│           ├── tracing/      # trace persistence
│           └── config/       # Pydantic schema, registry
├── config/                   # acme-fab.yaml, meridian-insurance.yaml, configent-support.yaml, gcp-platform-support.yaml
├── corpora/                  # source docs per client (small; committed)
├── prompts/                  # per-client system prompts
├── evals/                    # sentinels.yaml + golden sets (configent-support, gcp-platform-support)
├── docs/                     # this file, config reference, docs site source
├── infra/                    # Dockerfiles, docker-compose (local pg), CI
└── README.md
```

## 9. Key design decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Multi-tenancy | Single deployment, config-switched | Zero code changes to add a client; one service serves every tenant |
| Vector store | pgvector | One database for everything; no extra service to run or explain |
| Agent framework | None; raw Anthropic API manual loop | Cost tracking, limits, and streaming all live in code that's short enough to read in full |
| Citations | `search_result` blocks + API citations | Citations are guaranteed-valid (verbatim match required) instead of prompt-based quoting |
| Model | `claude-sonnet-4-6` | Current Sonnet generation; effort tuned low/medium for chat latency |
| Tracing | Homegrown Postgres `traces` table | The same data feeds cost display and (eventually) eval scoring; no extra service to run |
| Limits | Per-client rate limit + daily budget, enforced server-side | Config fields are meaningless if nothing reads them; both return a friendly 429 |

## 10. Status

**Built:**
- Config-driven multi-tenancy with fail-at-startup validation
- RAG retrieval (pgvector) scoped by `client_id`, with a similarity floor
- Manual agent loop: parallel tool calls, iteration cap, per-tool timeout
- Native citations via `search_result` blocks
- Prompt caching (system prompt + incremental turn breakpoints)
- SSE streaming chat UI with live citation popovers, cost/latency/cache footer
- Cross-tenant conversation ownership enforcement (mismatched `client_id` → 404)
- `get_document` resolves full document text from a `corpus://` source URI
- Per-client rate limiting and daily budget enforcement (429s), backed by trace
  persistence (per-span tokens/cache/cost/latency) and running conversation totals
- CI running ruff + unit tests (63 passing) on push/PR

**In progress / roadmap:**
- Eval harness (golden-set runner + LLM judge) — only 6 golden rows exist today, for
  one client, with no runner or judge wired up yet
- Admin console / API for cost and conversation observability
- Live deployment (no hosted URL yet)
- PDF ingestion (corpora are markdown-only today)
- Auth and database-enforced tenant isolation (`client_id` is currently a trusted
  path parameter, app-filtered but not backed by row-level security)
