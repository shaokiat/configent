"""The one place a model client is built (D14).

Every call goes through OpenRouter's Anthropic-compatible endpoint with the Anthropic SDK, so
`search_result` citations, structured output and `cache_control` work unchanged. Model ids are
OpenRouter's (`anthropic/claude-haiku-4.5`). Only Claude models read a `search_result` block:
a non-Claude model gets none of its text, so it can neither answer nor cite.
"""
import os

import anthropic

BASE_URL = "https://openrouter.ai/api"


def _key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set; every model call goes through OpenRouter (D14).")
    return key


def async_client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(base_url=BASE_URL, api_key=_key())


def client() -> anthropic.Anthropic:
    return anthropic.Anthropic(base_url=BASE_URL, api_key=_key())
