# OpenGaze Assist

**Live demo: https://aac-accelerator.vercel.app**

A full computer-access prototype for people with limited motor control and ASL users,
built around webcam eye gaze, blink/dwell selection, a large on-screen keyboard,
quick visual phrases, and the original LLM-accelerated communication system.

The browser version includes a safe simulated desktop. On macOS, a local-only
native bridge can move the real system pointer, click in any application, and
type the composed text into the focused application.

The communication component is designed for single-switch AAC users,
built from `aac-accelerator-design-doc.md` for the Frontier Cascadia Hackathon.

Someone using eye-gaze typing or single-switch scanning communicates at a few
words per minute. The bottleneck is not having nothing to say — it is the number
of switch selections each sentence costs. This prototype cuts that count by
letting the user select only the **first letter of each word** and reconstructing
the full sentence from that, conditioned on the conversation and on a personal
vocabulary file.

Measured on the same sentence, same interface, same scan speed:

> **12 selections vs 37 baseline — 3.1× fewer (32.9s → 9.7s)**

## Honest framing

This is a prototype of a **published research direction**, not a new idea, and
the pitch should say so (design doc §2):

- Google Research, *"Using large language models to accelerate communication for
  eye gaze typing users with ALS"*, Nature Communications, Nov 2024
- Google's SpeakFaster project
- *"Adapting Large Language Models for Character-based Augmentative and
  Alternative Communication"*, ACL Findings 2025

The claim worth making is that none of this is in shipped consumer AAC software
(Proloquo2Go, TD Snap use static word prediction) and it is not an OS
accessibility feature. The claim **not** to make is that it was invented here.

Not a certified assistive device, not a medical product, not voice cloning, not
gaze-point tracking, and not a replacement for a clinically fitted AAC system.

## Quick start

```bash
cd ~/aac-accelerator && ./run.sh
```

Then open http://localhost:8000. Press <kbd>Space</kbd> to start scanning;
<kbd>Space</kbd> is the switch.

For whole-computer control on macOS, use the native launcher from the project directory:

```bash
python3 native/start.py
```

It runs from the macOS menu bar—no browser is involved. Move the pointer with a
normal mouse or trackpad, then blink to click at its current position. Clicking
an editable field opens the large on-screen keyboard. Its oversized keys are
selected with pointer movement plus blink-clicks; physical typing is not
required. A click-through cyan crosshair shows the exact aim point in every app
and flashes yellow when a blink click fires. Press Escape once or choose
**Quit OpenGaze** from the menu-bar item to stop at any time.

On first launch, macOS may request Camera, Accessibility, and Input Monitoring
permission for Terminal. Grant them in System Settings, then restart the command.
If calibration reports that camera access is denied, enable OpenGaze or Terminal
under **System Settings → Privacy & Security → Camera**, quit with Escape, and
launch again.

The bridge listens on `127.0.0.1:8766` (port `8765` was retired to avoid a
collision with older bridge processes).

Grant Terminal Accessibility permission when macOS asks. The bridge binds only
to `127.0.0.1` and accepts the local app and production demo origins. Enter the
six-digit pairing code shown in the terminal when using the deployed site.
Without it,
all communication, keyboard, ASL-board, gaze, dwell, blink and speech features
still work inside the browser.

The intended system workflow is:

1. Start and arm the local bridge, then enable camera tracking.
2. Keep the OpenGaze page running; webcam gaze moves the real macOS pointer.
3. A deliberate blink posts a real system click at the pointer location.
4. After the click, the bridge reads the newly focused macOS accessibility
   element. If it is editable, it automatically opens the large floating
   keyboard—ordinary buttons and links do not open it.
5. Selecting **Type into field** closes the keyboard, restores the original
   application, and types into that field.

Press `Escape` three times within two seconds to disarm computer control.

## Accessible computer controls

- **Look to move:** MediaPipe iris landmarks estimate a coarse gaze point and
  smooth webcam jitter. Large targets are deliberate; this is not positioned as
  a clinical-grade eye tracker.
- **Blink or dwell to choose:** calibrated blink detection and adjustable dwell
  selection share the same target system. Mouse/touch remain available for setup.
- **Keyboard:** large QWERTY keys, word suggestions, text-to-speech, clipboard
  fallback, and native typing through the local bridge.
- **ASL board:** visual high-frequency needs and phrases can be selected and
  spoken for communication with non-signing partners.
- **Communicate:** preserves the original first-letter sentence expansion and
  single-switch row/column scan mode.

Copy `.env.example` to `.env` and set `OPENROUTER_API_KEY` for the cloud model.
With no key it still runs — it falls back to the offline generator.

> Note: blink detection needs a real browser tab for camera permission.

## How it works

```
[webcam] ─blink─┐
                ├─> [switch] ─> [row/column scanning UI] ─> [sparse tokens]
[Space key] ────┘                                                │
                                                                 v
                                        ┌────── candidate ladder ──────┐
                                        │ 1. personal phrase bank ~0ms │
                                        │ 2. LLM, hard-verified  ~950ms│
                                        │ 3. constrained beam    ~10ms │
                                        └──────────────┬───────────────┘
                                                       v
                                          [ranked candidates] ─> [confirm] ─> [TTS]
```

The user selects `i n s w`; the system returns *"I need some water"*.

### The generation problem, and what actually worked

A raw prompt does not solve this. Measured on this machine, share of generated
sentences that actually satisfied the initial-letter constraint:

| generator | valid | latency | notes |
|---|---|---|---|
| `llama3.2:3b` (local) | **8%** | ~1.0s | few-shot examples did not help |
| `qwen3.5:4b` (local) | **6%** | ~1.9s | |
| `google/gemma-3-12b-it` | **35%** | ~1.0s | |
| `google/gemini-2.5-flash` | **98%** | ~0.95s | the cloud path |
| constrained beam search | **100%** | ~10ms | valid by construction, offline |

