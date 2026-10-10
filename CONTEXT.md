# Configent

Configent turns a client's documents or database into an assistant that answers with sources and says so when it can't, optionally handing off to a human. One codebase; each client is a YAML file plus its sources. Built as a portfolio showcase of forward-deployed-engineering skills.

## Language

**Configent**:
The canonical project name — used for the repo, database, CLI, and all user-facing surfaces.
_Avoid_: POC Factory (legacy name; see `docs/architecture.md` for public architecture docs — the original planning doc and build plan now live privately, untracked, since they contain interview-prep framing rather than engineering documentation)

**Client**:
A tenant of the platform, defined entirely by one YAML file in `config/` plus a sources folder (a Corpus, or a database and a notes folder) and a prompt directory. Each Client runs one Template and has one Handoff.
_Avoid_: tenant, customer
_Amended 2026-10-08, D13_: the Client definition assumed one template, the support graph.
_Removed 2026-09-11, D11_: Acme Fab Equipment and Meridian Insurance, the two clients on the retired loop engine, were deleted with it.

**Demo tenant**:
The one Client the demo serves: `gcp-platform-support` (assistant `DeployBot`), which answers Google Cloud questions from public GCP documentation and offers a ticket for what those documents cannot know. The second Client, `f1-analyst` (`PitWall`), runs the database template over BIRD's `formula_1`. "Configent" stays canonical for the *platform*.
_Removed 2026-09-08_: the `configent-support` dogfood tenant, which answered questions about Configent itself, was deleted from the repo.

**Template**:
The only part of a Client that is code: it prepares the sources and finds evidence. Selected by `agent.template` and defined under `app/agent/templates/`: `documents` (the support graph: chunk, embed, retrieve, grade, corrective retrieval; D10) or `database` (schema and notes in the prompt, generate → guard → execute → one repair; D13). Templates find evidence; the platform decides what to do with it. Config selects and tunes a template; it never describes control flow.
_Renamed 2026-10-10, D13: was **Engine** (`agent.engine`, `support_graph`, `text_to_sql`)._
_Avoid_: engine, pipeline, mode, workflow.

**Handoff**:
What a Client does when it can't answer, set by `handoff.mode`. `message` (the default) replies with fixed text: no ticket, no model call. `ticket` drafts one, offers it, and files it once on the user's confirmation. The *decision* that a turn can't be answered is the template's and is made in Python; only the action is per Client.
_Added 2026-10-10, D9 (amended)._
_Avoid_: "escalate" for the message mode — nothing reaches a person.

**Corpus**:
The set of source documents belonging to one Client of the documents template, ingested into pgvector scoped by `client_id`. It is that template's evidence; a database Client has a Schema context instead.
_Amended 2026-10-08, D13._

**Schema context**:
The rendered DDL of a database Client's database plus its notes (column descriptions, glossary, rules), stored as one `documents` row with no chunks and placed in the prompt. Re-ingested when its fingerprint changes.
_Added 2026-10-08, D13._

**Outcome**:
How a turn ends, routed in Python: the model reports what it saw (a kind, a confidence, an
error), never the route. **answer** (cited, from the evidence; at Level 1 or Level 2 in the
support graph), **converse** (a greeting, a thank-you or a meta-question — no ticket), or the
Client's **Handoff** for a real question the evidence can't answer or an explicit request for
a person: **decline** (`message` mode) or **ticket** (`ticket` mode; drafted, proposed, and
filed on the user's confirmation). _Added 2026-09-08, D9: "not answerable" and "escalate" were one arm of a
binary branch, so every non-question filed a ticket. Amended 2026-09-11, D10: a follow-up
question is a question, answered by Level 2 rather than conversed with. Amended 2026-10-10:
the can't-answer arm ends in the Client's Handoff, so `decline` joins the outcomes._
_Avoid_: "fallback", and "escalate" as a synonym for any non-answer.

**Level**:
One tier of the support graph: **Level 1** is RAG (dense retrieval and a grade), **Level 2**
is corrective RAG (a query rewrite, hybrid search, a regrade), **Level 3** is the Client's
Handoff (a message, or a ticket the user confirms). A turn moves down only when the level above falls short. Levels belong to the support graph; Level 3 holds for every template.
_Added 2026-09-11, D10._
_Avoid_: "stage" for a graph node — stages belonged to the retired pipeline.

**Model price**:
USD per million tokens for one model id — input, output, cache write, cache read — in `config/pricing/claude.yaml`. Every cost figure is computed from it, so it is an estimate, not the bill.
_Added 2026-09-11, D8._

**Sentinel fact**:
A sentence planted verbatim in a Corpus document so retrieval, citation, and eval tests have deterministic ground truth (GCP-1..5). `evals/sentinels.yaml` is the single source of truth; scenario assertions built on them live in `docs/test-anchors.md`.

## Relationships

- A **Client** has exactly one **Template**, one **Handoff**, one YAML config, a prompt directory, and one evidence source: a **Corpus** (documents, four prompts) or a **Schema context** (database, three prompts)
- A **Corpus** contains the **Sentinel facts** assigned to that Client; no sentinel may appear in another Client's Corpus (cross-client isolation)
- A **Client**'s `agent.model` must have a **Model price**, or the API refuses to start

## Example dialogue

> **Dev:** "Can a **Client** config give the answering model a ticket tool?"
> **Domain expert:** "No — the schema has no `tools` key and rejects unknown ones. The **Handoff** is **Level** 3, which the graph routes to in Python; no model ever holds the ticket client, and a `message` Client has none to hold."

## Flagged ambiguities

- "poc-factory" vs "configent" — resolved 2026-06-12: **Configent** is canonical everywhere executable (CLI command is `configent`, DB is `configent`). Planning docs were consolidated, then split by audience on 2026-08-30: engineering documentation is tracked in `docs/` (`architecture.md`, `decisions.md`, `test-anchors.md`) and only interview-prep framing stays in the gitignored `private/`.
