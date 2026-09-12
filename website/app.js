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
let mode = "goal-list"; // goal-list | goal | choose-followup | quiz | scenario | feedback

function connect() {
  socket = new WebSocket(BRIDGE_URL);
  socket.addEventListener("open", () => setStatus("connected"));
  socket.addEventListener("close", () => {
    setStatus("disconnected");
    setTimeout(connect, 1000);
  });
  socket.addEventListener("message", (event) => {
    handleCompanionEvent(JSON.parse(event.data));
  });
}

function setStatus(text) {
  document.getElementById("status").textContent = text;
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
  show("goals");
  hide("active-goal", "quiz");
  const list = document.getElementById("goal-list");
  list.innerHTML = "";
  GOALS.forEach((goal) => {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.textContent = goal.title;
    button.addEventListener("click", () => startGoal(goal));
    li.appendChild(button);
    list.appendChild(li);
  });
}

function startGoal(goal) {
  currentGoal = goal;
  currentStepIndex = 0;
  mode = "goal";
  hide("goals", "quiz");
  show("active-goal");
  renderGoal();
}

function renderGoal() {
  document.getElementById("active-goal-title").textContent = currentGoal.title;
  const step = currentGoal.steps[currentStepIndex];
  const stepEl = document.getElementById("active-step");

  if (step) {
    stepEl.textContent = step.instruction;
    requestHighlight(step.target);
  } else {
    stepEl.textContent = "Nice — you finished the steps.";
    renderFollowUpChoice();
  }
}

function renderFollowUpChoice() {
  const container = document.getElementById("active-goal");
  const existing = document.getElementById("followup-choice");
  if (existing) existing.remove();

  const div = document.createElement("div");
  div.id = "followup-choice";

  const quizBtn = document.createElement("button");
  quizBtn.textContent = "Take a quiz";
  quizBtn.addEventListener("click", startQuiz);

  const scenarioBtn = document.createElement("button");
  scenarioBtn.textContent = "Try a scenario";
  scenarioBtn.addEventListener("click", startScenario);

  div.appendChild(quizBtn);
  div.appendChild(scenarioBtn);
  container.appendChild(div);
}

// ---- Quiz ----

function startQuiz() {
  mode = "quiz";
  quizIndex = 0;
  quizAnswers = [];
  hide("active-goal");
  show("quiz");
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

  const heading = document.createElement("p");
  heading.textContent = `${quizIndex + 1}. ${question.question}`;
  body.appendChild(heading);

  question.options.forEach((option) => {
    const button = document.createElement("button");
    button.textContent = option;
    button.addEventListener("click", () => {
      quizAnswers.push({ question: question.question, answer: option, correct: question.correct });
      quizIndex += 1;
      renderQuizQuestion();
    });
    body.appendChild(button);
    body.appendChild(document.createElement("br"));
  });
}

// ---- Scenario (live-tracked in the real app) ----

function startScenario() {
  mode = "scenario";
  scenarioProgress = 0;
  hide("active-goal");
  show("quiz");
  renderScenario();
}

function renderScenario() {
  const body = document.getElementById("quiz-body");
  body.innerHTML = "";

  const scenario = currentGoal.scenario;
  const heading = document.createElement("p");
  heading.textContent = scenario.instruction;
  body.appendChild(heading);

  const progress = document.createElement("p");
  progress.textContent = `Step ${Math.min(scenarioProgress + 1, scenario.expectedTargets.length)} of ${scenario.expectedTargets.length}`;
  body.appendChild(progress);

  if (scenarioProgress >= scenario.expectedTargets.length) {
    renderFeedback();
  } else {
    requestHighlight(scenario.expectedTargets[scenarioProgress]);
  }
}

// ---- Feedback ----

function renderFeedback() {
  mode = "feedback";
  const body = document.getElementById("quiz-body");
  body.innerHTML = "";

  const title = document.createElement("h3");

  if (quizAnswers.length > 0) {
    const correctCount = quizAnswers.filter((a) => a.answer === a.correct).length;
    title.textContent = `You got ${correctCount} of ${quizAnswers.length} right.`;
    body.appendChild(title);

    quizAnswers.forEach((a) => {
      const line = document.createElement("p");
      const verdict = a.answer === a.correct ? "correct" : `you said "${a.answer}", correct answer is "${a.correct}"`;
      line.textContent = `${a.question} — ${verdict}`;
      body.appendChild(line);
    });
  } else {
    title.textContent = "Scenario complete — you did it correctly.";
    body.appendChild(title);
  }

  const doneBtn = document.createElement("button");
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

renderGoalList();
connect();