Character-level constraints cut across tokenisation, so small models ignore them.
Three things follow, and they are the actual engineering content of this project:

1. **Every candidate is hard-verified** (`verify()` in `server/expander.py`).
   Word count must match the token count and word *N* must start with letter *N*.
   Failures are rejected, not shown. One **repair call** quotes the specific
   violations back to the model.
2. **The offline generator enforces the constraint structurally** rather than
   asking a model to comply — bigram-scored beam search over a letter-bucketed
   lexicon (`server/constrained.py`). It cannot emit an invalid candidate, runs
   in ~10ms, and needs no network.
3. **Ranking is separate from generation.** Survivors are scored on constraint
   fit, personal-vocabulary overlap, overlap with what the partner just said,
   brevity, and source, then deduped.

### The fallback ladder

The phrase bank answers instantly, the cloud model adds context-awareness, and
the offline generator guarantees the list is never empty. A dead venue network
degrades candidate *quality*, never availability — verified by pointing the app
at an invalid API key: 401 from the cloud, four valid candidates still returned.

### Blink switch

Blink-as-binary-switch (design doc §5), deliberately **not** gaze-point tracking.
MediaPipe Face Mesh landmarks → eye aspect ratio → a state machine that fires on
the closed→open transition when the closed phase lands inside a plausible window.
That rejects camera noise and long eye-rests, and a refractory period rejects
double-fires.

**Calibration is load-bearing, not a nicety.** An operator whose open-eye EAR is
0.18 reads as permanently closed under the 0.21 default and never fires at all —
there is a test for exactly this. Hit **Calibrate**, keep eyes open for 3s, and
the threshold is set from the interquartile mean of the samples so a stray blink
during calibration cannot skew it. Do this on the actual demo operator, under
actual venue lighting (design doc §11).

The MediaPipe runtime and model are **vendored** into `web/vendor/` (~15MB), so
blink detection has no CDN dependency.

The keyboard switch always works, in parallel, and is never disabled.

## Demo script (design doc §9)

1. **Baseline first.** Switch to **Baseline** and spell one sentence character by
   character. Let the room watch the selection counter climb. ~37 selections.
2. **Accelerated.** Same sentence, **Accelerated** mode: select 4 letters, choose
   GENERATE, confirm the candidate. ~12 selections.
3. **Quote the number out loud.** The Trial log panel computes it for you:
   *"12 selections instead of 37 — 3.1× fewer."*
4. Add conversation context first (the chips in the sidebar) so the candidates
   are visibly reacting to what was just said, not just autocompleting.
5. If blink is reliable in the room, do it hands-free. If not, the keyboard
   switch proves the same claim — say so rather than fighting the camera.

## Layout

```
server/
  config.py       settings, provider chain
  providers.py    ollama / openrouter / offline stub adapters
  expander.py     prompt, parsing, VERIFICATION, repair, ranking  <- core
  constrained.py  offline bigram beam search, valid by construction
  profile.py      personal vocabulary store
  main.py         FastAPI app + endpoints
public/           served straight from the CDN on Vercel
  app.js          scanning engine, modes, metrics, TTS
  blink-core.js   pure blink logic (EAR, state machine, calibration)
  blink.js        camera + MediaPipe wiring
  vendor/         vendored MediaPipe runtime + model (offline)
api/
  index.py        Vercel ASGI entry point
data/
  profile.json    personal vocabulary
  corpus.txt      582 utterances behind the offline generator
```

## Tests

```bash
PYTHONPATH=. ./.venv/bin/python -m pytest tests/ -q   # 31 tests
node tests/test_blink_core.mjs                        # 18 tests
```

## Deployment

Live at **https://aac-accelerator.vercel.app**.

```bash
npx vercel deploy --prod
```

Deployed on Vercel. `public/` is served from the CDN and `api/index.py` runs the
FastAPI app as a serverless function — the vendored MediaPipe wasm never touches
the lambda.

Set `OPENROUTER_API_KEY` in the Vercel project's environment variables. Without
it the deploy still works, falling back to the offline generator.

Two differences from running locally:

- **Ollama is unreachable** from a serverless function, so the chain is
  `openrouter -> constrained`. The offline generator behaves identically.
- **The filesystem is read-only.** Vocabulary edits apply to the running
  instance but are not persisted, and the trial log lives in the browser's
  `localStorage` rather than on the server — which is why the baseline-vs-
  accelerated number survives instance churn.

Deploying also gets you HTTPS, which browsers require for camera access: the
blink switch works on the deployed URL but not over plain `http://` on a LAN
address.

Two routing details worth knowing if you fork this:

- Vercel sends `/` to the Python function rather than to `public/index.html`,
  so the app redirects the root to the CDN copy. `outputDirectory` did not
  change this; the redirect is what works.
- `/api/health` reports `static_bundled`, `corpus_available` and
  `profile_persistent`, which is how the above was diagnosed rather than guessed.

> The deployed `/api/candidates` endpoint is unauthenticated and spends the
> configured OpenRouter key. Set a spend limit on the key if the URL is shared.

The blink tests cover what a webcam cannot be made to do on demand: noisy
frames, long eye-rests, double-triggers, and the narrow-eyed-operator case that
fails without calibration.

## Known risks

- **Blink reliability under venue lighting** — mitigated by calibration and the
  always-on keyboard switch. Test on the actual operator beforehand.
- **Generation latency** — mitigated by the instant phrase bank, a single lean
  call, and the ~10ms offline path. Pre-warm runs at startup.
- **Overclaiming** — see *Honest framing*. Frame as a prototype of published work.
- **Glasses glare** — light off-axis, and calibrate on the person who will demo.
