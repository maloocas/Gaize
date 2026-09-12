"""Runtime configuration, read from environment / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Minimal .env loader so we don't need python-dotenv."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    # Providers tried in order until enough valid candidates come back.
    #   openrouter  - cloud, best constraint satisfaction (~98% measured)
    #   ollama      - local model, works offline (weak on this task: ~8%)
    #   constrained - built-in offline generator, 100% valid by construction
    # "constrained" always runs last as the floor, whether listed or not.
    provider_chain_raw: str = os.environ.get(
        "AAC_PROVIDER_CHAIN", os.environ.get("AAC_PROVIDER", "openrouter,constrained"))

    ollama_host: str = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    ollama_model: str = os.environ.get("AAC_OLLAMA_MODEL", "llama3.2:3b")

    openrouter_key: str = os.environ.get("OPENROUTER_API_KEY", "")
    openrouter_model: str = os.environ.get("AAC_OPENROUTER_MODEL", "google/gemma-3-12b-it")

    # Generation budget. Kept deliberately small: see design doc s7/s11 (latency).
    max_tokens: int = int(os.environ.get("AAC_MAX_TOKENS", "220"))
    temperature: float = float(os.environ.get("AAC_TEMPERATURE", "0.8"))
    request_timeout: float = float(os.environ.get("AAC_TIMEOUT", "20"))

    # How many candidates to show the user in the scanning UI.
    n_candidates: int = int(os.environ.get("AAC_N_CANDIDATES", "4"))
    # How many turns of partner speech to condition on (prompts stay lean).
    context_turns: int = int(os.environ.get("AAC_CONTEXT_TURNS", "4"))

    profile_path: Path = ROOT / "data" / "profile.json"
    web_dir: Path = ROOT / "web"

    @property
    def provider_chain(self) -> list[str]:
        chain = [p.strip().lower() for p in self.provider_chain_raw.split(",") if p.strip()]
        return chain or ["constrained"]

    @property
    def primary_provider(self) -> str:
        for name in self.provider_chain:
            if name != "constrained":
                return name
        return "constrained"


settings = Settings()
