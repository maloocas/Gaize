"""FastAPI app: serves the scanning UI and the candidate-generation endpoint."""
from __future__ import annotations

import json
import tempfile
import time
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import profile as profile_store
from .config import settings
from .constrained import load_model as load_lm
from .expander import expand
from .providers import get_provider

app = FastAPI(title="LLM-Accelerated AAC", version="0.1.0")

@lru_cache(maxsize=1)
def session_log() -> Path | None:
    """Pick a writable location for the trial log, or None if there isn't one.

    On Vercel the project directory is read-only, so this lands in the instance's
    temp dir. That is per-instance and short-lived, which is why the browser also
    keeps its own copy - the demo's headline number must not depend on it."""
    candidates = [settings.profile_path.parent / "sessions.jsonl",
                  Path(tempfile.gettempdir()) / "aac-sessions.jsonl"]
    for path in candidates:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a"):
                pass
            return path
        except OSError:
            continue
    return None


class CandidateRequest(BaseModel):
    tokens: list[str] = Field(default_factory=list)
    partner_turns: list[str] = Field(default_factory=list)
    provider: str | None = None
    n: int | None = None


class TrialRecord(BaseModel):
    mode: str                      # "baseline" | "accelerated"
    target: str = ""
    spoken: str = ""
    selections: int = 0
    elapsed_ms: int = 0
    input_source: str = "key"      # "key" | "blink"


@app.on_event("startup")
async def prewarm() -> None:
    """Warm the candidate ladder before the demo starts (doc s7, s11).

    Building the offline language model and loading a local model into RAM both
    cost seconds on first use. Paying that here means the first live keystroke is
    already fast.
    """
    # Offline floor first - this must always be ready.
    started = time.perf_counter()
    load_lm()
    lm_ms = int((time.perf_counter() - started) * 1000)
    print(f"[warm] offline constrained generator ready in {lm_ms}ms")
    print(f"[warm] provider chain: {' -> '.join(settings.provider_chain)}")

    for name in settings.provider_chain:
        if name != "ollama":
            continue
        provider = get_provider(name)
        started = time.perf_counter()
        result = await provider.warm()
        took = int((time.perf_counter() - started) * 1000)
        if result.error:
            print(f"[warm] {name}/{provider.model} failed in {took}ms: {result.error}")
        else:
            print(f"[warm] {name}/{provider.model} ready in {took}ms")


@app.get("/api/health")
async def health() -> dict:
    """Report the chain state. The offline generator is always available, so the
    app is never unusable - "not reachable" only means candidates will be
    generic rather than context-aware."""
    primary = settings.primary_provider
    reachable, detail = True, "offline generator ready"
    model = "offline"
    if primary == "openrouter":
        model = settings.openrouter_model
        if not settings.openrouter_key:
            reachable, detail = False, "OPENROUTER_API_KEY is not set - offline candidates only"
        else:
            detail = "cloud model configured"
    elif primary == "ollama":
        model = settings.ollama_model
        probe = await get_provider("ollama").complete("Reply with: ok", "ok")
        reachable = probe.error is None
        detail = probe.error or f"warm round-trip {probe.latency_ms}ms"
    return {
        "provider": primary,
        "model": model,
        "chain": settings.provider_chain,
        "reachable": reachable,
        "detail": detail,
        "n_candidates": settings.n_candidates,
    }


@app.post("/api/candidates")
async def candidates(req: CandidateRequest) -> JSONResponse:
    result = await expand(
        tokens=req.tokens,
        partner_turns=req.partner_turns,
        profile=profile_store.load(),
        provider_name=req.provider,
        n=req.n,
    )
    return JSONResponse(result.as_dict())


@app.get("/api/profile")
async def get_profile() -> dict:
    return profile_store.load()


@app.put("/api/profile")
async def put_profile(data: dict) -> dict:
    saved = profile_store.save(data)
    return {**saved, "_persistent": profile_store.is_persistent()}


@app.post("/api/trial")
async def log_trial(record: TrialRecord) -> dict:
    """Persist baseline vs accelerated trials so the demo can quote real numbers."""
    payload = record.model_dump()
    payload["ts"] = time.time()
    path = session_log()
    if path is None:
        return {"logged": False, "reason": "no writable location"}
    try:
        with path.open("a") as handle:
            handle.write(json.dumps(payload) + "\n")
    except OSError as exc:
        return {"logged": False, "reason": str(exc)}
    return {"logged": True}


@app.get("/api/trials")
async def list_trials() -> dict:
    path = session_log()
    if path is None or not path.exists():
        return {"trials": []}
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return {"trials": rows[-100:]}


if settings.web_dir.exists():
    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(settings.web_dir / "index.html")

    app.mount("/", StaticFiles(directory=str(settings.web_dir), html=True), name="web")
