"""Provider-agnostic LLM port with budget, cache, timeout and retry policies.

Adapters:
  MockLLM       deterministic, offline; derives content from the supplied context (default)
  AnthropicLLM  Messages API over HTTPS (enabled when ANTHROPIC_API_KEY is set and EVOX_LLM=anthropic)
  OpenAICompat  any OpenAI-compatible /chat/completions endpoint (EVOX_LLM=openai, OPENAI_API_KEY, OPENAI_BASE_URL)

The port's only capability is text-in/JSON-out. It has no tools that can touch
the simulation, filesystem, shell or network beyond its own provider endpoint.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

CACHE_DIR = Path("artifacts/llm_cache")


class LLMBudgetExceeded(RuntimeError):
    pass


class LLMProvider(Protocol):
    name: str
    model: str

    def complete(self, system: str, user: str, max_tokens: int) -> str: ...


@dataclass
class Budget:
    max_calls: int = 24
    max_output_tokens: int = 2500
    timeout_s: float = 60.0
    retries: int = 2
    calls: int = 0
    cache_hits: int = 0


@dataclass
class LLMClient:
    provider: LLMProvider
    budget: Budget = field(default_factory=Budget)
    use_cache: bool = True

    def json(self, system: str, user: str, validate: Callable[[Any], Any]) -> Any:
        """Call the model, parse JSON, validate with a schema; retry on invalid output."""
        key = hashlib.sha256(f"{self.provider.name}|{self.provider.model}|{system}|{user}".encode()).hexdigest()
        cpath = CACHE_DIR / f"{key}.json"
        if self.use_cache and cpath.exists():
            self.budget.cache_hits += 1
            return validate(json.loads(cpath.read_text()))
        last_err: Exception | None = None
        for attempt in range(self.budget.retries + 1):
            if self.budget.calls >= self.budget.max_calls:
                raise LLMBudgetExceeded(f"call budget {self.budget.max_calls} exhausted")
            self.budget.calls += 1
            try:
                raw = self.provider.complete(system, user + ("" if attempt == 0 else
                                                            f"\n\nYour previous answer was invalid: {last_err}. "
                                                            "Return ONLY valid JSON."), self.budget.max_output_tokens)
                data = json.loads(_extract_json(raw))
                out = validate(data)
                if self.use_cache:
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    cpath.write_text(json.dumps(data))
                return out
            except (ValueError, httpx.HTTPError) as e:  # pydantic.ValidationError is a ValueError
                last_err = e
                time.sleep(min(2**attempt, 4) if not isinstance(self.provider, MockLLM) else 0)
        raise ValueError(f"LLM output failed validation after retries: {last_err}")


def _extract_json(raw: str) -> str:
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1].rsplit("```", 1)[0]
    i, j = min((p for p in (s.find("{"), s.find("[")) if p >= 0), default=0), max(s.rfind("}"), s.rfind("]"))
    return s[i:j + 1]


class MockLLM:
    """Deterministic offline 'model': the caller passes a rule function that builds the answer.

    This keeps the full workflow (prompting, schema validation, budget, caching,
    orchestration) exercised without network access or API keys.
    """

    name = "mock"
    model = "deterministic-rules-v1"

    def __init__(self) -> None:
        self.rules: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}

    def complete(self, system: str, user: str, max_tokens: int) -> str:
        payload = json.loads(user.split("<<CONTEXT>>", 1)[1]) if "<<CONTEXT>>" in user else {}
        rule = self.rules.get(payload.get("_rule", ""))
        if rule is None:
            raise ValueError(f"no mock rule for {payload.get('_rule')}")
        return json.dumps(rule(payload))


class AnthropicLLM:
    name = "anthropic"

    def __init__(self, model: str | None = None, timeout_s: float = 60.0) -> None:
        self.model = model or os.environ.get("EVOX_LLM_MODEL", "claude-sonnet-5-5")
        self.key = os.environ["ANTHROPIC_API_KEY"]
        self.timeout = timeout_s

    def complete(self, system: str, user: str, max_tokens: int) -> str:
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=self.timeout,
                       headers={"x-api-key": self.key, "anthropic-version": "2023-06-01",
                                "content-type": "application/json"},
                       json={"model": self.model, "max_tokens": max_tokens, "system": system,
                             "messages": [{"role": "user", "content": user}]})
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")


class OpenAICompatLLM:
    name = "openai-compatible"

    def __init__(self, model: str | None = None, timeout_s: float = 60.0) -> None:
        self.model = model or os.environ.get("EVOX_LLM_MODEL", "gpt-4.1")
        self.key = os.environ["OPENAI_API_KEY"]
        self.base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.timeout = timeout_s

    def complete(self, system: str, user: str, max_tokens: int) -> str:
        r = httpx.post(f"{self.base}/chat/completions", timeout=self.timeout,
                       headers={"authorization": f"Bearer {self.key}"},
                       json={"model": self.model, "max_tokens": max_tokens,
                             "response_format": {"type": "json_object"},
                             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


def make_provider() -> LLMProvider:
    kind = os.environ.get("EVOX_LLM", "mock").lower()
    if kind == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicLLM()
    if kind == "openai" and os.environ.get("OPENAI_API_KEY"):
        return OpenAICompatLLM()
    return MockLLM()


def render_user(instructions: str, context: dict[str, Any]) -> str:
    return f"{instructions}\n\nRespond with a single JSON object.\n<<CONTEXT>>{json.dumps(context, default=str)}"
