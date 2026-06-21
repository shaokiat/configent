# Configent: Architecture and Implementation Plan

A config-driven enterprise AI assistant platform. One codebase spins up a fully branded,
client-specific RAG + agent assistant from a YAML config file and a document dump. The
demo ships with 2 fictional clients, switchable from a single deployment.

**Pitch line:** "I can stand up a credible enterprise AI POC in under an hour."

**Stack:** Next.js frontend, FastAPI backend, Anthropic API (`claude-sonnet-4-6`),
Postgres + pgvector, Cloud Run.

---

## 1. What it does

Given a client config file and a folder of documents, the system produces:

1. A branded chat assistant (logo, colors, name, tone) at a client-specific route.
2. A RAG pipeline over that client's document corpus, with citations in every answer.
3. An agent loop with client-specific tools (a mock pricing API for one client, a
   coverage checker for another).
4. An eval suite scored per client (retrieval hit rate, answer quality, cost, latency).
5. An admin console showing traces, cost, and latency for every conversation.

Adding a new client requires no code changes: drop documents in a folder, write one YAML
file, run the ingestion command.

## 2. System architecture

```
                          ┌─────────────────────────────────────────────┐
                          │                  Cloud Run                  │
                          │                                             │
 ┌──────────┐   HTTPS     │  ┌─────────────┐        ┌────────────────┐  │
 │ Browser  │────────────▶│  │   Next.js   │  REST  │    FastAPI     │  │
 │          │             │  │  frontend   │───────▶│    backend     │  │
 │ - Chat UI│   SSE       │  │             │        │                │  │
 │ - Client │◀────────────│  │ - Chat UI   │        │ - Agent loop   │  │
 │  switcher│  streaming  │  │ - Admin     │        │ - RAG retrieval│  │
 │ - Admin  │             │  │ - Branding  │        │ - Tool runtime │  │
 └──────────┘             │  └─────────────┘        │ - Tracing      │  │
                          │                         └───────┬────────┘  │
                          └─────────────────────────────────┼───────────┘
                                                            │
                          ┌─────────────────┬───────────────┴───────────┐
                          ▼                 ▼                           ▼
                  ┌──────────────┐  ┌───────────────┐         ┌─────────────────┐
                  │ Anthropic API│  │  Postgres +   │         │ Embeddings API  │
                  │              │  │   pgvector    │         │ (Voyage AI or   │
                  │ - Agent LLM  │  │               │         │  Vertex AI)     │
                  │ - Tool use   │  │ - Chunks +    │         │                 │
                  │ - Citations  │  │   embeddings  │         │ - Used by       │
                  │ - LLM judge  │  │ - Convos      │         │   ingestion +   │
                  │   (evals)    │  │ - Traces      │         │   query embed   │
                  └──────────────┘  │ - Eval runs   │         └─────────────────┘
                                    └───────────────┘

        Offline pipeline (CLI, run per client):
        corpora/<client>/ ──▶ ingest ──▶ chunk ──▶ embed ──▶ pgvector (scoped by client_id)
```

### Request flow for one chat turn

1. Browser sends the message plus `client_id` to the FastAPI backend.
2. Backend loads the client config (system prompt, enabled tools, branding).
3. Agent loop calls the Anthropic API with the client's tool definitions, streaming.
4. The model issues tool calls (`search_docs`, `get_document`, client-specific tools).
   `search_docs` runs vector search scoped to that client's rows in pgvector and
   returns the chunks as `search_result` content blocks with citations enabled.
5. The final answer streams back to the browser via SSE. Citation deltas arrive
   alongside text deltas and the frontend renders them as inline source markers.
6. Every step (tool calls, tokens, cost, latency) is recorded as a trace row.

## 3. The client config schema

This is the heart of the project. One file fully defines a client. Validated with
Pydantic at startup; a bad config fails loudly with a clear error, never at request time.

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
  effort: medium                     # Sonnet 4.6 defaults to high; set explicitly
  tools:
    - search_docs                    # shared, always on
    - get_document                   # shared, always on
    - pricing_lookup                 # client-specific, defined in tools/acme_fab/
evals:
  golden_set: evals/acme-fab/golden.jsonl   # 25-40 Q&A pairs
  judge_model: claude-sonnet-4-6
limits:
  rate_limit_per_minute: 20
  daily_budget_usd: 2.00
