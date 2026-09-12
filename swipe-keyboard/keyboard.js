// Swipe keyboard. Pointer/gaze positions go in via kb.feed(x, y); the path is
// recorded between kb.start() and kb.end(), then decoded into a word.

import { createDecoder } from './decoder.js';

const ROWS = ['qwertyuiop', 'asdfghjkl', 'zxcvbnm'];

export function createSwipeKeyboard(root, { words, freqs, accuracy = 1.5 }) {
  const decoder = createDecoder(words, freqs);

  root.classList.add('swipe-kb');
  root.innerHTML = `
    <div class="swipe-output"></div>
    <div class="swipe-suggestions"></div>
    <div class="swipe-keys">
      ${ROWS.map((r) => `<div class="swipe-row">${[...r].map((c) => `<div class="swipe-key" data-key="${c}">${c}</div>`).join('')}</div>`).join('')}
    </div>
    <canvas class="swipe-trace"></canvas>`;

  const output = root.querySelector('.swipe-output');
  const suggestionsEl = root.querySelector('.swipe-suggestions');
  const canvas = root.querySelector('.swipe-trace');
  const ctx = canvas.getContext('2d');

  let text = [];
  let alternates = [];
  let path = null;

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

  suggestionsEl.addEventListener('click', (e) => {
    const w = e.target.dataset.suggest;
    if (!w) return;
    text[text.length - 1] = w;
    alternates = [];
    render();
  });

  function render() {
    output.textContent = text.join(' ');
    suggestionsEl.innerHTML = alternates.map((w) => `<div class="swipe-key suggestion" data-suggest="${w}">${w}</div>`).join('');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!path?.length) return;
    ctx.strokeStyle = 'rgba(120, 200, 255, 0.8)';
    ctx.lineWidth = 4;
    ctx.beginPath();
    path.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
    ctx.stroke();
  }

  let last = null;
  let pending = null;
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
    end() {
      const results = path?.length ? decoder.decode(path, { radius: accuracy }) : [];
      path = null;
      if (results.length) {
        text.push(results[0].word);
        alternates = results.slice(1).map((r) => r.word);
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
      text.pop();
      alternates = [];
      render();
    },
    getText: () => text.join(' '),
  };
}
