// Turns a finished sentence's lattice into text with an LLM. Kept free of DOM code so the
// prompt and parsing port directly to a native app; only `endpoint` is web-demo specific.

const INSTRUCTIONS = `You decode sentences typed on a gaze swipe keyboard.
Each slot is one swiped word. Candidates are ranked best-first by how well the word's shape matches the swipe path.
"path" lists every key the swipe crossed, in order, including keys it merely passed over between letters, so most path
letters are not in the word (e.g. "to" swiped from t to o gives "t r t y u i o"). It is also noisy (roughly 1.5 keys of error).
Use it only as a weak hint; the candidate ranking already accounts for the path, so prefer higher-ranked candidates.
Pick one word per slot to form the most likely sentence given the prior text. Usually the answer is among the candidates,
but if none fits the context, you may use a word that is not listed as long as it is consistent with the path.
A slot's candidates are mutually exclusive guesses for a single typed word. Once you pick one, the others were never typed:
do not use them elsewhere in the sentence and do not let them shape its meaning. Decide each slot, then build the sentence
only from the chosen words. You may insert a word no slot accounts for only if the sentence clearly needs it (e.g. a
skipped "a" or "to"), and never because it appeared as a rejected candidate.
Add capitalization, apostrophes and punctuation as appropriate.
Reply in this format: first one line per slot with the chosen word, then the sentence on a final line.
1. <word>
2. <word>
...
Sentence: <sentence>`;

export function buildPrompt(slots, priorText = '') {
  const lines = slots.map((s, i) => `${i + 1}. ${s.candidates.map((c) => c.word).join(' ')} | path: ${s.trace}`);
  return `Prior text: ${priorText || '(none)'}\n\nSlots:\n${lines.join('\n')}`;
}

// slots: [{candidates: [{word}], trace: 'h e l o'}] -> sentence string
export async function decodeSentence(slots, {
  priorText = '',
  topK = 8,
  model = 'gpt-5.6-luna',
  effort = 'none',
  endpoint = '/llm',
} = {}) {
  const trimmed = slots.map((s) => ({ ...s, candidates: s.candidates.slice(0, topK) }));
  const res = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model,
      reasoning: { effort },
      instructions: INSTRUCTIONS,
      input: buildPrompt(trimmed, priorText),
    }),
  });
  if (!res.ok) throw new Error(`${res.status} ${(await res.text()).slice(0, 200)}`);
  const data = await res.json();
  const text = data.output
    .filter((o) => o.type === 'message')
    .flatMap((o) => o.content)
    .filter((c) => c.type === 'output_text')
    .map((c) => c.text)
    .join('');
  // The per-slot choices come first so the model commits to each slot before writing the sentence.
  const m = text.match(/Sentence:\s*(.*)\s*$/s);
  if (!m) throw new Error(`no "Sentence:" line in reply: ${text.slice(0, 200)}`);
  return m[1].trim();
}
