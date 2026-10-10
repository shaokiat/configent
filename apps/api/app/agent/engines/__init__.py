"""The engine registry (D13). A plain dict of modules in this repo, reviewed like any code."""
from app.agent.engines import support_graph
from app.agent.platform import Engine

ENGINES: dict[str, Engine] = {e.name: e for e in (support_graph.ENGINE,)}
