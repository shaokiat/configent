# Implementation Plan: Configent Support Bot (primary example) + "Adding a New Use Case" guide

**Status:** approved, not yet implemented
**Date:** 2026-06-28

## Goal

Add a customer-facing **support bot** as the project's *primary*, easier-to-illustrate example,
demoting (but keeping) the niche Acme Fab example. The bot is **Configent's own support
assistant** (dogfooding): a tenant whose corpus is Configent's published docs, so the demo
assistant answers questions about the very platform you're reading about. Everything stays
runnable today — real markdown corpus + a client-specific mock tool, no new infra.

## Decisions (locked)

- **Client identity:** `client_id: configent-support` · `name: "Configent Support"` ·
  `assistant_name: ConfigentBot`. Sentinel prefix **CS-1..5**.
- **Dogfood tenant:** corpus = plain-markdown exports of the published docs.
- **Signature tool:** `create_support_ticket` as a **client-specific mock** (under
  `tools/configent_support/`), mirroring `pricing_lookup` / `coverage_check`. No webhook infra.
- **Doc scope:** lead surfaces only (Hero, demo, how-it-works, getting-started, examples).
  Deep technical docs stay on Acme/Meridian to limit churn.
- **Keep Acme + Meridian** intact as secondary live configs — nothing deleted.

## Anatomy reference (how a client is wired today)

`config/<id>.yaml` + `corpora/<id>/` (markdown) + `prompts/<id>.md` +
optional client-specific mock tool registered in `apps/api/app/tools/registry.py`.
Shared tools (`search_docs`, `get_document`) available to all; per-client tools resolved by name
at config load. Unknown tool names fail startup, not at request time
(`tools/registry.py::validate_tool_names`). `evals/sentinels.yaml` is the single source of truth
for sentinel facts; golden sets live at `evals/<id>/golden.jsonl`.

---

## Part A — Runtime / code (make `configent-support` runnable)

1. **Corpus `corpora/configent-support/`** — curated plain-markdown exports of the published
   docs (strip frontmatter + JSX/Astro components from the `.mdx`). Cover the high-traffic pages:
   quickstart, config-reference, tools-system, multi-tenancy, agent-loop, citations, examples.
   - **Sentinels CS-1..5** are real verbatim sentences already in those docs, recorded in
     `evals/sentinels.yaml`; verify each appears verbatim in the export (add if phrasing drifted):
     - CS-1 "Shared tools are available to every client: `search_docs` and `get_document`." (tools-system)
     - CS-2 "Unknown tool names fail startup, not at request time." (tools-system/registry)
     - CS-3 "Documents and queries are embedded with Voyage AI's `voyage-3` model." (quickstart)
     - CS-4 "A client is defined entirely by one YAML file in `config/` plus a corpus directory." (multi-tenancy)
     - CS-5 a citations-page sentence on `search_result_location`.
   - Respect cross-client isolation: CS-* must not appear in Acme/Meridian corpora.
   - **Snapshot caveat:** corpus is a point-in-time export; refresh path is
     `make ingest CLIENT=configent-support` (no live doc-watching).

2. **Prompt `prompts/configent-support.md`** — "Configent's support assistant; answer questions
   about the platform strictly from the docs with citations; if the docs don't cover it (bug
   report, feature request, account/billing), open a ticket via `create_support_ticket`; never
   invent behavior."

3. **Client-specific mock tool**
   `apps/api/app/tools/configent_support/create_support_ticket.py`:
   - Input schema: `subject`, `category` enum (`billing|bug|account|feature_request|other`),
     `priority` (`low|normal|high`), optional `customer_email`.
   - **Deterministic** mock (use `zlib.crc32`, not `hash()`): returns `ticket_id` like
     `CONFIGENT-1042`, `status: "open"`, `category`, `priority`, `url`, `eta_hours`.
   - Add `__init__.py` + `.gitkeep`; register one line in `apps/api/app/tools/registry.py`.

