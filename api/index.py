"""Vercel serverless entry point.

Vercel's Python runtime serves an ASGI app exported as `app`. Static assets
(public/) are served straight from Vercel's CDN and never reach this function,
which matters: the vendored MediaPipe wasm is ~12MB and has no business being
bundled into a lambda.

Locally nothing uses this file - `./run.sh` runs uvicorn against server.main.
"""
import sys
from pathlib import Path

# The function's working directory is not guaranteed to be the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.main import app  # noqa: E402

__all__ = ["app"]
