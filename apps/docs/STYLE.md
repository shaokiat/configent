# Docs style guide

How prose in `src/content/docs/` should read. The audience is technical: engineers
who want the answer fast and can read code. Write for a scanner, not a reader.

This guide follows its own rules. If a section here reads bloated, fix the section.

## Principles

**1. Lead with the claim.** Put the conclusion in the first clause. Use the rest of
the sentence to support it. A reader scanning headings and first sentences should get
the gist without reading every line.

> Bad: "Because the cache is a prefix match, and one changed token invalidates it, the
> tool list is sorted."
> Good: "Tool definitions are sorted alphabetically. The cache is a prefix match, so a
> stable order is what makes it hit."

**2. One idea per sentence.** Two independent clauses joined by an em-dash, a comma
splice, or "and" are usually two sentences. Split them. Stacked clauses are the main
source of em-dash overuse — fix the structure and the em-dashes disappear.

**3. Name the actor; use an active verb.** "The loop executes the tool," not "the tool
is executed." Technical readers track what does what. Passive voice hides the subject
and makes them reconstruct it.

**4. When clauses stack, reach for structure.** Parallel items become a list. A
comparison becomes a table. A sequence becomes numbered steps or a diagram. Prose is the
worst container for parallel data.

**5. Cut hedges and filler.** Delete "essentially," "basically," "it's worth noting
that," and intensifiers like "actually," "really," "just." Shorten "in order to" to "to."
These add length and a chatty register that reads as machine-generated.

**6. Show, then tell.** Lead with the code block or diagram. Follow with a one-line
explanation. Don't narrate what the reader is about to see.

**7. Quantify, don't qualify.** "10× cheaper," "8 iterations," "3 RPM" — not "much
cheaper" or "a few." Numbers are information; vague adjectives are noise.

## Formatting conventions

**Backticks are for identifiers only.** Function names, types, config keys, literal
values the reader will type or grep: `search_docs`, `cosine_distance`, `input_type`.
Not for conceptual emphasis or plain nouns. Backticking ordinary words is visual noise.

**Notes and asides use a blockquote with a bold lead-in.** This matches the existing
docs.

> **Same path as ingest.** See [Ingestion Pipeline](#) for the full details.

**Cross-link at the boundary, don't duplicate.** When another page owns a topic, state
the one-line summary and link to it. Each page covers its own altitude. The Agent Loop
owns how tools *run*; Tools System owns what a tool *is*.

## Page structure

`agent-loop.mdx` is the reference page for the patterns below. Copy its shape.

**Draw the flow; don't narrate it.** When the topic is control flow with branches (a
loop, a request path, a state machine), use a diagram. agent-loop opens "How the loop
works" with a flowchart, then explains in two sentences. The diagram carries the shape;
the prose carries what the diagram can't.

- **Mermaid** for branching flow: decisions, loops, anything with arrows that fork.
- **ASCII** for static structure: call trees, box-and-arrow layers, layouts. Match the
  file you're in.

**Point form for parallel cases.** A set of branches, options, or rules reads better as
a list than as a paragraph. Format each item as a bold term, a colon, then the action,
and keep the items parallel (same part of speech, similar length):

> - **`end_turn`:** collect text and citations, return.
> - **`tool_use`:** run the requested tools concurrently, append results, loop again.

**Lead a section with the artifact.** Open with the signature, code block, diagram, or
log sample. Follow with one or two lines of prose. agent-loop's "Entry points" is a
signature block and a single sentence. This is principle 6 applied at section scale.

**Show real output, trimmed.** A short log or payload sample beats a paragraph
describing it. agent-loop's "Example: one `search_docs` call" is two log lines and one
sentence. Cut to the fields that matter; annotate with inline comments.

## Em-dash usage

Em-dashes are not banned. They're fine for a genuine aside or a sharp turn. But if a
page has one in every other sentence, that is a signal the sentences are over-built.
Prefer a period (separate thoughts), a colon (the second clause explains the first), or
a list (three or more parallel items). Reach for the em-dash last, not first.
