# Configent: Tools and the Agent Loop

**Document ID:** DOC-TOOL-Rev1
**Revision Date:** June 2026

---

## 1. How the Agent Works

Each turn, the agent receives the user's message plus the client's system prompt and tool
definitions. It decides whether to answer directly or call a tool. When it calls a tool, the
platform runs the tool, feeds the result back into the model, and the loop continues until the
agent produces a final answer. The answer is streamed to the user token by token.

The agent never sees a tool it has not been given. The tools available on any turn are exactly
the ones listed in the client's YAML config, resolved by name at config load.

---

## 2. Shared Tools

Shared tools are available to every client: `search_docs` and `get_document`.

- **`search_docs`** runs a semantic search over the client's corpus and returns the most
  relevant passages, each with a citation pointing back to its source document.
- **`get_document`** retrieves a full document (or a section of one) when the user needs more
  than a short passage — for example, a complete procedure or policy section.

Because these two tools cover the core retrieve-and-cite pattern, many assistants need nothing
else. A pure question-answering assistant over a document corpus can run on the shared tools
alone, with no custom code.

---

## 3. Client-Specific Tools

A client-specific tool adds business logic unique to one customer. It is a small module that
exposes a tool definition and an `execute` function, registered once in the tool registry, and
then enabled per client by listing its name in that client's YAML.

Shipped examples include `pricing_lookup` for Acme Fab Equipment (part prices and lead times),
`coverage_check` for Meridian Insurance (a deterministic coverage verdict for common claim
scenarios), and `create_support_ticket` for Configent Support (filing a ticket when a question
cannot be answered from the documentation).

Client-specific tools are deterministic by design. They return structured data the agent can
cite, rather than asking the model to invent business facts.

---

## 4. The Registry and Startup Validation

Every tool — shared or client-specific — is listed in a single tool registry that maps a tool
name to its definition and its executor. The names in a client's YAML are checked against this
registry when the config is loaded.

Unknown tool names fail startup, not at request time. If a config lists a tool that is not in the
registry, the platform refuses to start and reports the offending tool name and the available
tools. This means a typo in a tool name can never reach a live user — it is caught the moment the
service boots.

*© 2026 Configent.*
