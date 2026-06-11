"""coverage_check tool: check coverage verdict for common Meridian claim scenarios."""
from typing import Any

DEFINITION = {
    "name": "coverage_check",
    "description": (
        "Check whether a specific claim scenario is covered under the Meridian HomeShield Plus "
        "policy. Use this tool when the user describes a specific damage or claim event and asks "
        "whether it is covered. The tool returns a structured verdict based on the policy rules. "
        "Always cross-reference the verdict against the policy wording using search_docs to "
        "confirm the relevant clause and provide an accurate citation to the user."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "scenario": {
                "type": "string",
                "description": (
                    "The claim scenario key. Supported values: "
                    "'burst_pipe_sudden' (sudden burst pipe or appliance overflow), "
                    "'gradual_seepage' (water leak developing over more than 14 days), "
                    "'unlisted_jewellery_over_5000' (jewellery above $5,000 not listed on schedule)."
                ),
                "enum": ["burst_pipe_sudden", "gradual_seepage", "unlisted_jewellery_over_5000"],
            }
        },
        "required": ["scenario"],
    },
}

# Canned data — must agree with the policy wording sentinel facts
_VERDICTS: dict[str, dict] = {
    "burst_pipe_sudden": {
        "covered": True,
        "excess_usd": 500,
        "clause": "3.1.4",
        "summary": (
            "Sudden burst pipe damage is covered under Section 3.1. "
            "The standard accidental damage excess of $500 applies."
        ),
    },
    "gradual_seepage": {
        "covered": False,
        "excess_usd": None,
        "clause": "4.2.1",
        "summary": (
            "Water damage from gradual seepage over more than 14 days is excluded under "
            "Clause 4.2.1 of the HomeShield Plus policy wording."
        ),
    },
    "unlisted_jewellery_over_5000": {
        "covered": False,
        "excess_usd": None,
        "clause": "7.3.2",
        "summary": (
            "Jewellery items valued above $5,000 that are not individually listed on the "
            "policy schedule are subject to the general per-item contents limit of $2,500 "
            "(Section 7.2 and 7.3.2). The claim will be settled at $2,500 maximum."
        ),
    },
}


async def execute(tool_input: dict[str, Any], **_) -> dict:
    scenario = tool_input["scenario"]
    verdict = _VERDICTS.get(scenario)
    if verdict is None:
        return {
            "error": f"Unknown scenario {scenario!r}. Use search_docs to look up the relevant policy clause."
        }
    return {"scenario": scenario, **verdict}
