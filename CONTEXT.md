# Configent

A config-driven enterprise AI assistant platform: one codebase spins up a branded, client-specific RAG + agent assistant from a YAML config file and a document corpus. Built as a portfolio showcase of forward-deployed-engineering skills.

## Language

**Configent**:
The canonical project name — used for the repo, database, CLI, and all user-facing surfaces.
_Avoid_: POC Factory (legacy name; see `CONFIGENT.md` and `CONFIGENT_BUILD.md`)

**Client**:
A tenant of the platform (e.g., Acme Fab Equipment, Meridian Insurance), defined entirely by one YAML file in `config/` plus a corpus directory.
_Avoid_: tenant, customer

**Corpus**:
The set of source documents belonging to one Client, ingested into pgvector scoped by `client_id`.

**Sentinel fact**:
A sentence planted verbatim in a Corpus document so retrieval, citation, and eval tests have deterministic ground truth (AF-1..5, MI-1..5 in `CONFIGENT_BUILD.md` Part 1 §1).

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

- "poc-factory" vs "configent" — resolved 2026-06-12: **Configent** is canonical everywhere executable (CLI command is `configent`, DB is `configent`). Planning docs consolidated into `CONFIGENT.md` and `CONFIGENT_BUILD.md`.