```

## 4. Claude API implementation guide (claude-sonnet-4-6)

Everything in this section is verified against the current API docs (June 2026). The
backend is Python, so use the official `anthropic` SDK (`pip install anthropic`).

### 4.1 Model facts

| Fact | Value |
|------|-------|
| Model ID | `claude-sonnet-4-6` (exact string, no date suffix) |
| Context window | 1M tokens |
| Max output | 64K tokens (stream anything above ~16K) |
| Pricing | $3 / 1M input tokens, $15 / 1M output tokens |
| Cache pricing | reads ~0.1x input price, writes 1.25x (5-min TTL) |
| Thinking | adaptive (`thinking: {"type": "adaptive"}`); `budget_tokens` is deprecated |
| Effort | `output_config: {"effort": "low"|"medium"|"high"|"max"}`, defaults to `high` |
| Prefills | assistant-turn prefills return 400; do not use them |

For a chat assistant, latency matters: set `thinking: {"type": "disabled"}` and
`effort: "low"` or `"medium"` explicitly. The default `high` effort burns latency and
tokens on questions that do not need it. The judge (section 4.5) can run at `medium`.

### 4.2 The agent loop

Use a manual loop, not the SDK tool runner. The manual loop is where tracing hooks,
the budget kill switch, and streaming live, and explaining it line by line is an
interview asset. Shape:

```python
import anthropic

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY

messages = [{"role": "user", "content": user_input}]
while True:
    with client.messages.stream(
        model=cfg.agent.model,
        max_tokens=cfg.agent.max_tokens,
        thinking={"type": "disabled"},
        output_config={"effort": cfg.agent.effort},
        system=[{
            "type": "text",
            "text": system_prompt,                      # frozen per client
            "cache_control": {"type": "ephemeral"},     # see 4.4
        }],
        tools=tool_defs,                                # stable order, see 4.4
        messages=messages,
    ) as stream:
        for event in stream:
            ...  # forward text_delta and citations_delta to the browser via SSE
        response = stream.get_final_message()

    if response.stop_reason != "tool_use":
        break

    messages.append({"role": "assistant", "content": response.content})
    results = [execute_tool(b) for b in response.content if b.type == "tool_use"]
    messages.append({"role": "user", "content": results})
```

Rules the loop must follow:

- Append the full `response.content` back (not just text), or tool_use blocks are lost.
- Each `tool_result` must carry the matching `tool_use_id`.
- Handle all tool calls in a response before continuing (the model can request several
  in parallel); return all results in a single user message.
- Use the SDK's typed exceptions (`anthropic.RateLimitError`, `anthropic.APIError`),
  never string-match error messages. The SDK already retries 429/5xx with backoff.
- Parse tool inputs as the parsed `block.input` object; never string-match the
  serialized JSON (Sonnet 4.6 may escape Unicode or slashes differently).

### 4.3 Citations: the `search_result` block

This is the load-bearing API feature of the whole project. When `search_docs` returns
retrieved chunks, do not return them as plain text. Return them as `search_result`
content blocks inside the `tool_result`, with citations enabled (GA on Sonnet 4.6, no
beta header):

```python
def search_docs_result(tool_use_id: str, hits: list[Chunk]) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": [
            {
                "type": "search_result",
                "source": hit.source_uri,        # required: URI or stable identifier
                "title": hit.document_title,     # required
                "content": [{"type": "text", "text": hit.text}],
                "citations": {"enabled": True},
            }
            for hit in hits
        ],
    }