4. **`config/configent-support.yaml`**
   ```yaml
   client_id: configent-support
   name: "Configent Support"
   branding:
     logo: assets/configent-support/logo.svg
     primary_color: "#10b981"
     assistant_name: ConfigentBot
   corpus:
     source: corpora/configent-support/
     chunking: { chunk_size: 512, overlap: 64 }
   agent:
     model: claude-haiku-4-5-20251001
     system_prompt_file: prompts/configent-support.md
     max_tokens: 2048
     effort: low
     tools: [search_docs, get_document, create_support_ticket]
   evals: { golden_set: evals/configent-support/golden.jsonl, judge_model: claude-sonnet-4-6 }
   limits: { rate_limit_per_minute: 60, daily_budget_usd: 2.00 }
   ```

5. **Branding** `assets/configent-support/logo.svg` (simple placeholder mark).

6. **Evals** `evals/configent-support/golden.jsonl` — ~6 entries: 5 sentinel-derived Q/A + 1
   escalation case that should trigger `create_support_ticket`.

7. **Tests** — extend `apps/api/tests/test_tools.py` (+ `test_e2e_tools.py`):
   `create_support_ticket` determinism, schema/enum validation, registry includes it.

8. **`CONTEXT.md`** — add `configent-support` to the **Client** examples and
   `create_support_ticket` to the **Client-specific tool** definition; add one line marking
   `configent-support` a *dogfood tenant* (Corpus = the platform's own docs) so "Configent" stays
   canonical for the platform.

---

## Part B — Docs: make it the lead example (lead surfaces only)

- **`examples.mdx`** — promote the support bot to the **first Live config** with the real runnable
  YAML above. Keep Acme + Meridian as secondary live configs. Reframe the old *Planned* "Customer-
  facing support bot" as the webhook-driven evolution (generic shared HTTP tools). Update the gaps
  table (the live version is a per-client mock, not the generic HTTP tool). Replace the inline
  *Adding a new client* block with a cross-link to the new guide (Part C).
- **`Hero.astro`** — swap headline YAML snippet from `acme-fab` to `configent-support`.
- **`how-it-works.astro`** — swap inline YAML (~lines 50–66) to `configent-support`.
- **`demo.astro`** — swap `demoConfig`, metadata chips, and "things to try" to real doc questions:
  "What shared tools does every client get?", "How are tenants isolated?", "How do I add a new
  client?", plus an escalation case → ticket.
- **`getting-started.mdx` §4 "Write your first config"** — use `configent-support` as the worked
  example so the quickstart and lead example match.

**Left unchanged on Acme/Meridian:** agent-loop, tools-system, multi-tenancy, citations,
ingestion-pipeline, conversation-history, prompt-caching, sse-streaming, api-reference.

---

## Part C — New guide: `adding-a-use-case.mdx`

**Frontmatter:** `title: Adding a New Use Case`, `group: Examples`, `order: 12`. Bump
`ui-architecture`→13, `api-reference`→14, `fastapi-internals`→15 (minimal churn). Becomes the
canonical "add a use case" walkthrough; the `examples.mdx` snippet shrinks to a cross-link (one
source of truth).

**Framing:** the Configent Support Bot was added with **zero engine changes** — generalize that
into a repeatable recipe, foregrounding the one decision that matters: shared-tools-only vs. a
client-specific tool.

**Outline:**
1. **Anatomy of a client** — the 4 (+1) artifacts, table mapping each to what it controls.
2. **Decision: shared-only vs. client-specific tool** — spectrum across the three live clients;
   "when do I need a tool?" checklist.
3. **Walkthrough — building the Configent Support Bot end to end**, each step showing the real
   artifact from Part A: plant corpus + sentinels (note exporting published docs, stripping
   MDX/JSX, cross-client isolation) → system prompt → optional client-specific tool (DEFINITION +
   async execute contract, deterministic mock, one-line registration; `create_support_ticket` as
   copy-paste template) → `config/<id>.yaml` (annotated) → branding asset → optional golden evals →
   `make ingest CLIENT=<id>` (or restart) → try it.
4. **What the engine validates for you** — config validated at load; unknown tools fail startup;
   corpus scoped by `client_id`.
5. **Checklist / copy-paste skeleton** — "new use case in N steps" with a minimal file tree.

**Cross-links:** from `examples.mdx`, `getting-started.mdx` §4, and to `config-reference.mdx` /
`tools-system.mdx`.

---

## Execution order

A (corpus + sentinels → prompt → tool + registry → config → asset → evals → tests; run API tests
to prove runnable) → B (lead-surface doc swaps) → C (new guide). All three use the Configent
Support Bot as the single worked example.
