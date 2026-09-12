// Swipe keyboard. Pointer/gaze positions go in via kb.feed(x, y); the path is
// recorded between word boundaries and decoded into ranked candidate words.
// Picking the final word is left to a downstream model (e.g. an LLM with context).
//
// We don't know how long the eyes take to reach the next word's first letter after a
// boundary, so each word is decoded several times, with the path starting at each offset.

import { createDecoder } from './decoder.js';

const ROWS = ['qwertyuiop', 'asdfghjkl', 'zxcvbnm'];

export function createSwipeKeyboard(root, {
  words,
  freqs,
  accuracy = 1.5,
  // ms after the boundary: ≈ p5/p25/p50/p75/p90 of measured inter-word gaps (n=47, trackpad)
  offsets = [150, 200, 275, 350, 450],
  perOffset = 3,
  traceOffset = 275, // start of the key trace sent to the LLM (median gap)
  temperature = 0.5,
  onWord,
}) {
  const decoder = createDecoder(words, freqs);

  root.classList.add('swipe-kb');
  root.innerHTML = `
    <div class="swipe-output"></div>
    <div class="swipe-keys">
      ${ROWS.map((r) => `<div class="swipe-row">${[...r].map((c) => `<div class="swipe-key" data-key="${c}">${c}</div>`).join('')}</div>`).join('')}
    </div>
    <canvas class="swipe-trace"></canvas>`;

  const output = root.querySelector('.swipe-output');
  const canvas = root.querySelector('.swipe-trace');
  const ctx = canvas.getContext('2d');

  let lattice = []; // one candidate list per word slot
  let traces = []; // per slot: keys the path passed near, e.g. 'h e l o'
  let centers = {};
  let path = null;
  let t0 = 0;
  let last = null;

  function layout() {
    centers = {};
    let w = 0;
    for (const el of root.querySelectorAll('[data-key]')) {
      const r = el.getBoundingClientRect();
      centers[el.dataset.key] = { x: r.left + r.width / 2, y: r.top + r.height / 2 };
      w = r.width;
    }
    decoder.setLayout(centers, w);
    canvas.width = innerWidth;
    canvas.height = innerHeight;
  }
  layout();
  addEventListener('resize', layout);

  function render() {
    output.innerHTML = lattice
      .map((c) => `<div class="swipe-slot">${c
        .map((x) => `<span style="opacity:${0.35 + 0.65 * x.p}">${x.word} ${x.p.toFixed(2)}</span>`)
        .join('')}</div>`)
      .join('');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!path?.length) return;
    ctx.strokeStyle = 'rgba(120, 200, 255, 0.8)';
    ctx.lineWidth = 4;
    ctx.beginPath();
    path.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
    ctx.stroke();
  }

  function decodeFrom(offset) {
    const cutoff = t0 + offset;
    const i = path.findIndex((p) => p.t >= cutoff);
    if (i < 0) return [];
    const sub = path.slice(Math.max(0, i - 1)); // include the position at the cutoff
    return decoder.decode(sub, { radius: accuracy, limit: perOffset }).map((r) => ({ ...r, offset }));
  }

  // Nearest key of each sample after traceOffset, with repeats collapsed.
  function trace() {
    const keys = [];
    for (const p of path) {
      if (p.t < t0 + traceOffset) continue;
      let best = null, bd = Infinity;
      for (const [c, k] of Object.entries(centers)) {
        const d = Math.hypot(k.x - p.x, k.y - p.y);
        if (d < bd) { bd = d; best = c; }
      }
      if (best !== keys[keys.length - 1]) keys.push(best);
    }
    return keys.join(' ');
  }

  // Merges all offsets' candidates, keeping each word's best (lowest-cost) offset,
  // then sorts globally and turns costs into probabilities.
  function merge(results) {
    const best = new Map();
    for (const r of results) if (!best.has(r.word) || r.cost < best.get(r.word).cost) best.set(r.word, r);
    const sorted = [...best.values()].sort((a, b) => a.cost - b.cost);
    const exps = sorted.map((r) => Math.exp(-(r.cost - sorted[0].cost) / temperature));
    const sum = exps.reduce((a, b) => a + b, 0);
    return sorted.map((r, i) => ({ word: r.word, p: exps[i] / sum, offset: r.offset }));
  }

  return {
    feed(x, y, t = performance.now()) {
      last = { x, y, t };
      if (path) {
        path.push(last);
        render();
      }
    },
    start(t = performance.now()) {
      t0 = t;
      path = last ? [{ ...last, t }] : [];
    },
    // Decodes the recorded path from each start offset (top perOffset each), merged and
    // sorted globally. Candidates are [{word, p, offset}], p sums to 1, offset = best start.
    end() {
      const candidates = path?.length ? merge(offsets.flatMap(decodeFrom)) : [];
      if (candidates.length) {
        lattice.push(candidates);
        traces.push(trace());
        onWord?.(candidates, lattice);
      }
      path = null;
      render();
    },
    // Single word-break input (a blink later): ends the current word and starts the next.
    boundary() {
      if (path) this.end();
      this.start();
    },
    deleteWord() {
      lattice.pop();
      traces.pop();
      render();
    },
    getLattice: () => lattice,
    // [{candidates, trace}] per word slot, the input for llm.js
    getSlots: () => lattice.map((candidates, i) => ({ candidates, trace: traces[i] })),
    // Stops recording and clears the lattice (after a sentence is committed).
    clear() {
      path = null;
      lattice = [];
      traces = [];
      render();
    },
  };
}
