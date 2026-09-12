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
  {
    id: "search-a-conversation",
    title: "Search your messages",
    steps: [
      { target: "search", instruction: "Look at the search field to find a conversation" },
    ],
    quiz: [
      {
        question: "Which control finds a conversation or message?",
        options: ["Filter", "Search", "Details", "Compose"],
        correct: "Search",
      },
    ],
    scenario: {
      instruction: "Search for a conversation.",
      expectedTargets: ["search"],
    },
  },
  {
    id: "start-a-facetime-call",
    title: "Start a FaceTime call",
    steps: [
      { target: "facetime", instruction: "Look at the FaceTime button to start a video call" },
    ],
    quiz: [
      {
        question: "Which button starts a video call?",
        options: ["Camera", "FaceTime", "Emoji", "Attach"],
        correct: "FaceTime",
      },
    ],
    scenario: {
      instruction: "Start a FaceTime call.",
      expectedTargets: ["facetime"],
    },
  },
  {
    id: "add-an-emoji",
    title: "Add an emoji",
    steps: [
      { target: "emoji", instruction: "Look at the emoji button to add one to your message" },
    ],
    quiz: [
      {
        question: "Which button adds an emoji to your message?",
        options: ["Emoji", "Filter", "Search", "Back"],
        correct: "Emoji",
      },
    ],
    scenario: {
      instruction: "Add an emoji to your message.",
      expectedTargets: ["emoji"],
    },
  },
  {
    id: "filter-conversations",
    title: "Filter your conversation list",
    steps: [
      { target: "filter", instruction: "Look at the filter button to sort your conversations" },
    ],
    quiz: [
      {
        question: "Which button lets you filter or sort your conversation list?",
        options: ["Filter", "Search", "Attach", "Details"],
        correct: "Filter",
      },
    ],
    scenario: {
      instruction: "Filter your conversation list.",
      expectedTargets: ["filter"],
    },
  },
  {
    id: "send-a-photo",
    title: "Send a photo",
    steps: [
      { target: "photos", instruction: "Look at Photos to send one from your library" },
    ],
    quiz: [
      {
        question: "Which option sends a photo from your library?",
        options: ["Photos", "Stickers", "Genmoji", "Image Playground"],
        correct: "Photos",
      },
    ],
    scenario: {
      instruction: "Send a photo from your library.",
      expectedTargets: ["photos"],
    },
  },
  {
    id: "send-a-sticker",
    title: "Send a sticker",
    steps: [
      { target: "stickers", instruction: "Look at Stickers to send one in your message" },
    ],
    quiz: [
      {
        question: "Which option sends a sticker?",
        options: ["Polls", "Stickers", "#images", "Message Effects"],
        correct: "Stickers",
      },
    ],
    scenario: {
      instruction: "Send a sticker.",
      expectedTargets: ["stickers"],
    },
  },
  {
    id: "create-a-poll",
    title: "Create a poll",
    steps: [
      { target: "polls", instruction: "Look at Polls to create one for the group to vote on" },
    ],
    quiz: [
      {
        question: "Which option creates a poll for the group?",
        options: ["Polls", "Send Later", "Genmoji", "Photos"],
        correct: "Polls",
      },
    ],
    scenario: {
      instruction: "Create a poll.",
      expectedTargets: ["polls"],
    },
  },
  {
    id: "schedule-a-message",
    title: "Schedule a message",
    steps: [
      { target: "send later", instruction: "Look at Send Later to schedule your message" },
    ],
    quiz: [
      {
        question: "Which option schedules a message to send later?",
        options: ["Send Later", "Polls", "Message Effects", "Filter"],
        correct: "Send Later",
      },
    ],
    scenario: {
      instruction: "Schedule a message to send later.",
      expectedTargets: ["send later"],
    },
  },
  {
    id: "create-a-genmoji",
    title: "Create a Genmoji",
    steps: [
      { target: "genmoji", instruction: "Look at Genmoji to create a custom emoji" },
    ],
    quiz: [
      {
        question: "Which option creates a custom emoji from a description?",
        options: ["Genmoji", "Emoji", "Stickers", "Image Playground"],
        correct: "Genmoji",
      },
    ],
    scenario: {
      instruction: "Create a Genmoji.",
      expectedTargets: ["genmoji"],
    },
  },
  {
    id: "generate-an-image",
    title: "Generate an image",
    steps: [
      { target: "image playground", instruction: "Look at Image Playground to generate an image" },
    ],
    quiz: [
      {
        question: "Which option generates an image to send?",
        options: ["Image Playground", "Genmoji", "#images", "Photos"],
        correct: "Image Playground",
      },
    ],
    scenario: {
      instruction: "Generate an image to send.",
      expectedTargets: ["image playground"],
    },
  },
  {
    id: "search-the-web-for-images",
    title: "Search the web for images",
    steps: [
      { target: "#images", instruction: "Look at #images to search the web for one to send" },
    ],
    quiz: [
      {
        question: "Which option searches the web for images?",
        options: ["#images", "Search", "Photos", "Image Playground"],
        correct: "#images",
      },
    ],
    scenario: {
      instruction: "Search the web for an image.",
      expectedTargets: ["#images"],
    },
  },
  {
    id: "add-a-message-effect",
    title: "Add a message effect",
    steps: [
      { target: "message effects", instruction: "Look at Message Effects to add a fun effect" },
    ],
    quiz: [
      {
        question: "Which option adds a visual effect like balloons or confetti?",
        options: ["Message Effects", "Genmoji", "Stickers", "Emoji"],
        correct: "Message Effects",
      },
    ],
    scenario: {
      instruction: "Add a message effect.",
      expectedTargets: ["message effects"],
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
let selectedLanguage = "en-US";

function connect() {
  socket = new WebSocket(BRIDGE_URL);
  socket.addEventListener("open", () => {
    setStatus(true, "Connected to Gaize");
    requestSetLanguage(selectedLanguage);
  });
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

function requestSetLanguage(languageCode) {
  if (!socket || socket.readyState !== WebSocket.OPEN) return;
  socket.send(JSON.stringify({ type: "set_language", language: languageCode }));
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
document.getElementById("language-select").addEventListener("change", (event) => {
  selectedLanguage = event.target.value;
  requestSetLanguage(selectedLanguage);
});

renderGoalList();
connect();
