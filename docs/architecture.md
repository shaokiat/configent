# Configent: Architecture

A config-driven, multi-tenant RAG platform. One codebase serves a branded, client-specific
support assistant per tenant, defined entirely by a YAML config file, a document corpus and
a prompt directory — no per-client code.

**Stack:** Next.js frontend, FastAPI backend, LangGraph, Anthropic Claude (Haiku 4.5),
Postgres + pgvector, Voyage AI embeddings.

---

## 1. What it does

Given a client config file and a folder of documents, the system produces:

1. A branded chat assistant (logo, colors, name) at a client-specific route.
2. A three-tier support graph over that client's corpus: a cited answer from retrieval, a
   second corrective search when that falls short, and a drafted ticket the user confirms
   when both do.
3. Every route decided by a Python function over config thresholds, never by a model, with
   a durable step trail per turn.
4. Per-client rate limiting and a daily spend budget, enforced server-side.
5. Per-span tracing (model calls and ticket filings) with tokens, cache reads, cost priced
   per model, and latency, rolled up into a running conversation total.

Adding a new client requires no code changes: drop documents in a folder, write one YAML file
and four prompts, run the ingestion command.

## 2. System architecture

```
 ┌──────────┐   HTTPS     ┌─────────────┐  REST   ┌────────────────┐
 │ Browser  │────────────▶│   Next.js   │────────▶│    FastAPI     │
 │          │             │  frontend   │         │    backend     │
 │ - Chat UI│   SSE       │             │         │                │
 │ - Client │◀────────────│ - Chat UI   │         │ - Support graph│
 │  switcher│  streaming  │ - Branding  │         │ - RAG retrieval│
 └──────────┘             └─────────────┘         │ - Ticket client│
                                                   │ - Tracing      │
                                                   │ - Rate/budget  │
                                                   └───────┬────────┘
                                                           │
                 ┌──────────────────┬──────────────────┬───┴──────────────┐
                 ▼                  ▼                  ▼                  ▼
         ┌──────────────┐  ┌────────────────┐  ┌───────────────┐  ┌──────────────┐
         │ Anthropic API│  │  Postgres +    │  │ Voyage AI     │  │ Ticket       │
         │              │  │   pgvector     │  │ embeddings    │  │ service      │
         │ - Grade      │  │                │  │               │  │ (mock, HTTP) │
         │ - Rewrite    │  │ - Chunks       │  │ - Ingestion + │  └──────────────┘
         │ - Draft      │  │ - Conversations│  │   query embed │
         │ - Cited answer│ │ - Runs, traces │  └───────────────┘
         └──────────────┘  │ - Checkpoints  │
                           └────────────────┘

        Offline pipeline (CLI, run per client):
        corpora/<client>/ ──▶ ingest ──▶ chunk ──▶ embed ──▶ pgvector (scoped by client_id)
```

### Request flow for one chat turn

1. Browser sends the message plus `client_id` (from the URL path) to the FastAPI backend,
   along with a `conversation_id` if continuing a thread.
2. Backend loads the client config and, if a `conversation_id` is present, verifies it
   belongs to that client — a mismatch returns 404 rather than exposing another tenant's
   thread.
3. The request is checked against that client's rate limit and daily budget; either guard
   trips a 429 with a friendly JSON body before any model call is made.
4. `retrieve` runs vector search scoped to that client's rows, and `grade` rates whether the
   passages support an answer. A Python function routes the turn: answer, converse, search
   again, or draft a ticket.
5. An answer is streamed from the Anthropic API with the passages as `search_result` content
   blocks and citations enabled, and with no tool definitions in the request.
6. Steps, text deltas and citation deltas stream back to the browser via SSE. A ticket offer
   arrives as a `ticket_proposal` event; the graph pauses until the user confirms.
7. Every model call is recorded as a trace row (tokens, cache reads, cost, latency), each
   node commits a step to the run, and the conversation's running totals are updated.

## 3. The client config schema

One file fully defines a client. Validated with Pydantic at load; a bad config fails loudly
with a clear, field-named error, never at request time.

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
    chunk_size: 512                  # tokens
    overlap: 64
agent:
  model: claude-haiku-4-5-20251001   # must have a row in config/pricing/claude.yaml
  system_prompt_file: prompts/gcp-platform-support/answer.md
  max_tokens: 2048
  retrieval_drop_floor: 0.3
  escalate_below: 0.45
  confidence_threshold: 0.6
  corrective:
    enabled: true
    query_rewrites: 3
evals:
  golden_set: evals/gcp-platform-support/golden.jsonl
  judge_model: claude-sonnet-4-6
limits:
  rate_limit_per_minute: 60
  daily_budget_usd: 2.00
