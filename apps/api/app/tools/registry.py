"""Tool registry: maps tool names to (definition, async executor) pairs.

Tool names in a client YAML are validated at config-load time against this registry.
Unknown tool names fail startup, not at request time.
"""
from collections.abc import Callable

from app.tools.acme_fab import pricing_lookup
from app.tools.configent_support import create_support_ticket
from app.tools.meridian import coverage_check
from app.tools.shared import get_document, search_docs

# Maps tool_name -> (definition_dict, async executor callable)
_REGISTRY: dict[str, tuple[dict, Callable]] = {
    "search_docs": (search_docs.DEFINITION, search_docs.execute),
    "get_document": (get_document.DEFINITION, get_document.execute),
    "pricing_lookup": (pricing_lookup.DEFINITION, pricing_lookup.execute),
    "coverage_check": (coverage_check.DEFINITION, coverage_check.execute),
    "create_support_ticket": (
        create_support_ticket.DEFINITION,
        create_support_ticket.execute,
    ),
}


def get_tool_definitions(tool_names: list[str]) -> list[dict]:
    """Return the Anthropic tool definition dicts for the given names."""
    return [_REGISTRY[name][0] for name in tool_names]


def get_tool_executor(tool_name: str) -> Callable:
    return _REGISTRY[tool_name][1]


def validate_tool_names(tool_names: list[str]) -> None:
    """Raise ValueError for any unknown tool name. Called at config load time."""
    unknown = [n for n in tool_names if n not in _REGISTRY]
    if unknown:
        raise ValueError(
            f"Unknown tool(s) in config: {unknown}. "
            f"Available tools: {sorted(_REGISTRY.keys())}"
        )


def all_tool_names() -> list[str]:
    return sorted(_REGISTRY.keys())
