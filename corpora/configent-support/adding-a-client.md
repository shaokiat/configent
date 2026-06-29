# Configent: Adding a Client

**Document ID:** DOC-ADD-Rev1
**Revision Date:** June 2026

---

## 1. The Four Artifacts

Adding a new client (a new assistant) means creating up to five files and no engine code:

1. A corpus directory `corpora/<client-id>/` holding the client's documents.
2. A system prompt `prompts/<client-id>.md` describing the assistant's persona and rules.
3. A config `config/<client-id>.yaml` tying it all together.
4. A branding asset `assets/<client-id>/logo.svg`.
5. Optionally, a golden eval set `evals/<client-id>/golden.jsonl`.

If the assistant only needs to answer from documents, those files are all that is required — the
shared tools handle retrieval and citation.

---

## 2. When You Need a Client-Specific Tool

You only write code when the assistant must *do* something deterministic that retrieval cannot —
look up a live price, return an auditable verdict, or file a ticket. In that case you add one
small tool module under `apps/api/app/tools/<client>/`, register it once in the tool registry,
and list its name in the client's YAML.

The decision is simple: if the answer lives in the documents, use the shared tools; if the answer
requires a structured action or calculation, add a client-specific tool.

---

## 3. The Steps

1. Drop the documents into `corpora/<client-id>/`.
2. Write `prompts/<client-id>.md`.
3. (Optional) Add and register a client-specific tool.
4. Write `config/<client-id>.yaml`, listing the tools the assistant should have.
5. Run `make ingest CLIENT=<client-id>`, or restart the API, which ingests on startup.

The platform validates the config at startup and raises an error immediately if any key is wrong
or any tool name is unknown. There is no deployment pipeline and no code change for a
documents-only assistant.

---

## 4. Support

If you are adding a client and something does not validate, the startup error names the field and
the file. For anything not covered by this documentation — a suspected bug, a feature request, or
an account question — open a support ticket and the Configent team will follow up.

*© 2026 Configent.*