```

Load-time validation rejects: a malformed `client_id`, duplicate `client_id` values across
files, an `escalate_below` at or under `retrieval_drop_floor` (a guardrail that could never
fire), any unknown `agent` key, and a model with no price.

## 4. The support graph

The turn is a LangGraph `StateGraph` in `apps/api/app/agent/graph.py`:

```
Level 1 · RAG             retrieve → grade ─┬─ answer | converse
Level 2 · corrective RAG  rewrite → hybrid_retrieve → regrade ─┬─ answer
Level 3 · human           escalate → ticket   (interrupt → user confirms → file)
```

- **Python decides every route.** `decide_level1` and `decide_level2` are plain functions
  over config thresholds; the node stores the route and the edge only reads it.
- **LangGraph owns mechanism only:** a Postgres checkpoint after every node, and the
  `interrupt()` pause while a ticket offer waits for the user.
- **The answering call is sent no tools,** so escalation is unreachable from inside the model.
- **Model calls use the Anthropic SDK directly** inside nodes, so citations stream exactly as
  the API documents them.
- **Every node commits a step** to the `runs` row on its own session before the next starts,
  so a crash leaves the finished steps on the record.

A free-form tool-use loop shipped beside the graph until D11; see `docs/decisions.md`.

## 5. Citations

Citations are attached by the Anthropic API at generation time, not extracted or regexed out
of the answer afterward. The `answer` node passes retrieved chunks as `search_result` content
blocks (each with a `source` URI, a `title`, and the passage text) with citations enabled.
The model's answer comes back as text blocks that can each carry a `citations` array — source,
title, and the exact `cited_text`, which must appear verbatim in the source document. That
verbatim requirement is what makes a hallucinated citation detectable.

While streaming, citation data arrives as `citations_delta` events alongside the text deltas,
and the frontend renders them as inline, expandable source popovers.

The graph never calls the answering model with zero passages: both route functions require
at least one before they choose `answer`.

## 6. Prompt caching

The answering call's system prompt carries a cache breakpoint
(`cache_control: {"type": "ephemeral"}`), but it is inert today: Claude Haiku 4.5 never
caches a prefix under 4,096 tokens, and the prompt is about 750. The grade, rewrite and
draft calls set no breakpoint, and conversation history is not cached.

The breakpoint starts writing if the client moves to a model with a lower minimum (1,024
tokens on Sonnet 4.6), or the prompt grows past Haiku's. Nothing volatile is interpolated
into the system prompt, so the prefix would be stable when it does.

## 7. Data model (Postgres)

```
clients        config snapshot, status (denormalized from YAML at load time)
documents      client_id, source_uri, title, content_hash, full_text, ingested_at
chunks         document_id, client_id, text, embedding vector(1024), text_search tsvector
conversations  client_id, started_at, total_cost, total_tokens
messages       conversation_id, role, content jsonb, citations jsonb, run_id
runs           conversation_id, client_id, status, current_stage, steps jsonb
traces         conversation_id, span_type, tool_name, input, output,
               tokens_in, tokens_out, cache_read_tokens, cost_usd, latency_ms
eval_runs      client_id, git_sha, scores jsonb, ran_at (schema exists; not yet written)
(LangGraph)    checkpoint tables, keyed by thread_id = run id
```

Multi-tenancy is a `client_id` column on every table, enforced at the retrieval and query
layer — every search, conversation load and run confirmation is filtered by `client_id`.
Row-level security is not implemented at the database layer today; `client_id` is a trusted
path parameter, filtered by the application rather than enforced by the database.

## 8. Repo structure

```
configent/
├── apps/
│   ├── web/                  # Next.js: chat UI, client switcher
│   ├── api/                  # FastAPI: support graph, RAG, tracing, limits
│   │   └── app/
│   │       ├── agent/        # graph, common (cost, conversations), limits
│   │       ├── retrieval/    # pgvector + full-text search, embed()
│   │       ├── config/       # Pydantic schema, registry, pricing
│   │       └── tickets.py    # the ticket service client
│   ├── mockticket/           # the mock ticket service
│   └── docs/                 # docs site source
├── config/                   # one YAML per client, plus pricing/claude.yaml
├── corpora/                  # source docs per client (small; committed)
├── prompts/                  # per-client prompt directories
├── evals/                    # sentinels.yaml + golden sets
├── docs/                     # this file, decisions, plan, test anchors
├── infra/                    # docker-compose
└── README.md
```

## 9. Key design decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Multi-tenancy | Single deployment, config-switched | Zero code changes to add a client; one service serves every tenant |
| Vector store | pgvector + Postgres full-text | One database for everything; no extra service to run or explain |
| Agent runtime | LangGraph for mechanism, Python for decisions | Checkpoints and the ticket pause come from the framework; every route is a function you can read |
| Escalation | Routed by code; answering call sent no tools | A model cannot be talked out of an `if` statement |
| Citations | `search_result` blocks + API citations | Citations are guaranteed-valid (verbatim match required) instead of prompt-based quoting |
| Model | `claude-haiku-4-5-20251001` | Cheap enough to spend extra calls on grading and rewriting |
| Cost | Priced per model from a dated YAML table | No API returns prices; an unpriced model fails startup |
| Tracing | Homegrown Postgres `traces` table | The same data feeds cost display and the daily budget; no extra service to run |
| Limits | Per-client rate limit + daily budget, enforced server-side | Config fields are meaningless if nothing reads them; both return a friendly 429 |

Full reasoning for each: `docs/decisions.md`.

## 10. Status

**Built:**
- Config-driven multi-tenancy with fail-at-load validation
- The three-tier support graph with a durable step trail and a confirm-before-filing pause
- RAG retrieval (pgvector) scoped by `client_id`, with a similarity floor, and hybrid search
  at Level 2
- Native citations via `search_result` blocks
- SSE streaming chat UI with the step trail, citation popovers and a ticket confirm card
- Cross-tenant conversation and run ownership enforcement (mismatched `client_id` → 404)
- Per-client rate limiting and daily budget enforcement (429s), backed by trace persistence
  with cost priced per model
- CI running ruff + unit tests on push/PR

**In progress / roadmap:**
- Resume for interrupted runs (checkpoints are written; no endpoint yet)
- Eval harness (golden-set runner + LLM judge) — golden rows exist for the support client,
  with no runner or judge wired up yet
- Admin console / API for cost and conversation observability
- Live deployment (no hosted URL yet)
- Auth and database-enforced tenant isolation (`client_id` is currently a trusted path
  parameter, app-filtered but not backed by row-level security)
