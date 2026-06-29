# Configent: Platform Overview

**Document ID:** DOC-OV-Rev1
**Revision Date:** June 2026

---

## 1. What Configent Is

Configent is a config-driven enterprise AI assistant platform. One codebase spins up a branded,
client-specific RAG (retrieval-augmented generation) and agent assistant from a single YAML
config file and a folder of documents. There is no per-client code to write and no deployment
pipeline to run for each new assistant.

The platform is built around one idea: the differences between two customers' assistants —
their documents, branding, system prompt, model, and tools — are *data*, not code. Configent
reads that data at startup, validates it, and serves a working assistant.

---

## 2. Who It Is For

Configent is aimed at teams that need to stand up many similar-but-distinct assistants quickly:
forward-deployed engineering teams running proofs-of-concept, internal platform teams serving
multiple business units, and product teams offering a white-labelled assistant to their own
customers.

A typical engagement looks like this: a customer hands over a set of documents (manuals, FAQs,
policy wording, product docs), the team writes one YAML file and one system prompt, drops the
documents into a folder, and a branded assistant is live the same day.

---

## 3. The Core Pieces

- **Client** — a tenant of the platform, defined entirely by one YAML file in `config/` plus a
  corpus directory. Examples shipped with the platform include Acme Fab Equipment (industrial
  equipment support), Meridian Insurance (policyholder self-service), and Configent Support
  (this assistant).
- **Corpus** — the set of source documents belonging to one client, ingested into a pgvector
  store and scoped by `client_id` so no client can ever retrieve another client's content.
- **Agent** — the reasoning loop that calls tools, retrieves from the corpus, and streams a
  grounded, cited answer back to the user.
- **Tools** — capabilities the agent can call. Every client gets the shared tools; a client may
  additionally enable a client-specific tool for business logic unique to that customer.

---

## 4. What You Get Out of the Box

- Streaming, agentic chat with retrieval over the client's corpus
- Inline citations that point back to the exact source passage
- Per-client branding (logo, primary color, assistant name)
- Strict multi-tenant isolation enforced at the database query level
- Config validation at startup that fails loudly on any mistake, before a single request is served

---

## 5. How a New Assistant Is Added

Adding a new assistant is a four-step, no-code operation: drop documents into a corpus folder,
write a system prompt, write one YAML config, and ingest. The platform validates the config and
serves the assistant. See the *Configuration Reference* and *Adding a Client* documents for the
full walkthrough.

*© 2026 Configent.*
