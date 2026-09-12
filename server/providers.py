"""LLM provider adapters.

Three paths, all behind one interface:

  ollama      - local model. Lowest and most predictable latency, works with no
                network at all. This is the demo default (design doc s11).
  openrouter  - cloud model, for when a bigger model gives better candidates.
  stub        - no model at all. Deterministic, instant, always available; used
                as the last-resort fallback so a dead network or unloaded model
                can never hard-fail a live demo.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

import httpx

from .config import settings

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


@dataclass
class Completion:
    text: str
    latency_ms: int
    provider: str
    model: str
    error: str | None = None


def _strip_reasoning(text: str) -> str:
    """Reasoning models leak <think> blocks; they waste tokens and break parsing."""
    return _THINK_BLOCK.sub("", text).strip()


class OllamaProvider:
    name = "ollama"

    def __init__(self) -> None:
        self.model = settings.ollama_model
        self.host = settings.ollama_host.rstrip("/")

    async def complete(self, system: str, user: str) -> Completion:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            # Disable thinking on models that support it - it is pure latency here.
            "think": False,
            # keep_alive holds weights in RAM between turns, which is the
            # difference between a ~400ms and a ~6s response mid-demo.
            "keep_alive": "30m",
            "options": {
                "temperature": settings.temperature,
                "num_predict": settings.max_tokens,
                "top_p": 0.9,
            },
        }
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
                resp = await client.post(f"{self.host}/api/chat", json=payload)
                if resp.status_code == 400:
                    # Older ollama builds reject the "think" field outright.
                    payload.pop("think", None)
                    resp = await client.post(f"{self.host}/api/chat", json=payload)
                resp.raise_for_status()
                body = resp.json()
            text = _strip_reasoning(body.get("message", {}).get("content", ""))
            return Completion(text, int((time.perf_counter() - started) * 1000),
                              self.name, self.model)
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI, never fatal
            return Completion("", int((time.perf_counter() - started) * 1000),
                              self.name, self.model, error=f"{type(exc).__name__}: {exc}")

    async def warm(self) -> Completion:
        return await self.complete("Reply with the single word: ok", "ok")


class OpenRouterProvider:
    name = "openrouter"

    def __init__(self) -> None:
        self.model = settings.openrouter_model

    async def complete(self, system: str, user: str) -> Completion:
        started = time.perf_counter()
        if not settings.openrouter_key:
            return Completion("", 0, self.name, self.model,
                              error="OPENROUTER_API_KEY is not set")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": settings.max_tokens,
            "temperature": settings.temperature,
        }
        headers = {
            "Authorization": f"Bearer {settings.openrouter_key}",
            "Content-Type": "application/json",
            "X-Title": "AAC Accelerator",
        }
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json=payload, headers=headers)
                resp.raise_for_status()
                body = resp.json()
            text = _strip_reasoning(body["choices"][0]["message"]["content"])
            return Completion(text, int((time.perf_counter() - started) * 1000),
                              self.name, self.model)
        except Exception as exc:  # noqa: BLE001
            return Completion("", int((time.perf_counter() - started) * 1000),
                              self.name, self.model, error=f"{type(exc).__name__}: {exc}")

    async def warm(self) -> Completion:
        return Completion("", 0, self.name, self.model)


class StubProvider:
    """Offline fallback. Expands each initial with a high-frequency word so the
    scanning + confirm + speak loop is always demonstrable."""

    name = "stub"
    model = "builtin-frequency-table"

    COMMON = {
        "a": ["a", "and", "am", "are", "about"],
        "b": ["be", "but", "because", "back", "bed"],
        "c": ["can", "come", "could", "call"],
        "d": ["do", "don't", "day", "down"],
        "e": ["easy", "everyone", "eat", "even"],
        "f": ["for", "feel", "from", "fine"],
        "g": ["get", "go", "good", "going"],
        "h": ["have", "help", "how", "here", "hurts"],
        "i": ["I", "is", "it", "if", "in"],
        "j": ["just", "job"],
        "k": ["know", "keep", "kind"],
        "l": ["like", "little", "let", "look"],
        "m": ["me", "my", "more", "much", "maybe"],
        "n": ["not", "need", "now", "no", "never"],
        "o": ["on", "of", "okay", "one", "out"],
        "p": ["please", "pain", "put", "people"],
        "q": ["quiet", "quick"],
        "r": ["really", "right", "rest", "ready"],
        "s": ["so", "see", "some", "sorry", "sleep"],
        "t": ["to", "the", "that", "thanks", "tired"],
        "u": ["up", "us", "under"],
        "v": ["very", "visit"],
        "w": ["want", "was", "with", "would", "water"],
        "y": ["you", "yes", "your", "yeah"],
        "z": ["zero"],
    }

    async def complete(self, system: str, user: str) -> Completion:
        return Completion("", 0, self.name, self.model)

    async def warm(self) -> Completion:
        return Completion("", 0, self.name, self.model)

    def expand(self, tokens: list[str], variants: int = 3) -> list[str]:
        out: list[str] = []
        for v in range(variants):
            words: list[str] = []
            for tok in tokens:
                if len(tok) > 1:
                    words.append(tok)
                    continue
                options = self.COMMON.get(tok.lower(), [tok])
                words.append(options[v % len(options)])
            if not words:
                continue
            sentence = " ".join(words)
            sentence = sentence[0].upper() + sentence[1:]
            out.append(sentence)
        # Dedupe, preserving order.
        return list(dict.fromkeys(out))


_REGISTRY = {
    "ollama": OllamaProvider,
    "openrouter": OpenRouterProvider,
    "stub": StubProvider,
}

STUB = StubProvider()


def get_provider(name: str | None = None):
    key = (name or settings.primary_provider).lower()
    if key not in _REGISTRY:
        raise ValueError(f"unknown provider {key!r}; choose from {sorted(_REGISTRY)}")
    return _REGISTRY[key]()
