"""Per-model token prices, read from `config/pricing/claude.yaml` (D8).

Loaded once at import. The registry checks every client's model against it at config load,
so a model with no price fails startup instead of quietly costing $0.
"""
from pathlib import Path

import yaml
from pydantic import BaseModel

_REPO_ROOT = Path(__file__).parents[4]
PRICING_FILE = _REPO_ROOT / "config" / "pricing" / "claude.yaml"


class ModelPrice(BaseModel):
    """USD per million tokens."""

    input: float
    output: float
    cache_write: float
    cache_read: float


_PRICES = {
    model: ModelPrice.model_validate(row)
    for model, row in yaml.safe_load(PRICING_FILE.read_text()).items()
}


def price_for(model: str) -> ModelPrice:
    try:
        return _PRICES[model]
    except KeyError:
        raise ValueError(
            f"No price for model {model!r}. Add a row to config/pricing/claude.yaml from "
            f"the pricing page."
        ) from None