```

The model's answer then comes back as multiple `text` blocks, each optionally carrying
a `citations` array of `search_result_location` objects:

```python
{
    "type": "search_result_location",
    "cited_text": "...",               # free: not counted toward output tokens
    "source": "corpus://acme-fab/etcher-manual",
    "title": "Plasma Etcher Maintenance Manual",
    "search_result_index": 0,          # which search_result block, request-wide order
    "start_block_index": 0,
    "end_block_index": 1,
}
```

Implementation notes:

- The text block is the minimal citable unit. One `search_result` per retrieved chunk
  gives chunk-level citations; split a chunk into several text blocks for finer grain.
- Citations must be enabled on all search results in a request or none.
- When streaming, citations arrive as `citations_delta` events on the current text
  block. Forward them on the SSE channel so the UI can attach markers live.
- The system prompt should still instruct the model to ground every claim in retrieved
  sources and say "I don't know" when retrieval comes back empty. The API guarantees
  citation validity, not citation presence.
- **Citations and structured outputs are mutually exclusive** (400 error if combined).
  This is fine: the chat path uses citations, the eval judge uses structured outputs,
  and they are separate API calls.
- `cited_text` is not billed as output tokens, and not billed as input when passed back
  in later turns. Citations are cheap.

### 4.4 Prompt caching

Caching is a prefix match over `tools` then `system` then `messages`. One byte of
change invalidates everything after it. Sonnet 4.6's minimum cacheable prefix is 2048
tokens, so the per-client system prompt should be at least that (with branding, domain
context, and grounding rules it will be).

- Put `cache_control: {"type": "ephemeral"}` on the last system block. That caches
  tools + system together. Serialize the tool list in a fixed order per client.
- Never interpolate timestamps, request IDs, or anything volatile into the system
  prompt. Dynamic context goes in user messages, after the cached prefix.
- For multi-turn conversations, also place a breakpoint on the last content block of
  the latest turn so history accrues incrementally (max 4 breakpoints per request).
- Verify with `response.usage.cache_read_input_tokens`. If it stays 0 across turns,
  a silent invalidator is in the prompt assembly. This number also feeds the cost
  column in the trace table: total prompt = `input_tokens + cache_creation_input_tokens
  + cache_read_input_tokens`, billed at 1x / 1.25x / 0.1x respectively.

Caching is also a demo talking point: the admin console can show cost per turn dropping
after turn one.

### 4.5 The eval judge: structured outputs

The judge is a separate, non-citation call, so it can use structured outputs for a
guaranteed-parseable verdict:

```python
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    output_config={
        "effort": "medium",
        "format": {
            "type": "json_schema",
            "schema": {
                "type": "object",
                "properties": {
                    "correctness": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
                    "groundedness": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
                    "citation_accuracy": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
                    "verdict": {"type": "string", "enum": ["pass", "fail"]},
                    "reasoning": {"type": "string"},
                },
                "required": ["correctness", "groundedness", "citation_accuracy",
                             "verdict", "reasoning"],
                "additionalProperties": False,
            },
        },
    },
    messages=[{"role": "user", "content": judge_prompt}],
)
```

The judge prompt contains the question, the golden answer, the assistant's answer, and
the chunks it cited. Run eval batches through the Batches API if cost matters (50% off,
results within an hour, fine for nightly runs).

### 4.6 Embeddings

Anthropic does not provide an embeddings endpoint. Use one of:

- **Voyage AI** (Anthropic's recommended embeddings partner): `voyage-3` family, simple
  REST API, generous free tier. Default choice.
- **Vertex AI** `text-embedding` models if keeping everything on GCP matters more.

Isolate the choice behind one `embed(texts: list[str]) -> list[list[float]]` function
so it is a one-file swap. Store vectors in pgvector with the dimension fixed per model;
re-ingest if the model changes.

### 4.7 Cost model (for the metrics table)

Illustrative per-query math at Sonnet 4.6 prices, assuming a ~3K-token cached system
prompt, ~2K tokens of retrieved chunks, and a ~400-token answer:

| Item | Tokens | Rate | Cost |
|------|--------|------|------|
| Cached prefix read | ~3,000 | $0.30/MTok | $0.0009 |
| Uncached input (question + chunks + tool round trip) | ~5,000 | $3/MTok | $0.0150 |
| Output (answer + tool calls) | ~700 | $15/MTok | $0.0105 |
| Embedding the query | ~30 | ~free tier | ~$0 |
| **Total** | | | **~$0.026** |

Compute the real number from trace data and put it in the README. Knowing this number
cold is an interview differentiator.

## 5. Components

### 5.1 Frontend (Next.js)

- **Client switcher**: route-based (`/c/acme-fab`). Switching swaps branding, system
  behavior, and corpus instantly. This is the money shot of every demo.
- **Chat UI**: SSE streaming, inline citation markers that expand to show `cited_text`
  and source title, tool-call indicators ("Searching documents...").
- **Admin console** (basic auth): conversation explorer with full trace replay,
  per-client cost/latency/volume stats, eval score history.

### 5.2 Backend (FastAPI)

- **Config registry**: loads and validates all client YAMLs at startup; hot-reload in dev.
- **Agent loop**: section 4.2. One generic loop; tools resolved by name from the config
  via a registry (shared tools plus client-specific modules).
- **RAG retrieval**: pgvector cosine search filtered by `client_id`, top-k with a
  similarity floor, results carrying document metadata for the `search_result` blocks.
- **Budget guard**: per-client daily token/cost ceiling checked before each API call;
  trips a 429 with a friendly message when exceeded.
- **Tracing middleware**: wraps the loop; records each span (tool call or model call)
  with tokens, cache hits, computed cost, and latency.

### 5.3 Ingestion pipeline (CLI)

```
configent ingest --client acme-fab
```

Reads raw docs (Markdown, PDF, HTML), chunks per the config, embeds via the
`embed()` function, upserts into pgvector under the client's `client_id`. Idempotent:
a content hash per document skips unchanged docs and replaces changed ones.

Corpus shortcut: generate 10 to 15 realistic docs per client with Claude from a persona
prompt ("write the maintenance FAQ for a plasma etcher vendor"). An hour per client
instead of days of hunting. Convert two or three to PDF for ingestion realism.

### 5.4 Eval harness

```
configent eval --client acme-fab
```

- **Retrieval metrics**: hit rate at k (does the golden chunk's document appear in the
  top-k results for the golden question).
- **Answer quality**: the structured-output judge from section 4.5, scoring
  correctness, groundedness, and citation accuracy.
- **Operational metrics**: p50/p95 latency and cost per query, captured during the run
  from the same tracing path production uses.
- Output: a JSON scorecard plus a Markdown table, and a row in `eval_runs` so the admin
  console charts score history. Runs locally first; wire into CI once stable.

Target output format:

| Client    | Answer quality | Retrieval hit@5 | p50 latency | Cost/query |
|-----------|---------------|-----------------|-------------|------------|
| acme-fab  | 92%           | 95%             | 2.1s        | $0.026     |
| meridian  | 89%           | 91%             | 1.8s        | $0.021     |

### 5.5 Observability

Homegrown: a `traces` table in Postgres written by the tracing middleware, rendered by
the admin console. The data is already needed for the eval and cost tables, so a third-
party tracing service adds setup without adding interview signal. Keep the middleware's
sink behind a small interface in case Langfuse becomes worth it later.

## 6. Data model (Postgres)

```
clients        config snapshot, status (denormalized from YAML at ingest time)
documents      client_id, source_uri, title, content_hash, ingested_at
chunks         document_id, client_id, text, embedding vector(1024), metadata jsonb
conversations  client_id, started_at, total_cost, total_tokens
messages       conversation_id, role, content jsonb, citations jsonb
traces         conversation_id, span_type, tool_name, input, output,
               tokens_in, tokens_out, cache_read_tokens, cost_usd, latency_ms
