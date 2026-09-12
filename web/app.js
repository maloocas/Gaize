/* Scanning engine, mode handling, metrics and TTS.
 *
 * Access model (design doc s5/s6): one binary switch. The switch is SPACE by
 * default and optionally a webcam blink; both call the same fire() path, so the
 * blink layer can never become a dependency.
 *
 * Row-column scanning: the highlight steps down rows on a timer; a switch hit
 * picks that row, then the highlight steps across its cells; a second hit picks
 * the cell. That is two switch actions per selection, which is what makes the
 * baseline condition honestly slow.
 */
import { initBlink } from "./blink.js";

const $ = (id) => document.getElementById(id);

/* ------------------------------------------------------------------ state */
const state = {
  mode: "accelerated",
  tokens: [],            // selected letters / whole words
  partnerTurns: [],
  scanInterval: 800,
  scanning: false,
  level: "row",          // "row" | "cell" | "candidate"
  rowIndex: 0,
  cellIndex: 0,
  candIndex: 0,
  candidates: [],
  selections: 0,
  startedAt: null,
  timerHandle: null,
  clockHandle: null,
  switchSource: "key",
  busy: false,
  spokenOnce: "",
};

/* ------------------------------------------------------- grid definitions */
// Baseline mode is letters only: to say a sentence you spell every character.
const LETTER_ROWS = [
  ["A", "B", "C", "D", "E", "F", "G"],
  ["H", "I", "J", "K", "L", "M", "N"],
  ["O", "P", "Q", "R", "S", "T", "U"],
  ["V", "W", "X", "Y", "Z", "'", "_"],
];

const ACTION_ROW_BASELINE = [
  { label: "SPEAK", action: "speak" },
  { label: "DEL", action: "delete" },
  { label: "CLEAR", action: "clear" },
];

// Accelerated mode adds high-frequency whole words and the GENERATE action.
const WORD_ROWS = [
  ["I", "you", "not", "please", "now", "can", "want"],
];

const ACTION_ROW_ACCEL = [
  { label: "GENERATE", action: "generate", cls: "cell-generate" },
  { label: "DEL", action: "delete" },
  { label: "CLEAR", action: "clear" },
  { label: "SPEAK", action: "speak" },
];

function buildRows() {
  const rows = LETTER_ROWS.map((r) => r.map((ch) => ({ label: ch, action: "letter", value: ch })));
  if (state.mode === "accelerated") {
    rows.push(WORD_ROWS[0].map((w) => ({ label: w, action: "word", value: w, cls: "cell-word" })));
    rows.push(ACTION_ROW_ACCEL);
  } else {
    rows.push(ACTION_ROW_BASELINE);
  }
  return rows;
}

let rows = buildRows();

/* --------------------------------------------------------------- rendering */
function renderGrid() {
  const grid = $("grid");
  grid.innerHTML = "";
  rows.forEach((row, r) => {
    const el = document.createElement("div");
    el.className = "grid-row";
    el.style.setProperty("--cols", String(Math.max(row.length, 3)));
    row.forEach((cell, c) => {
      const btn = document.createElement("div");
      btn.className = "cell" + (cell.cls ? ` ${cell.cls}` : "") +
        (cell.action !== "letter" && cell.action !== "word" ? " cell-action" : "");
      btn.textContent = cell.label === "_" ? "␣" : cell.label;
      btn.dataset.r = String(r);
      btn.dataset.c = String(c);
      btn.setAttribute("role", "gridcell");
      // Direct clicking is for setup and debugging; the demo uses the switch.
      btn.addEventListener("click", () => { commit(r, c); });
      el.appendChild(btn);
    });
    grid.appendChild(el);
  });
  paint();
}

function paint() {
  document.querySelectorAll(".grid-row").forEach((el, r) => {
    el.classList.toggle("row-hot", state.scanning && state.level === "row" && r === state.rowIndex);
  });
  document.querySelectorAll(".cell").forEach((el) => {
    const r = Number(el.dataset.r), c = Number(el.dataset.c);
    el.classList.toggle("cell-hot",
      state.scanning && state.level === "cell" && r === state.rowIndex && c === state.cellIndex);
  });
  document.querySelectorAll(".cand").forEach((el, i) => {
    el.classList.toggle("cand-hot",
      state.scanning && state.level === "candidate" && i === state.candIndex);
  });
}

