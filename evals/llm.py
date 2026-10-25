"""Cached OpenAI chat helper used for test-set generation and the refusal judge.

Every call is keyed on (model, messages, temperature, response_format) and
stored in the disk cache, so re-runs are free. Token usage is accumulated for
cost reporting.
"""

import json
import logging
import os
import threading

from evals.cache import get_cache, make_key
from evals.settings import load_config

logger = logging.getLogger(__name__)


class Usage:
    def __init__(self):
        self._lock = threading.Lock()
        self.by_model: dict[str, dict[str, int]] = {}

    def add(self, model: str, prompt_tokens: int, completion_tokens: int):
        with self._lock:
            entry = self.by_model.setdefault(model, {"input": 0, "output": 0, "calls": 0})
            entry["input"] += prompt_tokens
            entry["output"] += completion_tokens
            entry["calls"] += 1

    def cost_usd(self) -> float:
        pricing = load_config()["llm"]["pricing"]
        total = 0.0
        for model, u in self.by_model.items():
            price = pricing.get(model)
            if price:
                total += u["input"] / 1e6 * price["input"] + u["output"] / 1e6 * price["output"]
        return total


usage = Usage()
_client = None


def openai_client():
    global _client
    if _client is None:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not set (add it to .env)")
        from openai import OpenAI

        _client = OpenAI()
    return _client


def chat(messages: list[dict], model: str | None = None, json_mode: bool = False,
         temperature: float | None = None) -> str:
    cfg = load_config()["llm"]
    model = model or cfg["judge_model"]
    temperature = cfg["temperature"] if temperature is None else temperature
    key = make_key("chat", model, messages, temperature, json_mode)
    cache = get_cache()
    cached = cache.get("chat", key)
    if cached is not None:
        return cached

    kwargs = {"model": model, "messages": messages, "temperature": temperature}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    response = openai_client().chat.completions.create(**kwargs)
    text = response.choices[0].message.content or ""
    if response.usage:
        usage.add(model, response.usage.prompt_tokens, response.usage.completion_tokens)
    cache.set("chat", key, text)
    return text


def chat_json(messages: list[dict], model: str | None = None,
              temperature: float | None = None) -> dict:
    text = chat(messages, model=model, json_mode=True, temperature=temperature)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("LLM returned invalid JSON: %.200s", text)
        return {}
