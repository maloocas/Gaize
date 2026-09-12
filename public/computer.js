const $ = (id) => document.getElementById(id);
const views = { computer: "computerView", keyboard: "keyboardView", communicate: "aacView", sign: "signView", settings: "settingsView" };
let bridgeOnline = false;
let controlArmed = false;
let dwellMs = 900;
let hoverTarget = null;
let hoverStarted = 0;
let dwellFired = false;

function showView(name) {
  Object.entries(views).forEach(([key, id]) => $(id)?.classList.toggle("hidden", key !== name));
  document.querySelectorAll(".nav-btn").forEach((b) => b.classList.toggle("is-active", b.dataset.view === name));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function say(text) {
  speechSynthesis.cancel();
  speechSynthesis.speak(new SpeechSynthesisUtterance(text));
}

async function bridge(path, body = {}) {
  const res = await fetch(`http://127.0.0.1:8766/${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error("bridge unavailable");
  return res.json();
}

async function connectBridge() {
  try {
    const status = await bridge("status"); bridgeOnline = true;
    controlArmed = Boolean(status.armed);
    window.openGazeSystemArmed = controlArmed;
    $("bridgeLabel").textContent = "macOS control connected";
    $("trackingLabel").textContent = "Whole computer ready";
    $("bridgeConnect").textContent = controlArmed ? "Connected and armed ✓" : "Bridge found — control stopped";
  } catch {
    bridgeOnline = false;
    $("bridgeLabel").textContent = "Browser mode · start native/bridge.py for macOS";
    $("bridgeConnect").textContent = "Try again";
  }
}

async function startSystemControl() {
  const button = $("startSystemControl");
  const statusEl = $("systemControlStatus");
  if (controlArmed) {
    await bridge("panic").catch(() => {});
    controlArmed = false; window.openGazeSystemArmed = false;
    button.textContent = "Start eye control";
    statusEl.textContent = "Control stopped. The camera can remain on for AAC blink scanning.";
    return;
  }
  button.disabled = true; button.textContent = "Connecting…";
  try {
    const status = await bridge("status");
    const code = $("pairingCode").value.trim();
    const armed = await bridge("arm", code ? { code } : {});
    bridgeOnline = true; controlArmed = Boolean(armed.armed);
    window.openGazeSystemArmed = controlArmed;
    if (!controlArmed) throw new Error("not armed");
    if (!document.getElementById("camToggle")?.textContent.includes("Disable")) {
      document.getElementById("camToggle")?.click();
    }
    button.textContent = "Stop eye control";
    $("trackingLabel").textContent = "Eyes control the Mac";
    $("bridgeLabel").textContent = "Blink clicks · keyboard is automatic";
    statusEl.textContent = "Active. Leave this page open; look around the computer and blink to click.";
    if (!status.needs_code) $("pairingCode").style.display = "none";
  } catch {
    bridgeOnline = false; controlArmed = false; window.openGazeSystemArmed = false;
    button.textContent = "Start eye control";
    statusEl.textContent = "Could not arm the bridge. Run python3 native/bridge.py and enter its pairing code.";
  } finally { button.disabled = false; }
}

function activate(el) {
  if (!el || el.disabled) return;
  el.classList.add("gaze-activated");
  setTimeout(() => el.classList.remove("gaze-activated"), 350);
  el.click();
}

// Called by the MediaPipe camera layer. Coordinates are normalized and smoothed there.
window.openGazeMove = async (x, y) => {
  const px = Math.max(12, Math.min(innerWidth - 12, x * innerWidth));
  const py = Math.max(12, Math.min(innerHeight - 12, y * innerHeight));
  const cursor = $("gazeCursor");
  cursor.style.transform = `translate(${px}px, ${py}px)`;
  cursor.classList.add("visible");
  if (controlArmed) bridge("move", { x, y }).catch(() => { controlArmed = false; window.openGazeSystemArmed = false; });
  const next = document.elementFromPoint(px, py)?.closest("button, .gaze-target");
  if (next !== hoverTarget) { hoverTarget = next; hoverStarted = performance.now(); dwellFired = false; }
  document.querySelectorAll(".gaze-hover").forEach((n) => n.classList.remove("gaze-hover"));
  if (next) {
    next.classList.add("gaze-hover");
    const progress = Math.min(1, (performance.now() - hoverStarted) / dwellMs);
    cursor.style.setProperty("--dwell", `${progress * 360}deg`);
    if ($("dwellToggle")?.checked && progress >= 1 && !dwellFired) { dwellFired = true; activate(next); }
  } else cursor.style.setProperty("--dwell", "0deg");
};

window.openGazeBlink = () => {
  if (controlArmed) bridge("click").catch(() => { controlArmed = false; window.openGazeSystemArmed = false; });
  else if (!$("aacView").classList.contains("hidden")) return;
  else activate(hoverTarget);
};

const letters = ["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"];
function buildKeyboard() {
  const board = $("onscreenKeyboard");
  letters.forEach((row) => {
    const line = document.createElement("div"); line.className = "key-row";
    [...row].forEach((letter) => {
      const b = document.createElement("button"); b.className = "key gaze-target"; b.textContent = letter; b.dataset.key = letter.toLowerCase(); line.appendChild(b);
    }); board.appendChild(line);
  });
  document.querySelectorAll("[data-key]").forEach((b) => b.addEventListener("click", () => {
    const box = $("computerText"); const key = b.dataset.key;
    if (key === "backspace") box.value = box.value.slice(0, -1);
    else if (key === "space") box.value += " ";
    else if (key === "clear") box.value = "";
    else box.value += key;
    box.dispatchEvent(new Event("input"));
  }));
}

const phrases = ["Yes", "No", "Please wait", "I need help", "Thank you", "I need a break"];
const signs = [["👋","Hello"],["👍","Yes"],["✋","No / stop"],["🙏","Please"],["💧","Water"],["🆘","I need help"],["⏳","Please wait"],["❤️","Thank you"],["🚻","Bathroom"],["😣","I am in pain"],["🤟","I love you"],["🔁","Say that again"]];
function buildPhrases() {
  phrases.forEach((text) => { const b=document.createElement("button"); b.className="phrase-pill gaze-target"; b.textContent=text; b.onclick=()=>say(text); $("quickSpeak").appendChild(b); });
  signs.forEach(([icon,text]) => { const b=document.createElement("button"); b.className="sign-card gaze-target"; b.innerHTML=`<span>${icon}</span><strong>${text}</strong>`; b.onclick=()=>say(text); $("signGrid").appendChild(b); });
}

function wire() {
  document.querySelectorAll(".nav-btn").forEach((b) => b.onclick=()=>showView(b.dataset.view));
  document.querySelectorAll(".launch-card").forEach((b) => b.onclick=()=> {
    const a=b.dataset.action;
    if (views[a]) showView(a); else if (a === "browser") window.open("https://www.google.com", "_blank"); else if (a === "messages") { showView("keyboard"); $("computerText").placeholder="Write your message…"; }
  });
  $("keyboardSpeak").onclick=()=>say($("computerText").value.trim());
  $("sendToComputer").onclick=async()=> { const text=$("computerText").value; if (!text) return; if (bridgeOnline) await bridge("type",{text}).catch(()=>{bridgeOnline=false;}); else { await navigator.clipboard?.writeText(text); $("sendToComputer").textContent="Copied — paste anywhere ✓"; setTimeout(()=>$("sendToComputer").textContent="Type into computer ↗",1800); } };
  $("bridgeConnect").onclick=connectBridge;
  $("startSystemControl").onclick=startSystemControl;
  $("dwellSpeed").oninput=(e)=> { dwellMs=Number(e.target.value); $("dwellOut").textContent=`${dwellMs}ms`; };
  document.querySelector("[data-jump-camera]").onclick=()=> { showView("communicate"); setTimeout(()=>$("camToggle")?.scrollIntoView({behavior:"smooth",block:"center"}),100); };
  $("computerText").oninput=()=> { const last=$("computerText").value.trim().split(/\s+/).pop()?.toLowerCase() || ""; const words=["please","people","help","hello","home","need","now","water","want","thank","yes","you"].filter(w=>w.startsWith(last)&&w!==last).slice(0,4); $("wordSuggestions").innerHTML=""; words.forEach(w=>{const b=document.createElement("button");b.className="suggestion gaze-target";b.textContent=w;b.onclick=()=>{$("computerText").value=$("computerText").value.replace(/\S+$/,w)+" ";$("computerText").dispatchEvent(new Event("input"));};$("wordSuggestions").appendChild(b);}); };
}

$("dayPart").textContent = new Date().getHours() < 12 ? "MORNING" : new Date().getHours() < 18 ? "AFTERNOON" : "EVENING";
buildKeyboard(); buildPhrases(); wire(); connectBridge();
