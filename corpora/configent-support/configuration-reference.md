# Configent: Configuration Reference

**Document ID:** DOC-CFG-Rev1
**Revision Date:** June 2026

---

## 1. The Config Is the Product

A client is defined entirely by one YAML file in `config/` plus a corpus directory. Everything
that makes one assistant different from another — its name, branding, documents, system prompt,
model, tools, and limits — lives in that file and that folder. There is no per-client code.

When the API starts, it loads every `*.yaml` file in `config/`, validates each against the
config schema, and registers the resulting clients. A malformed config fails startup with an
error that names both the offending field and the file, so mistakes surface immediately rather
than at request time.

---

## 2. Top-Level Sections

A client config has the following sections:

- **`client_id`** — a lowercase slug (letters, digits, hyphens) that uniquely identifies the
  client. It scopes the corpus, the database rows, and the chat URL.
- **`name`** — the human-readable client name.
- **`branding`** — `logo`, `primary_color`, and `assistant_name`. These drive the chat UI.
- **`corpus`** — the `source` directory and optional `chunking` settings (`chunk_size` and
  `overlap`).
- **`agent`** — the `model`, the `system_prompt_file`, `max_tokens`, `effort`, and the list of
  `tools`.
- **`evals`** — an optional `golden_set` path and `judge_model` for offline quality checks.
- **`limits`** — `rate_limit_per_minute` and `daily_budget_usd` guardrails.

---

## 3. Choosing Chunking Settings

`chunk_size` and `overlap` control how documents are split before embedding. Smaller chunks give
more precise retrieval for short factual lookups; larger chunks preserve more context for dense
reference material. A common default is a chunk size of 512 to 800 tokens with an overlap of
roughly one-eighth of the chunk size.

---

## 4. Choosing a Model and Effort

The `model` field selects the Claude model the agent uses. The `effort` field is one of `low`,
`medium`, `high`, or `max`, and tunes how much reasoning the agent applies. Factual lookup
assistants run well on a fast model at `low` or `medium` effort; multi-hop research assistants
benefit from a stronger model at `high` effort.

---

## 5. Validation Guarantees

The platform validates `client_id` is a proper slug, rejects duplicate `client_id` values across
files, checks that `effort` is one of the allowed values, and verifies that every tool named in
`agent.tools` exists in the tool registry. Any failure stops startup with a descriptive error.

*© 2026 Configent.*
