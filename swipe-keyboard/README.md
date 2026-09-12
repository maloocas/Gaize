# Swipe keyboard

A swipe-to-type keyboard, like the one on iOS, built to take gaze input later. For now the mouse stands in for gaze.

## Run

```bash
cd swipe-keyboard
python3 -m http.server 8000
```

Open http://localhost:8000. **Space** stands in for a blink. Each press ends the current word and starts recording the next one. Your first press only starts recording.

We can't know how long the eyes take to reach the next word's first letter, so each word is decoded 5 times. Each decode starts the path at a different delay after the boundary: 0, 0.2, 0.4, 0.6 and 0.8 s. Each decode keeps its top 3 candidates, which gives up to 15 per word. The page shows them grouped by start delay. **Backspace** deletes the last word. Click a suggestion to replace the last word.

## How it works

`decoder.js` is a SHARK2-style decoder, based on Kristensson & Zhai (UIST 2004). It works in these steps:

1. It groups the path's jittery points into fixations. A long fixation in the middle of the path is a pause, and the word must contain a letter near each pause.
2. It keeps only the words whose first and last letters are within 1.5 key widths of where the path starts and ends. This tolerance matches the accuracy we expect from gaze.
3. It scores each remaining word by comparing the path with the word's ideal path through the key centers, by both shape and position.
4. It ranks the words by combining that score with how common each word is in `words.txt`.

`words.txt` holds the 50k most common English words with their frequency counts. It comes from [hermitdave/FrequencyWords](https://github.com/hermitdave/FrequencyWords) and is built from OpenSubtitles 2018 data.

## Connecting gaze

The decoder expects positions in viewport coordinates.

```js
const kb = createSwipeKeyboard(el, {
  ...(await loadWords('./words.txt')),
  // Called once per word: candidates = [{ word, p, offset }, ...], top 3 for each
  // start delay (offset in ms); p sums to 1 within each offset.
  // lattice = every word's candidate list so far. Hand these to the LLM.
  onWord: (candidates, lattice) => {},
});
kb.feed(x, y); // send every gaze sample
kb.boundary(); // call on each blink: ends the current word and starts the next
kb.start();    // or control recording directly
kb.end();
```
