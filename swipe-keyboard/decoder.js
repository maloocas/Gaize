// SHARK2-style shape-writing decoder (Kristensson & Zhai, UIST 2004), adapted for gaze.
// Compares a gaze path against each word's ideal path through key centers,
// combining a shape channel (scale/translation invariant) and a location channel.

const N = 40; // resample count

function resample(pts, n = N) {
  if (pts.length === 1) return Array.from({ length: n }, () => ({ ...pts[0] }));
  let total = 0;
  for (let i = 1; i < pts.length; i++) total += Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y);
  if (total === 0) return Array.from({ length: n }, () => ({ ...pts[0] }));
  const step = total / (n - 1);
  const out = [{ ...pts[0] }];
  let acc = 0;
  let prev = pts[0];
  for (let i = 1; i < pts.length; i++) {
    let cur = pts[i];
    let d = Math.hypot(cur.x - prev.x, cur.y - prev.y);
    while (acc + d >= step && out.length < n) {
      const t = (step - acc) / d;
      const p = { x: prev.x + t * (cur.x - prev.x), y: prev.y + t * (cur.y - prev.y) };
      out.push(p);
      prev = p;
      d = Math.hypot(cur.x - prev.x, cur.y - prev.y);
      acc = 0;
    }
    acc += d;
    prev = cur;
  }
  while (out.length < n) out.push({ ...pts[pts.length - 1] });
  return out;
}

function normalize(pts) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity, cx = 0, cy = 0;
  for (const p of pts) {
    minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
    minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
    cx += p.x; cy += p.y;
  }
  cx /= pts.length; cy /= pts.length;
  const s = Math.max(maxX - minX, maxY - minY) || 1;
  return pts.map((p) => ({ x: (p.x - cx) / s, y: (p.y - cy) / s }));
}

function meanDist(a, b) {
  let d = 0;
  for (let i = 0; i < a.length; i++) d += Math.hypot(a[i].x - b[i].x, a[i].y - b[i].y);
  return d / a.length;
}

export function createDecoder(words, freqs = null) {
  let keys = null; // letter -> {x, y}
  let keyW = 1;
  const templates = new Map();
  const byFirst = new Map();
  words.forEach((w, i) => {
    if (!byFirst.has(w[0])) byFirst.set(w[0], []);
    byFirst.get(w[0]).push(i);
  });
  const logPrior = freqs ? freqs.map((f) => Math.log(f + 1)) : null;
  const maxLogPrior = logPrior ? Math.max(...logPrior) : 0;

  function template(i) {
    let t = templates.get(i);
    if (!t) {
      const pts = [];
      for (const ch of words[i]) {
        const k = keys[ch];
        const last = pts[pts.length - 1];
        if (!last || last.x !== k.x || last.y !== k.y) pts.push(k);
      }
      const r = resample(pts);
      t = { loc: r, shape: normalize(r) };
      templates.set(i, t);
    }
    return t;
  }

  return {
    // keyCenters: {a: {x, y}, ...}; width: key width in px (location distances are scaled by it)
    setLayout(keyCenters, width) {
      keys = keyCenters;
      keyW = width;
      templates.clear();
    },

    decode(path, { limit = 6, radius = 1.6 } = {}) {
      // Collapse gaze jitter into fixations so noise doesn't add fake arc length.
      const fix = [];
      let sum = null;
      for (const p of path) {
        if (sum && Math.hypot(p.x - sum.x / sum.n, p.y - sum.y / sum.n) < 0.5 * keyW) {
          sum.x += p.x; sum.y += p.y; sum.n++;
        } else {
          if (sum) fix.push({ x: sum.x / sum.n, y: sum.y / sum.n, n: sum.n });
          sum = { x: p.x, y: p.y, n: 1 };
        }
      }
      fix.push({ x: sum.x / sum.n, y: sum.y / sum.n, n: sum.n });
      // Pauses (long fixations, excluding the endpoints) mark letters the word must contain.
      const pauseN = Math.max(4, 2 * (path.length / fix.length));
      const pauses = fix.slice(1, -1).filter((f) => f.n >= pauseN);
      const r = resample(fix);
      const shape = normalize(r);
      const start = r[0];
      const end = r[r.length - 1];
      const near = (p) => Object.keys(keys).filter((c) => Math.hypot(keys[c].x - p.x, keys[c].y - p.y) <= radius * keyW);
      const endSet = new Set(near(end));
      const results = [];
      for (const first of near(start)) {
        for (const i of byFirst.get(first) || []) {
          const w = words[i];
          if (!endSet.has(w[w.length - 1])) continue;
          const t = template(i);
          let cost = meanDist(r, t.loc) / keyW + 2 * meanDist(shape, t.shape);
          // Start and end points are deliberate, so weight them beyond the averaged location term.
          const a = keys[w[0]], b = keys[w[w.length - 1]];
          cost += 0.5 * (Math.hypot(a.x - start.x, a.y - start.y) + Math.hypot(b.x - end.x, b.y - end.y)) / keyW;
          for (const p of pauses) {
            let best = Infinity;
            for (const ch of w) best = Math.min(best, Math.hypot(keys[ch].x - p.x, keys[ch].y - p.y));
            cost += Math.max(0, best / keyW - 0.5) / pauses.length;
          }
          if (logPrior) cost += 0.15 * (maxLogPrior - logPrior[i]);
          results.push({ word: w, cost });
        }
      }
      results.sort((a, b) => a.cost - b.cost);
      return results.slice(0, limit);
    },
  };
}

// Accepts "word" or "word count" per line.
export async function loadWords(url) {
  const lines = (await (await fetch(url)).text()).split('\n');
  const words = [];
  const freqs = [];
  for (const line of lines) {
    const [w, f] = line.trim().toLowerCase().split(/\s+/);
    if (!w || !/^[a-z]+$/.test(w)) continue;
    words.push(w);
    freqs.push(f ? Number(f) : NaN);
  }
  return { words, freqs: freqs.every(Number.isFinite) ? freqs : null };
}
