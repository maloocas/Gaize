# Gaize

Eye-tracking control built to teach you an interface, not just operate one you
already know.

## The problem

Eye-tracking tools already exist that let someone with limited hand mobility
select things on screen just by looking. None of them help you *learn* a new
interface. If you're not sure what a button does and every action takes real
effort, you avoid exploring — so you stay stuck using only what you already
know.

## How it works

- **Hover with your gaze** over a button or icon.
- Instead of clicking immediately, you **hear a short spoken explanation** of
  what it actually does — no need to read on-screen text.
- If it's what you wanted, **look again / hold your gaze a bit longer** to
  confirm and actually perform the action.

You get to hear what something does before committing to it — entirely
hands-free, and without competing for visual attention between reading and
controlling your gaze.

### Why audio, not just a visual preview

Not everyone using eye tracking has strong reading ability, or wants to read
small on-screen text while also trying to control their gaze precisely.
Hearing the explanation is faster, more natural, and doesn't fight the
interface for visual attention.

## The learning loop (website + app)

Gaize is two connected pieces:

1. **The app** — real-time gaze tracking (camera-based, via MediaPipe) drives
   selection. Hover → spoken explanation. Confirm gaze → action performed.
2. **The website** — goal-driven learning on top of the app:
   - Pick a **goal** (e.g. "learn how to export a photo," "send an email").
     The site breaks it into steps and tells you what to do next in the app.
   - Optionally take a **quiz** to demonstrate what you've learned. The quiz
     gives feedback at the end — what you got right, what to review.
   - Or take on a **scenario**: the site hands you a task, tracks your actual
     actions in the app, and verifies you completed it correctly — live
     task-verification, not just self-reported answers.

The loop: the website sets a goal or scenario → you carry it out hands-free in
the app (getting spoken explanations along the way) → the website observes
your actions and/or quizzes you → feedback tells you what to work on next.

## Hackathon demo scope

- One small mock app with a handful of buttons.
- Real gaze tracking through the camera (MediaPipe).
- Hover triggers a short pre-written audio clip explaining that button.
- Looking again confirms the action.

## Why this, now

Eye-tracking control is a mature space, but nobody's built the missing
"learn as you go" layer — and now that layer speaks to you instead of just
showing you a preview.
