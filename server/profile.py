"""Personal vocabulary / context file (design doc s7, build priority 3).

Small, human-editable JSON. Names, recurring phrases and current topics are what
make candidates plausible for one specific person rather than generic English.
"""
from __future__ import annotations

import json
from copy import deepcopy

from .config import settings

DEFAULT_PROFILE: dict = {
    "name": "",
    "about": "",
    "people": [],
    "topics": [],
    "phrases": [],
}


def load() -> dict:
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
    settings.profile_path.parent.mkdir(parents=True, exist_ok=True)
    settings.profile_path.write_text(json.dumps(merged, indent=2) + "\n")
    return merged