function renderTokens() {
  const strip = $("tokenStrip");
  if (!state.tokens.length) {
    strip.innerHTML = '<span class="token-empty">no selections yet</span>';
    return;
  }
  strip.innerHTML = "";
  state.tokens.forEach((t) => {
    const el = document.createElement("span");
    el.className = "token" + (t.length > 1 ? " token-word" : "");
    el.textContent = t === "_" ? "␣" : t;
    strip.appendChild(el);
  });
}

function renderMetrics() {
  $("mSelections").textContent = String(state.selections);
  const secs = state.startedAt ? (Date.now() - state.startedAt) / 1000 : 0;
  $("mTime").textContent = `${secs.toFixed(1)}s`;
}

function setSpoken(text) {
  $("spokenText").textContent = text || " ";
  $("speakBtn").disabled = !text;
}

/* -------------------------------------------------------- scanning control */
function startScanning() {
  if (state.scanning) return;
  state.scanning = true;
  state.level = state.candidates.length ? "candidate" : "row";
  state.rowIndex = 0; state.cellIndex = 0; state.candIndex = 0;
  $("startStop").textContent = "Stop scanning";
  tick();
  state.timerHandle = setInterval(tick, state.scanInterval);
  if (!state.clockHandle) state.clockHandle = setInterval(renderMetrics, 100);
}

function stopScanning() {
  state.scanning = false;
  clearInterval(state.timerHandle); state.timerHandle = null;
  $("startStop").textContent = "Start scanning";
  paint();
}

function restartTimer() {
  if (!state.scanning) return;
  clearInterval(state.timerHandle);
  state.timerHandle = setInterval(tick, state.scanInterval);
}

/** Advance the highlight one step. */
function tick() {
  if (state.busy) return;
  if (state.level === "row") {
    state.rowIndex = (state.rowIndex + 1) % rows.length;
  } else if (state.level === "cell") {
    const row = rows[state.rowIndex];
    state.cellIndex += 1;
    // Ran off the end of the row: fall back to row scanning, which is how real
    // single-switch systems let you escape a wrong row without a second switch.
    if (state.cellIndex >= row.length) {
      state.level = "row"; state.cellIndex = 0;
      state.rowIndex = (state.rowIndex + 1) % rows.length;
    }
  } else if (state.level === "candidate") {
    state.candIndex = (state.candIndex + 1) % (state.candidates.length + 1);
  }
  paint();
}

/** The one and only switch entry point - keyboard and blink both land here. */
function fire(source = "key") {
  state.switchSource = source;
  if (!state.startedAt) state.startedAt = Date.now();
  if (!state.scanning) { startScanning(); return; }
  // A generation is in flight. Swallowing the hit is deliberate: the highlight
  // the operator aimed at is about to be replaced by the candidate list, so
  // acting on it would commit something they did not choose.
  if (state.busy) return;

  state.selections += 1;
  renderMetrics();

  if (state.level === "candidate") {
    if (state.candIndex < state.candidates.length) {
      chooseCandidate(state.candIndex);
    } else {
      // Past the last candidate: "none of these", go back to the grid.
      state.level = "row"; state.rowIndex = 0;
      renderCandidates(state.candidates, null, "none chosen - keep adding input");
    }
    paint();
    restartTimer();
    return;
  }

  if (state.level === "row") {
    state.level = "cell"; state.cellIndex = 0;
  } else {
    commit(state.rowIndex, state.cellIndex);
  }
  paint();
  restartTimer();
}

/** Apply the cell at (r, c). */
function commit(r, c) {
  const cell = rows[r]?.[c];
  if (!cell) return;
  const el = document.querySelector(`.cell[data-r="${r}"][data-c="${c}"]`);
  if (el) { el.classList.add("cell-fired"); setTimeout(() => el.classList.remove("cell-fired"), 300); }

  switch (cell.action) {
    case "letter":
      state.tokens.push(cell.value === "_" ? "_" : cell.value.toLowerCase());
      break;
    case "word":
      state.tokens.push(cell.value);
      break;
    case "delete":
      state.tokens.pop();
      break;
    case "clear":
      state.tokens = []; state.candidates = []; setSpoken("");
      renderCandidates([], null, null);
      break;
    case "generate":
      generate();
      break;
    case "speak":
      speakBaseline();
      break;
  }
  renderTokens();
  if (state.mode === "baseline") setSpoken(baselineText());
  state.level = "row"; state.cellIndex = 0;
}