eval_runs      client_id, git_sha, scores jsonb, ran_at
```

Multi-tenancy is a `client_id` column everywhere, enforced in the retrieval and query
layer. No row-level security needed for a demo.

## 7. Repo structure (monorepo)

```
configent/
├── apps/
│   ├── web/                  # Next.js: chat UI, client switcher, admin
│   └── api/                  # FastAPI: agent loop, RAG, tools, tracing
│       └── app/
│           ├── agent/        # loop, streaming, citations
│           ├── retrieval/    # pgvector search, embed()
│           ├── tools/        # registry, shared/, acme_fab/, meridian/
│           ├── tracing/      # middleware + sink
│           └── config/       # Pydantic schema, registry
├── config/                   # acme-fab.yaml, meridian-insurance.yaml
├── corpora/                  # source docs per client (small; committed)
├── prompts/                  # per-client system prompts
├── evals/
│   ├── acme-fab/golden.jsonl
│   └── runner/               # eval harness CLI
├── briefs/                   # published discovery briefs (1 page per client)
├── infra/                    # Dockerfiles, docker-compose (local pg), Cloud Run, CI
└── README.md                 # diagram, eval table, video link
```

## 8. Deployment (GCP)

- **Cloud Run**: two services (web, api), scale to zero.
- **Postgres + pgvector**: Cloud SQL smallest tier, or Neon free tier if Cloud SQL cost
  is annoying for a demo. The app only sees `DATABASE_URL`. Local dev uses
  docker-compose with the `pgvector/pgvector` image.
- **Secrets**: Anthropic and Voyage keys in Secret Manager.
- **Hardening**: basic auth on admin, per-IP rate limit middleware, the per-client
  budget guard from 5.2, nightly Cloud Scheduler job resetting demo data.
- **CI (GitHub Actions)**: lint, tests, eval suite, deploy on main, README badge with
  current eval scores.

## 9. The fictional clients

1. **Acme Fab Equipment** (semiconductor fab equipment vendor): equipment manuals,
   maintenance FAQs, spare-parts docs. Client tool: `pricing_lookup` (mock JSON API).
2. **Meridian Insurance** (general insurer): policy wording documents, claims FAQs,
   underwriting guidelines. Client tool: `coverage_check` (mock JSON API).

Each client gets a published one-page discovery brief (stakeholders, pain points,
success criteria) in `briefs/`. These are FDE deliverables in their own right.

Stretch: a third client whose tool hits a real external system (Odoo/ERPNext).

## 10. Key design decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Multi-tenancy | Single deployment, config-switched | The whole point: prove repeatability; one Cloud Run service is cheap |
| Vector store | pgvector | One database for everything; no extra service; fits the GCP story |
| Agent framework | None; raw Anthropic API manual loop | Shows API fluency; the loop is where tracing, budgets, and streaming live |
| Citations | `search_result` blocks + API citations | Guaranteed-valid citations parsed by the API beat prompt-based quoting on cost and reliability |
| Model | `claude-sonnet-4-6`, thinking disabled, effort low/medium for chat | Right latency/cost point for a demo assistant; judge runs at medium |
| Evals | Per-client golden sets, structured-output judge | Evals are the top skill gap AI companies report; structured outputs make the judge parse-proof |
| Tracing | Homegrown Postgres sink | The data is needed anyway for cost/eval tables; no extra service to explain |

## 11. What the recruiter is screening for

An FDE/SE screener spends about 60 seconds on a portfolio and a hiring manager about 5
minutes. They are not reading code. They are pattern-matching for four signals, and
every artifact in this project exists to hit one of them.

### Signal 1: "Can this person stand up a convincing demo fast?"

What they fear: someone who needs three weeks and a perfect spec before a customer sees
anything.

How the project conveys it:
- The headline is the timer, not the assistant. Record the "new client onboarding" run:
  doc dump to working branded POC in under an hour, on video, with a visible clock.
- The README opens with the pitch line and the onboarding steps (3 steps, no code).
- In an interview, open the live URL and add nothing. Just flip the client switcher.
  The point lands in 10 seconds.

What to say: "Every client in this demo is one YAML file and a folder of documents. I
built the platform once so the POC takes an hour, not a sprint."

### Signal 2: "Can they handle messy enterprise reality, not toy datasets?"

What they fear: another chatbot over a clean Wikipedia dump.

How the project conveys it:
- Corpora are realistic enterprise garbage: PDFs, policy wording with cross-references,
  equipment manuals with tables. Mention the ingestion pain you solved (chunking
  tables, deduplication, content hashing).
- Client-specific tools that simulate real integrations (pricing API, coverage check),
  and the stretch goal of a tool hitting a live Odoo instance.
- Per-client auth, rate limits, and budget caps show you think about what happens when
  a real customer touches it.

What to say: "The hard part was never the model call. It was making insurance policy
PDFs retrievable and making sure the agent cites the exact clause."

### Signal 3: "Do they have production rigor, or did they stop at 'it works on my machine'?"

What they fear: candidates who have never measured anything. AI companies consistently
name evals as the #1 gap.

How the project conveys it:
- The eval table is in the README above the fold, with real numbers: answer quality,
  retrieval hit rate, p50 latency, cost per query, per client.
- Evals run in CI on every push. The badge proves it is a habit, not a one-off.
- The admin console shows you can replay any conversation and account for every cent,
  down to cache reads versus cold input tokens.

What to say: "I don't claim it works. I have 40 golden questions per client, scored on
every commit. When I changed the chunking strategy, answer quality went from X to Y and
I can show you the diff."

### Signal 4: "Can they communicate with customers, not just code?"

What they fear: a strong engineer who cannot run a discovery call or write a deliverable
a VP would read.

How the project conveys it:
- The discovery briefs in `briefs/` are the strongest non-code artifact: stakeholders,
  pain, success criteria, one page each. Almost no engineering portfolio has these.
- The demo video is told as a client story (client has a problem, here is the brief,
  here is the config, here is the live assistant, here are the scores), not a feature
  tour.
- The blog post explains the anatomy of a one-hour POC to a mixed audience.

What to say: "Before I wrote any code I wrote the discovery brief, because that is the
order it happens with a real customer."

### The 60-second path

Order the artifacts so the screener hits the strongest signals first:

1. Portfolio card: Problem / Built / Result with the eval numbers in the Result line.
2. Live URL: lands on the client switcher, not a login page.
3. README: pitch line, architecture diagram, eval table, video link, all visible
   without scrolling past anything else.
4. Everything else (briefs, blog post, code) is for the 5-minute reader.

One framing rule across all of it: never describe this as "a RAG chatbot." Describe it
as "a POC delivery system." The first is what everyone has. The second is the job.

## 12. Definition of done

- [ ] Live URL with at least 2 switchable clients
- [ ] Demo video (2 to 3 minutes, told as a client story) linked from portfolio + README
- [ ] Architecture diagram in README
- [ ] Eval table with real numbers in README and portfolio card
- [ ] Discovery briefs published
- [ ] Blog post live
