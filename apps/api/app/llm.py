"""The one place a model client is built (D14, D15).

Every call goes through OpenRouter's OpenAI-compatible endpoint with the OpenAI SDK, so any
model OpenRouter lists can take any call. Model ids are OpenRouter's
(`anthropic/claude-haiku-4.5`, `deepseek/deepseek-v4.1-flash`). Citations are numbered
markers the answering model writes and Python parses (D15), not an API feature.
"""
import os

import openai

BASE_URL = "https://openrouter.ai/api/v1"


def async_client() -> openai.AsyncOpenAI:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set; every model call goes through OpenRouter (D14).")
    return openai.AsyncOpenAI(base_url=BASE_URL, api_key=key)