/* -------------------------------------------------------- baseline spelling */
// In baseline mode the tokens ARE the characters of the sentence.
function baselineText() {
  return state.tokens.map((t) => (t === "_" ? " " : t)).join("");
}

function speakBaseline() {
  const text = baselineText().trim();
  if (!text) return;
  speak(text);
  logTrial("baseline", text);
}

/* ------------------------------------------------------------- generation */
async function generate() {
  if (!state.tokens.length || state.busy || state.level === "candidate") return;
  state.busy = true;
  renderCandidates([], null, null, true);
  const t0 = performance.now();
  try {
    const res = await fetch("/api/candidates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tokens: state.tokens, partner_turns: state.partnerTurns }),
    });
    const data = await res.json();
    const wall = Math.round(performance.now() - t0);
    state.candidates = data.candidates || [];
    $("mLatency").textContent = `${wall}ms`;
    renderCandidates(state.candidates, data, null);
    updateProviderBadge(data);
    // Hand the scan straight to the candidate list - no extra switch hit needed.
    if (state.candidates.length) {
      state.level = "candidate";
      state.candIndex = 0;
      // Restart the interval so candidate 1 gets a full dwell rather than being
      // skipped by whatever was left of the previous tick.
      restartTimer();
    }
  } catch (err) {
    renderCandidates([], null, `generation failed: ${err.message}`);
  } finally {
    state.busy = false;
    paint();
  }
}

function renderCandidates(cands, meta, note, loading = false) {
  const box = $("candidates");
  const metaEl = $("candMeta");
  box.innerHTML = "";
  if (loading) {
    box.innerHTML = '<div class="spinner">generating candidates&hellip;</div>';
    metaEl.textContent = "";
    return;
  }
  if (note) box.innerHTML = `<p class="hint">${note}</p>`;
  if (!cands.length) {
    if (!note) box.innerHTML = '<p class="hint">Select a few letters, then choose <strong>GENERATE</strong>.</p>';
    metaEl.textContent = "";
    return;
  }
  cands.forEach((c, i) => {
    const btn = document.createElement("button");
    btn.className = "cand" + (c.exact ? "" : " is-near");
    btn.innerHTML = `
      <span class="cand-rank">${i + 1}</span>
      <span class="cand-body">
        <span class="cand-text"></span>
        <span class="cand-why"></span>
      </span>
      <span class="cand-src">${c.source}</span>`;
    btn.querySelector(".cand-text").textContent = c.text;
    btn.querySelector(".cand-why").textContent = (c.reasons || []).join(" · ");
    btn.addEventListener("click", () => chooseCandidate(i));
    box.appendChild(btn);
  });
  if (meta) {
    metaEl.textContent =
      `${meta.provider} · ${meta.model} · ${meta.latency_ms}ms · ${meta.calls} call(s)` +
      (meta.degraded ? " · offline fallback" : "") +
      (meta.note ? ` · ${meta.note}` : "");
  }
}

function chooseCandidate(index) {
  const cand = state.candidates[index];
  if (!cand) return;
  setSpoken(cand.text);
  speak(cand.text);
  logTrial("accelerated", cand.text);
  state.candidates = [];
  state.tokens = [];
  renderTokens();
  renderCandidates([], null, "spoken ✓ ready for the next utterance");
  state.level = "row"; state.rowIndex = 0;
}

/* ------------------------------------------------------------------- TTS */
function speak(text) {
  const el = $("spokenText");
  el.classList.add("is-speaking");
  try {
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.0;
    u.onend = () => el.classList.remove("is-speaking");
    u.onerror = () => el.classList.remove("is-speaking");
    speechSynthesis.speak(u);
  } catch {
    setTimeout(() => el.classList.remove("is-speaking"), 600);
  }
  addTurn(text, "mine");
  state.spokenOnce = text;
}

