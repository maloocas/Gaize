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
  offsets = [0, 200, 400, 600, 800], // ms after the boundary
  perOffset = 3,
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
  let path = null;
  let t0 = 0;
  let last = null;

  function layout() {
    const centers = {};
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
      .map((c) => `<div class="swipe-slot">${offsets
        .map((o) => `<div class="swipe-group"><i>+${o / 1000}s</i>${c
          .filter((x) => x.offset === o)
          .map((x) => `<span style="opacity:${0.35 + 0.65 * x.p}">${x.word} ${x.p.toFixed(2)}</span>`)
          .join('')}</div>`)
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
    const results = decoder.decode(sub, { radius: accuracy, limit: perOffset });
    if (!results.length) return [];
    const exps = results.map((r) => Math.exp(-(r.cost - results[0].cost) / temperature));
    const sum = exps.reduce((a, b) => a + b, 0);
    return results.map((r, j) => ({ word: r.word, p: exps[j] / sum, offset }));
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
    // Decodes the recorded path from each start offset. Candidates are [{word, p, offset}],
    // up to perOffset per offset; p is a softmax over that offset's candidates.
    end() {
      const candidates = path?.length ? offsets.flatMap(decodeFrom) : [];
      path = null;
      if (candidates.length) {
        lattice.push(candidates);
        onWord?.(candidates, lattice);
      }
      render();
    },
    // Single word-break input (a blink later): ends the current word and starts the next.
    boundary() {
      if (path) this.end();
      this.start();
    },
    deleteWord() {
      lattice.pop();
      render();
    },
    getLattice: () => lattice,
  };
}
