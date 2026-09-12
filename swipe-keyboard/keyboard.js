// Swipe keyboard. Pointer/gaze positions go in via kb.feed(x, y); the path is
// recorded between word boundaries and decoded into ranked candidate words.
// Picking the final word is left to a downstream model (e.g. an LLM with context).

import { createDecoder } from './decoder.js';

const ROWS = ['qwertyuiop', 'asdfghjkl', 'zxcvbnm'];

export function createSwipeKeyboard(root, { words, freqs, accuracy = 1.5, limit = 10, temperature = 0.5, onWord }) {
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

  let lattice = []; // one ranked candidate list per word slot
  let path = null;
  let last = null;
  let pending = null;

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
      .map((c) => `<div class="swipe-slot">${c.slice(0, 5).map((x) => `<span style="opacity:${0.35 + 0.65 * x.p}">${x.word} ${x.p.toFixed(2)}</span>`).join('')}</div>`)
      .join('');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!path?.length) return;
    ctx.strokeStyle = 'rgba(120, 200, 255, 0.8)';
    ctx.lineWidth = 4;
    ctx.beginPath();
    path.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
    ctx.stroke();
  }

  return {
    feed(x, y) {
      last = { x, y };
      if (path) {
        path.push(last);
        render();
      }
    },
    start() {
      path = last ? [last] : [];
    },
    // Decodes the recorded path into [{word, p}], p = softmax(-cost / temperature) over the top candidates.
    end() {
      const results = path?.length ? decoder.decode(path, { radius: accuracy, limit }) : [];
      path = null;
      if (results.length) {
        const exps = results.map((r) => Math.exp(-(r.cost - results[0].cost) / temperature));
        const sum = exps.reduce((a, b) => a + b, 0);
        const candidates = results.map((r, i) => ({ word: r.word, p: exps[i] / sum }));
        lattice.push(candidates);
        onWord?.(candidates, lattice);
      }
      render();
    },
    // Single word-break input (a blink later): ends the current word, then starts
    // recording the next one after gapMs so the eyes can move to its first letter.
    boundary(gapMs = 500) {
      clearTimeout(pending);
      if (path) this.end();
      pending = setTimeout(() => this.start(), gapMs);
    },
    deleteWord() {
      lattice.pop();
      render();
    },
    getLattice: () => lattice,
  };
}
