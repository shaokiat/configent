# Configent: Multi-Tenancy and Isolation

**Document ID:** DOC-MT-Rev1
**Revision Date:** June 2026

---

## 1. One Platform, Many Clients

Configent runs many clients from one deployment. Each client is an isolated tenant: its
documents, its chunks, and its embeddings are stored together and tagged with that client's
`client_id`. The same database holds every tenant's data, but no query ever crosses a tenant
boundary.

---

## 2. How Isolation Is Enforced

Isolation is enforced at the database query level, not by convention. Every retrieval query is
filtered by `client_id`, so a search run for one client can only ever return that client's
chunks. There is no code path that searches across clients.

A built-in guarantee follows from this: a document planted only in one client's corpus can be
retrieved for that client and is never returned for any other client. The shipped test suite
checks exactly this — a query that hits a passage for one client returns nothing containing that
passage for a different client.

---

## 3. Per-Client Configuration

Beyond data isolation, each client carries its own configuration: its own system prompt, model,
effort level, tool set, branding, and spend limits. Two clients on the same deployment can run
different Claude models with completely different instructions and tools.

This is what makes the platform safe to operate as shared infrastructure: a change to one
client's YAML or corpus affects only that client. Nothing is global except the engine itself.

---

## 4. Routing and Branding

A client is reached at `/c/<client-id>`. The UI reads the client's branding — logo, primary
color, and assistant name — so each tenant sees a chat that looks like their own product, served
from the same underlying engine.

*© 2026 Configent.*
