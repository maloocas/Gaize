// Connects to the local companion app's WebSocket bridge and drives the
// goal -> quiz/scenario -> feedback loop off events reported from real
// gaze/voice actions in the target app (Messages, for the demo).

const BRIDGE_URL = "ws://localhost:8765";

const GOALS = [
  {
    id: "send-a-message",
    title: "Send a message",
    steps: [
      { target: "compose", instruction: "Look at the compose button to start a new conversation" },
      { target: "send", instruction: "Look at the send button once you've typed a message" },
    ],
    quiz: [
      {
        question: "Which button starts a brand-new conversation?",
        options: ["Send", "Compose", "Details", "Search"],
        correct: "Compose",
      },
      {
        question: "Which button actually sends your typed message?",
        options: ["Attach", "Send", "Camera", "Back"],
        correct: "Send",
      },
    ],
    scenario: {
      instruction: "Start a new conversation, then send a message.",
      expectedTargets: ["compose", "send"],
    },
  },
  {
    id: "add-an-attachment",
    title: "Add an attachment",
    steps: [
      { target: "attach", instruction: "Look at the attach button to add a photo or file" },
    ],
    quiz: [
      {
        question: "Which button lets you attach a photo or file?",
        options: ["Emoji", "Attach", "App Store", "Details"],
        correct: "Attach",
      },
    ],
    scenario: {
      instruction: "Attach a photo to your message.",
      expectedTargets: ["attach"],
    },
  },
];

let socket = null;
let currentGoal = null;
let currentStepIndex = 0;
let quizAnswers = [];
let quizIndex = 0;
let scenarioProgress = 0;
let mode = "goal-list"; // goal-list | goal | quiz | scenario | feedback

function connect() {
  socket = new WebSocket(BRIDGE_URL);
  socket.addEventListener("open", () => setStatus(true, "Connected to Gaize"));
  socket.addEventListener("close", () => {
    setStatus(false, "Waiting for Gaize…");
    setTimeout(connect, 1000);
  });
  socket.addEventListener("error", () => setStatus(false, "Waiting for Gaize…"));
  socket.addEventListener("message", (event) => {
    handleCompanionEvent(JSON.parse(event.data));
  });
}

function setStatus(connected, text) {
  document.getElementById("status").textContent = text;
  document.getElementById("connection-dot").classList.toggle("connected", connected);
}

function requestHighlight(target) {
  if (!target || !socket || socket.readyState !== WebSocket.OPEN) return;
  socket.send(JSON.stringify({ type: "highlight", target }));
}

function handleCompanionEvent(msg) {
  if (msg.type !== "action_completed") return;
  const title = (msg.title || "").toLowerCase();

  if (mode === "goal") {
    const expected = currentGoal.steps[currentStepIndex];
    if (expected && title.includes(expected.target)) {
      currentStepIndex += 1;
      renderGoal();
    }
  } else if (mode === "scenario") {
    const expectedTarget = currentGoal.scenario.expectedTargets[scenarioProgress];
    if (expectedTarget && title.includes(expectedTarget)) {
      scenarioProgress += 1;
      renderScenario();
    }
  }
}

// ---- Goal list ----

function renderGoalList() {
  mode = "goal-list";
  show("intro", "goals");
  hide("active-goal", "quiz");

  const list = document.getElementById("goal-list");
  list.innerHTML = "";

  GOALS.forEach((goal) => {
    const li = document.createElement("li");
    const card = document.createElement("button");
    card.className = "goal-card";
    card.innerHTML = `
      <span>
        <span class="goal-card-title">${escapeHtml(goal.title)}</span><br />
        <span class="goal-card-meta">${goal.steps.length} step${goal.steps.length > 1 ? "s" : ""}</span>
      </span>
      <span class="goal-card-arrow" aria-hidden="true">→</span>
    `;
    card.addEventListener("click", () => startGoal(goal));
    li.appendChild(card);
    list.appendChild(li);
  });
}

function startGoal(goal) {
  currentGoal = goal;
  currentStepIndex = 0;
  mode = "goal";
  hide("intro", "goals", "quiz");
  show("active-goal");
  document.getElementById("followup-choice").hidden = true;
  renderGoal();
}

function renderGoal() {
  document.getElementById("active-goal-title").textContent = currentGoal.title;
  renderStepsTrack();

  const step = currentGoal.steps[currentStepIndex];
  const stepEl = document.getElementById("active-step");
  const followup = document.getElementById("followup-choice");

  if (step) {
    stepEl.textContent = step.instruction;
    followup.hidden = true;
    requestHighlight(step.target);
  } else {
    stepEl.textContent = "Nice — you finished the steps. Ready to check what you learned?";
    followup.hidden = false;
  }
}

