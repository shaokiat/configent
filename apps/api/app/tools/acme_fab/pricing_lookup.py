"""pricing_lookup tool: look up part prices, volume discounts, and lead times for Acme parts."""
from typing import Any

DEFINITION = {
    "name": "pricing_lookup",
    "description": (
        "Look up the unit price, volume discount, and lead time for an Acme Fab Equipment "
        "part number. Use this tool when the user asks for a price quote, wants to know "
        "delivery time, or is enquiring about bulk purchase discounts for a specific part. "
        "Always confirm the part number using search_docs against the spare parts catalog "
        "before calling this tool, so you can verify the correct part number for the user's "
        "equipment and application."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "part_number": {
                "type": "string",
                "description": "The Acme part number (e.g., 'PX900-SEAL-A2', 'LT200-VALVE-B1').",
            },
            "quantity": {
                "type": "integer",
                "description": "The quantity being quoted. Used to determine volume discount eligibility.",
                "default": 1,
            },
        },
        "required": ["part_number"],
    },
}

# Canned pricing data — agrees with the spare parts catalog sentinel facts
_CATALOG: dict[str, dict] = {
    "PX900-SEAL-A2": {
        "description": "Chamber seal kit, fluoroelastomer",
        "unit_price_usd": 1840.00,
        "volume_discount": {"min_qty": 10, "pct": 8},
        "lead_time_days": 21,
    },
    "LT200-VALVE-B1": {
        "description": "LT-200 valve actuator",
        "unit_price_usd": 412.50,
        "volume_discount": {"min_qty": 25, "pct": 5},
        "lead_time_days": 10,
    },
    "PX900-FOCUS-R3": {
        "description": "Focus ring, silicon",
        "unit_price_usd": 340.00,
        "volume_discount": {"min_qty": 20, "pct": 5},
        "lead_time_days": 10,
    },
    "PX900-ORING-U2": {
        "description": "Upper electrode O-ring",
        "unit_price_usd": 85.00,
        "volume_discount": {"min_qty": 50, "pct": 10},
        "lead_time_days": 7,
    },
    "PX900-VALVE-S1": {
        "description": "Exhaust isolation valve seat",
        "unit_price_usd": 180.00,
        "volume_discount": {"min_qty": 10, "pct": 5},
        "lead_time_days": 14,
    },
}


async def execute(tool_input: dict[str, Any], **_) -> dict:
    part_number = tool_input["part_number"].upper().strip()
    quantity = int(tool_input.get("quantity", 1))

    entry = _CATALOG.get(part_number)
    if entry is None:
        return {
            "error": f"Part number {part_number!r} not found in the pricing catalog. "
            "Please verify the part number against the spare parts catalog."
        }

    unit_price = entry["unit_price_usd"]
    discount_info = entry["volume_discount"]
    discount_pct = 0.0
    if quantity >= discount_info["min_qty"]:
        discount_pct = discount_info["pct"]

    discounted_unit = unit_price * (1 - discount_pct / 100)
    total = discounted_unit * quantity

    return {
        "part_number": part_number,
        "description": entry["description"],
        "unit_price_usd": unit_price,
        "quantity": quantity,
        "discount_pct": discount_pct,
        "discounted_unit_price_usd": round(discounted_unit, 2),
        "total_usd": round(total, 2),
        "lead_time_days": entry["lead_time_days"],
        "volume_discount_threshold": discount_info["min_qty"],
    }
