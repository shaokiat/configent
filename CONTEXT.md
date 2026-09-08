# Configent

A config-driven enterprise AI assistant platform: one codebase spins up a branded, client-specific RAG + agent assistant from a YAML config file and a document corpus. Built as a portfolio showcase of forward-deployed-engineering skills.

## Language

**Configent**:
The canonical project name — used for the repo, database, CLI, and all user-facing surfaces.
_Avoid_: POC Factory (legacy name; see `docs/architecture.md` for public architecture docs — the original planning doc and build plan now live privately, untracked, since they contain interview-prep framing rather than engineering documentation)

**Client**:
A tenant of the platform (e.g., Cloud Platform Support, Acme Fab Equipment, Meridian Insurance), defined entirely by one YAML file in `config/` plus a corpus directory. Only configs directly in `config/` are loaded; `config/disabled/` holds tenants kept in the repo but out of the demo.
_Avoid_: tenant, customer

**Demo tenant**:
The one Client the demo serves: `gcp-platform-support` (assistant `DeployBot`), which answers Google Cloud questions from public GCP documentation and escalates what those documents cannot know. "Configent" stays canonical for the *platform*.
_Removed 2026-09-08_: the `configent-support` dogfood tenant, which answered questions about Configent itself, was deleted from the repo.

**Corpus**:
The set of source documents belonging to one Client, ingested into pgvector scoped by `client_id`.

**Outcome**:
How a turn ends on the pipeline engine — one of three, decided in Python, never by the
answering model: **answer** (cited, from the Corpus), **converse** (a greeting, a
thank-you, a meta-question, or a follow-up handled from context — no ticket), or
**escalate** (a real support question the Corpus cannot answer; a ticket is drafted,
proposed, and filed on the user's confirmation). _Added 2026-09-08, D9: "not answerable"
and "escalate" were one arm of a binary branch, so every non-question filed a ticket._
_Avoid_: "fallback", and "escalate" as a synonym for any non-answer.

**Sentinel fact**:
A sentence planted verbatim in a Corpus document so retrieval, citation, and eval tests have deterministic ground truth (AF-1..5, MI-1..5, GCP-1..5). `evals/sentinels.yaml` is the single source of truth; scenario assertions built on them live in `docs/test-anchors.md`.

**Shared tool**:
A tool available to every Client (`search_docs`, `get_document`).

**Client-specific tool**:
A mock business-system tool enabled per Client via its YAML (`pricing_lookup` for Acme, `coverage_check` for Meridian).

## Relationships

- A **Client** has exactly one **Corpus** and one YAML config
- A **Corpus** contains the **Sentinel facts** assigned to that Client; no sentinel may appear in another Client's Corpus (cross-client isolation)
- A **Client**'s agent gets all **Shared tools** plus its **Client-specific tools**, resolved by name from the tool registry at config load

## Example dialogue

> **Dev:** "Can a **Client-specific tool** like `pricing_lookup` be called by Meridian?"
> **Domain expert:** "No — tools are resolved from each **Client**'s YAML at config load; Meridian's config never lists it, so the model never sees the definition."

## Flagged ambiguities

- "poc-factory" vs "configent" — resolved 2026-06-12: **Configent** is canonical everywhere executable (CLI command is `configent`, DB is `configent`). Planning docs were consolidated, then split by audience on 2026-08-30: engineering documentation is tracked in `docs/` (`architecture.md`, `decisions.md`, `support-agent-plan.md`, `test-anchors.md`) and only interview-prep framing stays in the gitignored `private/`.
