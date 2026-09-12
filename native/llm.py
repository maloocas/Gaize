"""Turn a swiped sentence's candidate lattice into text with an LLM (port of Gaize llm.js).

The key comes from OPENAI_API_KEY in the environment or the repo's .env and is
only ever placed in the request header. Spend guards: the model and output cap
are fixed here, requests are size-capped, and each process stops after
MAX_CALLS calls. Any failure falls back to the top candidate per slot.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import urllib.error
import urllib.request

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
ENDPOINT = "https://api.openai.com/v1/responses"
MODEL = "gpt-5.6-luna"
EFFORT = "none"
TOP_K = 5
MAX_OUTPUT_TOKENS = 200
MAX_INPUT_BYTES = 8000
MAX_CALLS = int(os.environ.get("MAX_CALLS", 300))
TIMEOUT = 12

INSTRUCTIONS = """You decode sentences typed on a gaze swipe keyboard.
Each slot is one swiped word. Candidates are ranked best-first by how well the word's shape matches the swipe,
so prefer higher-ranked candidates. Pick one word per slot to form the most likely sentence given the prior text.
Usually the answer is among the candidates, but if none fits the context, you may use a similar-looking word that is not listed.
A slot's candidates are mutually exclusive guesses for a single typed word. Once you pick one, the others were never typed:
do not use them elsewhere in the sentence and do not let them shape its meaning. Decide each slot, then build the sentence
only from the chosen words. You may insert a word no slot accounts for only if the sentence clearly needs it (e.g. a
skipped "a" or "to"), and never because it appeared as a rejected candidate.
Add capitalization, apostrophes and punctuation as appropriate.
Reply in this format: first one line per slot with the chosen word, then the sentence on a final line.
1. <word>
2. <word>
...
Sentence: <sentence>"""

_calls = 0
_lock = threading.Lock()


def _api_key():
    key = os.environ.get("OPENAI_API_KEY", "")
    if key or not ENV_FILE.exists():
        return key
    for line in ENV_FILE.read_text().splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and name.strip() == "OPENAI_API_KEY":
            return value.strip().strip("\"'")
    return ""


def build_prompt(slots, prior_text=""):
    lines = [f"{i + 1}. " + " ".join(c["word"] for c in slot[:TOP_K])
             for i, slot in enumerate(slots)]
    return f"Prior text: {prior_text or '(none)'}\n\nSlots:\n" + "\n".join(lines)


def parse_reply(data):
    text = "".join(c.get("text", "") for o in data.get("output", [])
                   if o.get("type") == "message"
                   for c in o.get("content", []) if c.get("type") == "output_text")
    marker = text.rfind("Sentence:")
    if marker < 0:
        raise ValueError(f'no "Sentence:" line in reply: {text[:200]}')
    return text[marker + len("Sentence:"):].strip()


def fallback(slots):
    return " ".join(slot[0]["word"] for slot in slots if slot)


def decode_sentence(slots, prior_text=""):
    """Returns (sentence, error). error is None when the LLM answered."""
    global _calls
    if not slots:
        return "", None
    key = _api_key()
    if not key:
        return fallback(slots), "no OPENAI_API_KEY"
    body = json.dumps({
        "model": MODEL, "reasoning": {"effort": EFFORT},
        "max_output_tokens": MAX_OUTPUT_TOKENS, "stream": False,
        "instructions": INSTRUCTIONS, "input": build_prompt(slots, prior_text),
    }).encode()
    if len(body) > MAX_INPUT_BYTES:
        return fallback(slots), "request too large"
    with _lock:
        if _calls >= MAX_CALLS:
            return fallback(slots), "call limit reached; restart OpenGaze"
        _calls += 1
    request = urllib.request.Request(ENDPOINT, data=body, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return parse_reply(json.loads(response.read())), None
    except urllib.error.HTTPError as error:
        return fallback(slots), f"LLM HTTP {error.code}"
    except Exception as error:  # network, timeout, bad reply
        return fallback(slots), f"LLM error: {error}"
