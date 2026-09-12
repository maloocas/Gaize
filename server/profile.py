"""Personal vocabulary / context file (design doc s7, build priority 3).

Small, human-editable JSON. Names, recurring phrases and current topics are what
make candidates plausible for one specific person rather than generic English.
"""
from __future__ import annotations

import json
from copy import deepcopy

from .config import settings

# Serverless filesystems are read-only outside /tmp, and each instance is
# short-lived. When the file cannot be written we keep the edit in memory so the
# running instance still behaves correctly, and tell the caller it will not
# survive. Losing a vocabulary edit is acceptable; a 500 mid-demo is not.
_OVERRIDE: dict | None = None
_PERSISTENT = True

DEFAULT_PROFILE: dict = {
    "name": "",
    "about": "",
    "people": [],
    "topics": [],
    "phrases": [],
}


def is_persistent() -> bool:
    """False once a save has fallen back to memory (read-only filesystem)."""
    return _PERSISTENT


def load() -> dict:
    if _OVERRIDE is not None:
        return deepcopy(_OVERRIDE)
    path = settings.profile_path
    if not path.exists():
        return deepcopy(DEFAULT_PROFILE)
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return deepcopy(DEFAULT_PROFILE)
    merged = deepcopy(DEFAULT_PROFILE)
    if isinstance(data, dict):
        for key in merged:
            if key in data and data[key] is not None:
                merged[key] = data[key]
    return merged


def save(data: dict) -> dict:
    merged = deepcopy(DEFAULT_PROFILE)
    for key in merged:
        if key in data and data[key] is not None:
            value = data[key]
            if isinstance(merged[key], list) and isinstance(value, str):
                value = [v.strip() for v in value.split("\n") if v.strip()]
            merged[key] = value
    global _OVERRIDE, _PERSISTENT
    try:
        settings.profile_path.parent.mkdir(parents=True, exist_ok=True)
        settings.profile_path.write_text(json.dumps(merged, indent=2) + "\n")
        _OVERRIDE = None
    except OSError:
        _OVERRIDE = deepcopy(merged)
        _PERSISTENT = False
    return merged
