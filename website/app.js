// Connects to the local companion app's WebSocket bridge and drives the
// goal / quiz UI off events reported from real gaze actions in the target app.

const BRIDGE_URL = "ws://localhost:8765";

// TODO: flesh out goals/steps/quiz content; this is placeholder shape.
const GOALS = [
  {
    id: "send-a-message",
    title: "Send a message",
    steps: [
      { target: "compose button", instruction: "Start a new conversation" },
      { target: "message field", instruction: "Type your message" },
      { target: "send button", instruction: "Send it" },
    ],
  },
];

let socket = null;
let currentGoal = null;
let currentStepIndex = 0;

function connect() {
  socket = new WebSocket(BRIDGE_URL);

  socket.addEventListener("open", () => {
    setStatus("connected");
  });

  socket.addEventListener("close", () => {
    setStatus("disconnected");
    setTimeout(connect, 1000); // retry
  });

  socket.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);
    handleCompanionEvent(msg);
  });
}

function setStatus(text) {
  document.getElementById("status").textContent = text;
}

function handleCompanionEvent(msg) {
  // TODO: msg.type === "hover" -> could log/analytics
  // msg.type === "action_completed" -> compare against currentGoal step target
  if (!currentGoal || msg.type !== "action_completed") return;

  const expected = currentGoal.steps[currentStepIndex];
  if (expected && msg.title === expected.target) {
    currentStepIndex += 1;
    renderActiveGoal();
  }
}

function startGoal(goal) {
  currentGoal = goal;
  currentStepIndex = 0;
  document.getElementById("active-goal").hidden = false;
  renderActiveGoal();
  requestHighlightForCurrentStep();
}

function renderActiveGoal() {
  document.getElementById("active-goal-title").textContent = currentGoal.title;
  const step = currentGoal.steps[currentStepIndex];
  document.getElementById("active-step").textContent = step
    ? step.instruction
    : "Goal complete!";
  if (step) requestHighlightForCurrentStep();
}

function requestHighlightForCurrentStep() {
  const step = currentGoal.steps[currentStepIndex];
  if (!step || !socket || socket.readyState !== WebSocket.OPEN) return;
  socket.send(JSON.stringify({ type: "highlight", target: step.target }));
}

function renderGoalList() {
  const list = document.getElementById("goal-list");
  GOALS.forEach((goal) => {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.textContent = goal.title;
    button.addEventListener("click", () => startGoal(goal));
    li.appendChild(button);
    list.appendChild(li);
  });
}

renderGoalList();
connect();
