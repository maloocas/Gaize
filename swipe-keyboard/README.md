# Swipe keyboard

A swipe-to-type keyboard, like the one on iOS, built to take gaze input later. For now the mouse stands in for gaze.

## Run

```bash
cd swipe-keyboard
cp .env.example .env   # then put your OpenAI key in .env
python3 server.py
```

Open http://localhost:8000 and trace words with the trackpad or mouse. **Tap Space** once to start, then tap it at the end of each word. A tap stands in for a blink. Each tap ends the current word and starts the next one right away. Backspace deletes the last word. **Enter** ends the sentence and sends it to the LLM, and the decoded text appears at the top of the page.

## LLM decoding

`llm.js` has no DOM code, so it ports directly to a native app. When a sentence ends, `decodeSentence(kb.getSlots(), { priorText })` sends every word slot to `gpt-5.6-luna` with reasoning effort `none` through the Responses API. For each slot it sends the top 5 candidates in rank order, with no scores and no path. The model lists its pick for each slot, then writes the sentence. Only the sentence is shown. It can use a similar-looking word that isn't listed when none of the listed words fit. `server.py` serves the page and forwards `POST /llm` to OpenAI, so the API key never reaches the browser.

A tap calls `kb.boundary()`. Each word is then decoded from several start delays set by the `offsets` option (default 150, 200, 275, 350 and 450 ms, which match p5/p25/p50/p75/p90 of 47 gaps measured on a trackpad), keeping the top `perOffset` candidates from each. The results are merged into one list sorted by score. Use the gap measurements to pick better offsets. **Backspace** deletes the last word. Click a suggestion to replace the last word.

## How it works

`decoder.js` is a SHARK2-style decoder, based on Kristensson & Zhai (UIST 2004). It works in these steps:

1. It groups the path's jittery points into fixations. A long fixation in the middle of the path is a pause, and the word must contain a letter near each pause.
2. It keeps only the words whose first and last letters are within 1.5 key widths of where the path starts and ends. This tolerance matches the accuracy we expect from gaze.
3. It scores each remaining word by comparing the path with the word's ideal path through the key centers, by both shape and position.
4. It ranks the words by combining that score with how common each word is in `words.txt`.

`words.txt` holds the 150k most common English words with their frequencies, exported from [wordfreq](https://github.com/rspeer/wordfreq). wordfreq combines Wikipedia, Reddit, Twitter, Google Books, subtitles, news and web text, with data up to about 2021. Each count is the word's frequency per billion words. The list includes contractions such as "don't" and "I'm". The keyboard has no apostrophe key, so you swipe "dont" to get "don't". To regenerate the file, run `pip install wordfreq`, take `top_n_list('en', 250000)`, keep the words that match `^[a-z]+('[a-z]+)?$`, and cut the list at 150k. Past that point the list is mostly rare names and typos, and they cost memory and decode time.

## Connecting gaze

The decoder expects positions in viewport coordinates.

```js
const kb = createSwipeKeyboard(el, {
  ...(await loadWords('./words.txt')),
  // Called once per word: candidates = [{ word, p, offset }, ...], sorted best first,
  // p sums to 1, offset = the start delay (ms) that gave the word its best score.
  // lattice = every word's candidate list so far. Hand these to the LLM.
  onWord: (candidates, lattice) => {},
});
kb.feed(x, y); // send every gaze sample
kb.boundary(); // call on each blink: ends the current word and starts the next
kb.start();    // or control recording directly
kb.end();
```
