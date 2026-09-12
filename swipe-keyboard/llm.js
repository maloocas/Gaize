// Turns a finished sentence's lattice into text with an LLM. Kept free of DOM code so the
// prompt and parsing port directly to a native app; only `endpoint` is web-demo specific.

const INSTRUCTIONS = `You decode sentences typed on a gaze swipe keyboard.
Each slot is one swiped word. Candidates are ranked best-first by how well the word's shape matches the swipe path.
"path" lists the keys the swipe passed near, in order, and is noisy (roughly 1.5 keys of error; letters can be missing or extra).
Pick one word per slot to form the most likely sentence given the prior text. Usually the answer is among the candidates,
but if none fits the context, you may use a word that is not listed as long as it is consistent with the path.
Keep one word per slot. Add capitalization, apostrophes and punctuation as appropriate.
Reply with only the sentence.`;

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
  return data.output
    .filter((o) => o.type === 'message')
    .flatMap((o) => o.content)
    .filter((c) => c.type === 'output_text')
    .map((c) => c.text)
    .join('')
    .trim();
}
