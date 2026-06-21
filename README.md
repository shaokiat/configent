# Configent

Config-driven agentic workflow engine for enterprise AI.

**[→ Full docs at shaokiat.github.io/configent](https://shaokiat.github.io/configent/)**

---

## What it is

Configent spins up production-ready RAG pipelines and agentic assistants from a single YAML file. No code changes per client — swap the config, restart, done.

```yaml
client_id: acme-fab
name: "Acme Fab Equipment"

corpus:
  source: corpora/acme-fab/

agent:
  model: claude-sonnet-4-6
  system_prompt_file: prompts/acme-fab.md
  tools:
    - search_docs
    - get_document
    - pricing_lookup
```

## Stack

| Layer | Tech |
|---|---|
| API | FastAPI + Python 3.12 |
| Frontend | Next.js 14 (App Router) |
| LLM | Anthropic Claude (streaming SSE) |
| Embeddings | Voyage AI `voyage-3` |
| Vector store | pgvector (Postgres) |
| Docs | Astro → GitHub Pages |

## Running locally

```bash
# Start Postgres + API + web
make up

# Docs dev server → http://localhost:4321/configent
make docs
```

Requires `.env` with `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY`. See the [quickstart](https://shaokiat.github.io/configent/docs/getting-started/) for full setup steps.

## Docs

- [How it works](https://shaokiat.github.io/configent/how-it-works/)
- [Config reference](https://shaokiat.github.io/configent/docs/config-reference/)
- [Examples](https://shaokiat.github.io/configent/docs/examples/)
