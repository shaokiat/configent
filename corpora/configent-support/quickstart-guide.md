# Configent: Quickstart Guide

**Document ID:** DOC-QS-Rev1
**Revision Date:** June 2026

---

## 1. Prerequisites

Before running Configent locally you need:

- Python 3.11 or newer
- Docker, used to run Postgres with the pgvector extension
- An Anthropic API key, used by the agent for reasoning and tool use
- A Voyage AI API key, used for embeddings

---

## 2. Install and Start Services

Clone the repository and install the backend dependencies under `apps/api`, then install the
frontend dependencies under `apps/web`. Start the supporting services — including the Postgres
instance with pgvector enabled — with `make up`. This brings up everything defined in
`infra/docker-compose.yml`.

---

## 3. Configure Environment Variables

Create `apps/api/.env` with your `ANTHROPIC_API_KEY`, your `VOYAGE_API_KEY`, and a
`DATABASE_URL` pointing at the local Postgres instance.

Documents and queries are embedded with Voyage AI's `voyage-3` model. Both the documents in a
corpus and the user's live query pass through the same embedding model, so retrieval compares
like with like. If the `VOYAGE_API_KEY` is missing or invalid, ingestion and search will fail —
this is the most common cause of an empty or erroring assistant on first run.

---

## 4. Ingest a Corpus

Run `make ingest CLIENT=<client-id>` to parse, chunk, embed, and store a client's documents. The
API also ingests on startup, so restarting the service will pick up new or changed documents.
Re-running ingest is safe: a document whose content has not changed is skipped, and a changed
document is re-chunked and replaced.

---

## 5. Run and Try It

Start the API and the web app, then open the branded chat for a client at `/c/<client-id>`. Ask
a question that the corpus can answer and watch the assistant stream a grounded, cited response.

If retrieval returns nothing relevant, the assistant is instructed to say it does not know rather
than guess — this is by design.

*© 2026 Configent.*
