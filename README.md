# Gaize

**Full computer control with your eyes.** Look to move the pointer, blink to
click, and type whole sentences without touching anything.

Built for people with limited motor control — ALS, locked-in syndrome, spinal
injury — who can move their eyes but not a mouse.

```bash
python3 native/start.py
```

Look at the dots to calibrate (17 of them, about 30 seconds), and the pointer
starts following your eyes. Escape three times to quit.

---

## What you can do with it

| | How |
|---|---|
| Move the pointer | Look at it. Gaze snaps onto real buttons within 135pt, and zooms to separate two that are close together. |
| Left click | Wink left |
| Right click | Wink right, or hold both eyes shut for about a second |
| Select | A hard blink |
| Drag | Double blink to grab, double blink again to drop |
| Scroll | Look at the scroll strips at the screen edge |
| Type | Blink on a text field and a large on-screen keyboard opens, typing into whatever app you came from |
| Type *faster* | Pick the first letter of each word — `i n s w` becomes "I need some water" |
| Hear what a control does | Gaze at it and the companion speaks what it is, before you commit to pressing it |

The last one is the idea the project started from: eye-tracking tools let you
*operate* an interface you already know, but none of them help you *learn* one.
If every action takes real effort you stop exploring, so you stay stuck with the
parts you already understand. Hearing what a button does before pressing it is
what makes exploring cheap again.

## The pieces

| Path | What it is |
|---|---|
| `native/` | The eye-control system. Gaze engine, calibration, blink/wink gestures, target snapping, the on-screen keyboard, autocomplete. This is what `start.py` runs. |
| `companion/` | Swift menu-bar app: reads what you're looking at through the accessibility tree and speaks it aloud, plus voice commands and guided lessons. |
| `website/` | The lesson site the companion talks to. |
| `swipe-keyboard/` | Web swipe keyboard with LLM sentence decoding. |
| `server/`, `api/`, `public/` | The sentence accelerator as a web app, also deployed to Vercel. |
| `data/`, `scripts/` | Conversational corpus, personal vocabulary, corpus builder. |
| `tests/` | 129 Python + 18 JavaScript tests. |

### How the sentence accelerator works

Selecting letters one at a time is brutally slow — measured here, one sentence
cost **37 selections and 32.9 seconds**. Picking only the first letter of each
word and expanding it cost **12 selections and 9.7 seconds** for the same
sentence: **3.1× fewer**.

Getting that right needed more than prompting. Measured on this machine, the
share of generated sentences that actually satisfied the first-letter
constraint:

| Generator | Valid | Latency |
|---|---|---|
| `llama3.2:3b` (local) | 8% | ~1.0s |
| `qwen3.5:4b` (local) | 6% | ~1.9s |
| `gemma-3-12b` | 35% | ~1.0s |
| `gemini-2.5-flash` | 98% | ~0.95s |
| constrained beam search | **100%** | **~10ms** |

So every candidate is hard-verified against the constraint and rejected if it
fails, one repair call quotes the specific violations back to the model, and an
offline generator enforces the constraint structurally — valid by construction,
no network. A dead venue network degrades candidate *quality*, never
availability.

## Setup

Needs macOS, a webcam, and Python 3.12.

```bash
python3 native/start.py     # installs dependencies on first run, then launches
```

macOS will ask for **Camera**, **Accessibility** and **Input Monitoring**. All
three are required: the camera to see your eyes, accessibility to move the
pointer and read what's on screen, input monitoring for the panic key.

Other pieces run on their own:

```bash
./run.sh                             # sentence accelerator web app, localhost:8000
cd swipe-keyboard && python3 server.py   # web swipe keyboard
cd companion && ./make-app.sh            # build the Swift companion
```

## Tests

```bash
.native-venv/bin/python -m pytest tests/ -q   # 129 tests
node tests/test_blink_core.mjs                # 18 tests
```

## Honest framing

The sentence accelerator is a working prototype of a **published research
direction**, not a new idea:

- Google Research, *"Using large language models to accelerate communication for
  eye gaze typing users with ALS"*, Nature Communications, Nov 2024
- Google's SpeakFaster project
- *"Adapting Large Language Models for Character-based Augmentative and
  Alternative Communication"*, ACL Findings 2025

None of this is in shipped consumer AAC software (Proloquo2Go and TD Snap use
static word prediction) and it is not an OS accessibility feature. That is the
claim worth making. The claim *not* to make is that it was invented here.

This is not a certified assistive device or a medical product, and not a
replacement for a clinically fitted AAC system.

## Known state

Three things are true and worth knowing before relying on this:

- **The gaze engine feeds `native/` only.** `companion/` still uses a mock
  tracker that follows the mouse cursor, and `swipe-keyboard/` takes gaze points
  from an unspecified external `kb.feed(x, y)`. Both are documented seams
  expecting Quartz top-left points, which is exactly what `gaze_engine.py`
  emits — but the wiring is not done.
- **Some logic exists twice**: two SHARK2 swipe decoders (`decoder.js` and
  `swipe_decoder.py`) and two LLM sentence decoders (`swipe-keyboard/llm.js`
  plus `server.py`, and `server/expander.py` plus `native/llm.py`).
- **Webcam gaze is coarse.** Target snapping and large controls do most of the
  work; treat it as pointing, not as a clinical eye tracker.

## Further reading

- [README-opengaze-assist.md](README-opengaze-assist.md) — full documentation of
  the eye-control system and the sentence accelerator: gestures, setup, measured
  results, deployment and known risks.
- [README-gaize-original.md](README-gaize-original.md) — the original Gaize
  README as written, explaining the learn-the-interface idea and why the
  explanation is spoken rather than shown. Kept intact; this page summarises it
  but does not replace it.