/* ------------------------------------------------------------- trial log */
async function logTrial(mode, spoken) {
  const elapsed = state.startedAt ? Date.now() - state.startedAt : 0;
  const payload = {
    mode, spoken, target: "", selections: state.selections,
    elapsed_ms: elapsed, input_source: state.switchSource,
  };
  try {
    await fetch("/api/trial", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch { /* the demo must not care if logging fails */ }
  resetTrial(false);
  loadTrials();
}

function resetTrial(clearText = true) {
  state.selections = 0;
  state.startedAt = null;
  renderMetrics();
  if (clearText) {
    state.tokens = []; state.candidates = [];
    renderTokens(); setSpoken(""); renderCandidates([], null, null);
  }
}

async function loadTrials() {
  try {
    const res = await fetch("/api/trials");
    const { trials } = await res.json();
    const box = $("trialSummary");
    if (!trials.length) { box.textContent = "no trials yet"; return; }
    const recent = trials.slice(-6).reverse();
    const avg = (mode) => {
      const rows = trials.filter((t) => t.mode === mode && t.selections > 0);
      if (!rows.length) return null;
      return {
        sel: rows.reduce((a, t) => a + t.selections, 0) / rows.length,
        sec: rows.reduce((a, t) => a + t.elapsed_ms, 0) / rows.length / 1000,
        n: rows.length,
      };
    };
    const base = avg("baseline"), acc = avg("accelerated");
    let html = "<table><tr><th>mode</th><th>sel</th><th>time</th><th>said</th></tr>";
    recent.forEach((t) => {
      html += `<tr><td>${t.mode === "baseline" ? "base" : "accel"}</td>` +
        `<td>${t.selections}</td><td>${(t.elapsed_ms / 1000).toFixed(1)}s</td>` +
        `<td>${escapeHtml((t.spoken || "").slice(0, 26))}</td></tr>`;
    });
    html += "</table>";
    if (base && acc) {
      const factor = (base.sel / Math.max(acc.sel, 0.01)).toFixed(1);
      html += `<div class="gap-callout">${acc.sel.toFixed(1)} selections vs ` +
        `${base.sel.toFixed(1)} baseline &mdash; ${factor}&times; fewer ` +
        `(${base.sec.toFixed(1)}s &rarr; ${acc.sec.toFixed(1)}s)</div>`;
    }
    box.innerHTML = html;
  } catch { /* ignore */ }
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ------------------------------------------------------------- transcript */
function addTurn(text, who = "them") {
  if (who === "them") state.partnerTurns.push(text);
  const box = $("transcript");
  const el = document.createElement("div");
  el.className = "turn" + (who === "mine" ? " turn-mine" : "");
  el.innerHTML = `<div class="turn-who">${who === "mine" ? "them → spoken by device" : "them"}</div>`;
  const p = document.createElement("div");
  p.textContent = text;
  el.appendChild(p);
  box.appendChild(el);
  box.scrollTop = box.scrollHeight;
}

/* ----------------------------------------------------------------- profile */
async function loadProfile() {
  try {
    const p = await (await fetch("/api/profile")).json();
    $("pName").value = p.name || "";
    $("pAbout").value = p.about || "";
    $("pPeople").value = (p.people || []).join("\n");
    $("pTopics").value = (p.topics || []).join("\n");
    $("pPhrases").value = (p.phrases || []).join("\n");
  } catch { /* ignore */ }
}

async function saveProfile() {
  const lines = (v) => v.split("\n").map((s) => s.trim()).filter(Boolean);
  const body = {
    name: $("pName").value.trim(),
    about: $("pAbout").value.trim(),
    people: lines($("pPeople").value),
    topics: lines($("pTopics").value),
    phrases: lines($("pPhrases").value),
  };
  await fetch("/api/profile", {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  $("profileSaved").textContent = "saved ✓";
  setTimeout(() => ($("profileSaved").textContent = ""), 1800);
}

/* ------------------------------------------------------------------ health */
function updateProviderBadge(meta) {
  const el = $("providerBadge");
  if (!meta) return;
  const label = meta.provider || meta.model || "unknown";
  el.textContent = meta.degraded ? `${label} (offline)` : label;
  el.className = "badge " + (meta.degraded ? "badge-warn" : "badge-ok");
}

async function checkHealth() {
  try {
    const h = await (await fetch("/api/health")).json();
    const el = $("providerBadge");
    el.textContent = `${h.provider} · ${h.model}`;
    el.className = "badge " + (h.reachable ? "badge-ok" : "badge-warn");
    el.title = h.detail || "";
  } catch {
    $("providerBadge").textContent = "server unreachable";
    $("providerBadge").className = "badge badge-bad";
  }
}

/* -------------------------------------------------------------- mode switch */
function setMode(mode) {
  state.mode = mode;
  $("modeBaseline").classList.toggle("is-active", mode === "baseline");
  $("modeAccel").classList.toggle("is-active", mode === "accelerated");
  $("scanTitle").textContent = mode === "baseline"
    ? "Scanning — spell every character" : "Scanning — letters, words, generate";
  $("scanHint").innerHTML = mode === "baseline"
    ? "Baseline condition: every character of the sentence must be scanned and selected. " +
      "Press <kbd>Space</kbd> to pick the highlighted row, then the highlighted cell."
    : "Select the <strong>first letter of each word</strong>, then choose " +
      "<strong>GENERATE</strong>. Press <kbd>Space</kbd> (or blink) to select.";
  $("candPanel").style.display = mode === "baseline" ? "none" : "";
  rows = buildRows();
  state.tokens = []; state.candidates = [];
  state.level = "row"; state.rowIndex = 0; state.cellIndex = 0;
  renderTokens(); setSpoken(""); renderCandidates([], null, null);
  resetTrial(false);
  renderGrid();
}

/* ------------------------------------------------------------------- wiring */
function wire() {
  $("modeBaseline").addEventListener("click", () => setMode("baseline"));
  $("modeAccel").addEventListener("click", () => setMode("accelerated"));
  $("startStop").addEventListener("click", () => (state.scanning ? stopScanning() : startScanning()));
  $("resetTrial").addEventListener("click", () => resetTrial(true));
  $("speakBtn").addEventListener("click", () => {
    const text = $("spokenText").textContent.trim();
    if (text) { speak(text); logTrial(state.mode, text); }
  });

  $("scanSpeed").addEventListener("input", (e) => {
    state.scanInterval = Number(e.target.value);
    $("scanSpeedOut").textContent = `${state.scanInterval}ms`;
    restartTimer();
  });

  $("partnerForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const v = $("partnerInput").value.trim();
    if (!v) return;
    addTurn(v, "them");
    $("partnerInput").value = "";
  });
  document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => addTurn(chip.dataset.turn, "them"));
  });

  $("saveProfile").addEventListener("click", saveProfile);
  $("refreshTrials").addEventListener("click", loadTrials);

  // The keyboard switch. Space is the switch; it must never scroll the page.
  window.addEventListener("keydown", (e) => {
    const typing = ["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName);
    if (e.code === "Space" && !typing) {
      e.preventDefault();
      fire("key");
    }
  });
}

/* --------------------------------------------------------------- blink layer */
function setupBlink() {
  const badge = $("blinkBadge");
  const status = $("blinkStatus");
  const blink = initBlink({
    video: $("cam"),
    overlay: $("camOverlay"),
    placeholder: $("camPlaceholder"),
    onBlink: () => {
      fire("blink");
      $("switchBadge").textContent = "switch: BLINK";
      $("switchBadge").className = "badge badge-ok";
    },
    onEar: (ear, threshold) => {
      const pct = Math.max(0, Math.min(1, ear / 0.45));
      $("earFill").style.width = `${pct * 100}%`;
      $("earThresh").style.left = `${Math.min(1, threshold / 0.45) * 100}%`;
      $("earVal").textContent = `EAR ${ear.toFixed(3)}`;
    },
    onStatus: (text, kind) => {
      status.textContent = text;
      if (kind) { badge.textContent = kind; badge.className = "badge " +
        (kind === "live" ? "badge-ok" : kind === "error" ? "badge-bad" : "badge-warn"); }
    },
  });

  $("camToggle").addEventListener("click", async () => {
    if (blink.running()) {
      blink.stop();
      $("camToggle").textContent = "Enable camera";
      $("calibrateBtn").disabled = true;
      badge.textContent = "off"; badge.className = "badge badge-off";
      $("switchBadge").textContent = "switch: SPACE";
      $("switchBadge").className = "badge badge-key";
    } else {
      $("camToggle").disabled = true;
      $("camToggle").textContent = "Starting…";
      const ok = await blink.start();
      $("camToggle").disabled = false;
      $("camToggle").textContent = ok ? "Disable camera" : "Enable camera";
      $("calibrateBtn").disabled = !ok;
    }
  });

  $("calibrateBtn").addEventListener("click", () => blink.calibrate());
  $("earSlider").addEventListener("input", (e) => {
    const v = Number(e.target.value);
    $("earSliderOut").textContent = v.toFixed(3);
    blink.setThreshold(v);
  });
}

/* --------------------------------------------------------------------- boot */
setMode("accelerated");
wire();
setupBlink();
loadProfile();
loadTrials();
checkHealth();
renderMetrics();