function renderStepsTrack() {
  const track = document.getElementById("steps-track");
  track.innerHTML = "";
  currentGoal.steps.forEach((_, i) => {
    const dot = document.createElement("div");
    dot.className = "step-dot";
    if (i < currentStepIndex) dot.classList.add("done");
    else if (i === currentStepIndex) dot.classList.add("current");
    track.appendChild(dot);
  });
}

// ---- Quiz ----

function startQuiz() {
  mode = "quiz";
  quizIndex = 0;
  quizAnswers = [];
  hide("active-goal");
  show("quiz");
  document.getElementById("quiz-heading").textContent = "Quiz";
  renderQuizQuestion();
}

function renderQuizQuestion() {
  const body = document.getElementById("quiz-body");
  body.innerHTML = "";

  const question = currentGoal.quiz[quizIndex];
  if (!question) {
    renderFeedback();
    return;
  }

  const progress = document.createElement("p");
  progress.className = "quiz-progress";
  progress.textContent = `Question ${quizIndex + 1} of ${currentGoal.quiz.length}`;
  body.appendChild(progress);

  const heading = document.createElement("p");
  heading.className = "quiz-question";
  heading.textContent = question.question;
  body.appendChild(heading);

  const options = document.createElement("div");
  options.className = "quiz-options";

  question.options.forEach((option) => {
    const button = document.createElement("button");
    button.className = "quiz-option";
    button.textContent = option;
    button.addEventListener("click", () => {
      quizAnswers.push({ question: question.question, answer: option, correct: question.correct });
      quizIndex += 1;
      renderQuizQuestion();
    });
    options.appendChild(button);
  });

  body.appendChild(options);
}

// ---- Scenario (live-tracked in the real app) ----

function startScenario() {
  mode = "scenario";
  scenarioProgress = 0;
  hide("active-goal");
  show("quiz");
  document.getElementById("quiz-heading").textContent = "Scenario";
  renderScenario();
}

function renderScenario() {
  const body = document.getElementById("quiz-body");
  body.innerHTML = "";

  const scenario = currentGoal.scenario;

  if (scenarioProgress >= scenario.expectedTargets.length) {
    renderFeedback();
    return;
  }

  const heading = document.createElement("p");
  heading.className = "scenario-instruction";
  heading.textContent = scenario.instruction;
  body.appendChild(heading);

  const progress = document.createElement("p");
  progress.className = "scenario-progress";
  progress.textContent = `Step ${scenarioProgress + 1} of ${scenario.expectedTargets.length}`;
  body.appendChild(progress);

  requestHighlight(scenario.expectedTargets[scenarioProgress]);
}

// ---- Feedback ----

function renderFeedback() {
  mode = "feedback";
  const body = document.getElementById("quiz-body");
  body.innerHTML = "";

  const title = document.createElement("h3");
  title.className = "feedback-title";

  if (quizAnswers.length > 0) {
    const correctCount = quizAnswers.filter((a) => a.answer === a.correct).length;
    title.textContent = `You got ${correctCount} of ${quizAnswers.length} right.`;
    body.appendChild(title);

    quizAnswers.forEach((a) => {
      const row = document.createElement("div");
      const isCorrect = a.answer === a.correct;
      row.className = `feedback-row ${isCorrect ? "correct" : "incorrect"}`;
      const q = document.createElement("span");
      q.className = "feedback-row-question";
      q.textContent = isCorrect
        ? `${a.question} — correct.`
        : `${a.question} — you said "${a.answer}", correct answer is "${a.correct}".`;
      row.appendChild(q);
      body.appendChild(row);
    });
  } else {
    title.textContent = "Scenario complete — you did it correctly.";
    body.appendChild(title);
  }

  const doneBtn = document.createElement("button");
  doneBtn.className = "btn-primary";
  doneBtn.textContent = "Back to goals";
  doneBtn.addEventListener("click", renderGoalList);
  body.appendChild(doneBtn);
}

// ---- DOM helpers ----

function show(...ids) {
  ids.forEach((id) => (document.getElementById(id).hidden = false));
}

function hide(...ids) {
  ids.forEach((id) => (document.getElementById(id).hidden = true));
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

document.getElementById("cancel-goal").addEventListener("click", renderGoalList);
document.getElementById("btn-quiz").addEventListener("click", startQuiz);
document.getElementById("btn-scenario").addEventListener("click", startScenario);

renderGoalList();
connect();
