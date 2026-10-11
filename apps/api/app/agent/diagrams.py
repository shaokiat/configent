"""Each template's graph as Mermaid, drawn from the compiled graph, for the docs.

    cd apps/api && uv run python -m app.agent.diagrams

writes `apps/docs/src/diagrams/<template>.mmd`. `tests/test_diagrams.py` fails when a
committed drawing no longer matches its graph, so the docs cannot drift from the code.

LangGraph draws the topology: solid edges are fixed, dashed ones conditional. This adds a
class per node kind; the docs' CSS colours them, so the drawing follows the site theme.
"""
from pathlib import Path

from app.agent import handoff
from app.agent.templates import TEMPLATES

OUT = Path(__file__).parents[4] / "apps/docs/src/diagrams"

# Nodes that call a model. Everything else is plain Python.
_MODEL_NODES = {"grade", "regrade", "rewrite", "answer", "generate", "repair", "escalate"}
_SHARED = {handoff.converse, handoff.decline, handoff.escalate, handoff.ticket}


def mermaid(name: str) -> str:
    graph = TEMPLATES[name].build().compile().get_graph()
    lines = [
        # LangGraph's own frontmatter and light-only fills; the docs style nodes by class.
        line for line in graph.draw_mermaid().splitlines()
        if line.strip() and not line.lstrip().startswith(("classDef", "---", "config:", "flowchart:", "curve:"))
    ]
    kinds: dict[str, list[str]] = {"model": [], "code": [], "shared": [], "pause": []}
    for node_id, node in graph.nodes.items():
        if node_id.startswith("__"):
            continue
        func = getattr(node.data, "afunc", None) or getattr(node.data, "func", None)
        kinds["model" if node_id in _MODEL_NODES else "code"].append(node_id)
        if func in _SHARED:
            kinds["shared"].append(node_id)
        if func is handoff.ticket:
            kinds["pause"].append(node_id)
    lines += [f"\tclass {','.join(ids)} {kind}" for kind, ids in kinds.items() if ids]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name in TEMPLATES:
        (OUT / f"{name}.mmd").write_text(mermaid(name))
        print(f"wrote {OUT / name}.mmd")
