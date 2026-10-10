# Configent

A platform for grounded assistants: one codebase spins up a branded, client-specific assistant from a YAML file and a sources folder. Each assistant retrieves evidence before it answers, answers only from it with citations, and escalates to a human when the evidence falls short. Built as a portfolio showcase of forward-deployed-engineering skills.

## Language

**Configent**:
The canonical project name — used for the repo, database, CLI, and all user-facing surfaces.
_Avoid_: POC Factory (legacy name; see `docs/architecture.md` for public architecture docs — the original planning doc and build plan now live privately, untracked, since they contain interview-prep framing rather than engineering documentation)

**Client**:
A tenant of the platform, defined entirely by one YAML file in `config/` plus a sources folder (a Corpus, or a database and a notes folder) and a prompt directory. Each Client runs one Engine.
_Avoid_: tenant, customer
_Amended 2026-10-08, D13_: the Client definition assumed one engine, the support graph.
_Removed 2026-09-11, D11_: Acme Fab Equipment and Meridian Insurance, the two clients on the retired loop engine, were deleted with it.

**Demo tenant**:
The one Client the demo serves: `gcp-platform-support` (assistant `DeployBot`), which answers Google Cloud questions from public GCP documentation and escalates what those documents cannot know. "Configent" stays canonical for the *platform*.
_Removed 2026-09-08_: the `configent-support` dogfood tenant, which answered questions about Configent itself, was deleted from the repo.

**Engine**:
The graph a Client runs, selected by `agent.engine` and defined in code under `app/agent/engines/`: `support_graph` (documents, D10) or `text_to_sql` (rows, D13). An engine finds evidence; code judges it; answering, conversing and escalating are shared. Config selects and tunes an engine; it never describes control flow.
_Added 2026-10-08, D13._
_Avoid_: pipeline, mode, workflow.

**Corpus**:
The set of source documents belonging to one Client of the support graph, ingested into pgvector scoped by `client_id`. It is that engine's evidence; a text-to-SQL Client has a Schema context instead.
_Amended 2026-10-08, D13._

**Schema context**:
The rendered DDL of a text-to-SQL Client's database plus its notes (column descriptions, glossary, rules), stored as one `documents` row with no chunks and placed in the prompt. Re-ingested when its fingerprint changes.
_Added 2026-10-08, D13._

**Outcome**:
How a turn ends — one of three, decided in Python, never by the answering model: **answer**
(cited, from the evidence; at Level 1 or Level 2 in the support graph), **converse** (a greeting, a thank-you or a
meta-question — no ticket), or **escalate** (a real support question neither level can
answer, or an explicit request for a human; a ticket is drafted, proposed, and filed on the
user's confirmation). _Added 2026-09-08, D9: "not answerable" and "escalate" were one arm of a
binary branch, so every non-question filed a ticket. Amended 2026-09-11, D10: a follow-up
question is a question, answered by Level 2 rather than conversed with._
_Avoid_: "fallback", and "escalate" as a synonym for any non-answer.

**Level**:
One tier of the support graph: **Level 1** is RAG (dense retrieval and a grade), **Level 2**
is corrective RAG (a query rewrite, hybrid search, a regrade), **Level 3** is a human (a
ticket the user confirms). A turn moves down only when the level above falls short. Levels belong to the support graph; "Level 3 is a human" holds for every engine.
_Added 2026-09-11, D10._
_Avoid_: "stage" for a graph node — stages belonged to the retired pipeline.

**Model price**:
USD per million tokens for one model id — input, output, cache write, cache read — in `config/pricing/claude.yaml`. Every cost figure is computed from it, so it is an estimate, not the bill.
_Added 2026-09-11, D8._

**Sentinel fact**:
A sentence planted verbatim in a Corpus document so retrieval, citation, and eval tests have deterministic ground truth (GCP-1..5). `evals/sentinels.yaml` is the single source of truth; scenario assertions built on them live in `docs/test-anchors.md`.

## Relationships

- A **Client** has exactly one **Engine**, one YAML config, a prompt directory, and one evidence source: a **Corpus** (support graph, four prompts) or a **Schema context** (text-to-SQL, three prompts)
- A **Corpus** contains the **Sentinel facts** assigned to that Client; no sentinel may appear in another Client's Corpus (cross-client isolation)
- A **Client**'s `agent.model` must have a **Model price**, or the API refuses to start

## Example dialogue

> **Dev:** "Can a **Client** config give the answering model a ticket tool?"
> **Domain expert:** "No — the schema has no `tools` key and rejects unknown ones. Escalation is **Level** 3, which the graph routes to in Python; no model ever holds the ticket client."

## Flagged ambiguities

- "poc-factory" vs "configent" — resolved 2026-06-12: **Configent** is canonical everywhere executable (CLI command is `configent`, DB is `configent`). Planning docs were consolidated, then split by audience on 2026-08-30: engineering documentation is tracked in `docs/` (`architecture.md`, `decisions.md`, `support-agent-plan.md`, `test-anchors.md`) and only interview-prep framing stays in the gitignored `private/`.
