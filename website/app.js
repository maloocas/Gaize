// Connects to the local companion app's WebSocket bridge and drives the
// goal -> quiz/scenario -> feedback loop off events reported from real
// gaze/voice actions in the target app (Messages, for the demo).

const BRIDGE_URL = "ws://localhost:8765";

const QUIZ_EXPLANATIONS = {
  Compose: "Compose opens a blank conversation so you can choose a recipient and write a message.",
  "The To field": "The To field identifies who will receive the message; the Message field holds what you want to say.",
  Send: "Send delivers the message or selected content to the current conversation.",
  Attach: "Attach opens the choices for adding content such as photos and files.",
  Photos: "Photos opens your photo library so you can choose an existing picture.",
  Search: "Search looks across conversations and message text for a person or phrase.",
  FaceTime: "FaceTime starts a call with the person or group in the current conversation.",
  Emoji: "Emoji inserts a standard emoji into the message you are writing.",
  Filter: "Filter narrows the conversation list, making particular kinds of messages easier to find.",
  Stickers: "Stickers opens your sticker collection so you can choose one to send.",
  Polls: "Polls creates choices that everyone in a group conversation can vote on.",
  "Send Later": "Send Later lets you choose a future date and time instead of delivering the message immediately.",
  Genmoji: "Genmoji creates a custom emoji from a description.",
  "Image Playground": "Image Playground generates a new image; Photos selects one that already exists.",
  "#images": "#images searches the web for an image you can add to the conversation.",
  "Message Effects": "Message Effects adds an animation such as balloons or confetti when the message is sent.",
};

const GOALS = [
  {
    id: "send-a-message",
    title: "Send a message",
    steps: [
      { target: "compose", instruction: "Look at the compose button to start a new conversation" },
      { target: "to:", instruction: "Say “type” followed by the recipient's name, or type it into the To field" },
      { target: "message", instruction: "Say your message, or type it in the message box" },
      { target: "send", instruction: "Say “send” (or press Return) to send it" },
    ],
    quiz: [
      {
        question: "Which button starts a brand-new conversation?",
        options: ["Send", "Compose", "Details", "Search"],
        correct: "Compose",
      },
      {
        question: "Where do you put the name of who you're messaging?",
        options: ["The To field", "The Message field", "Search", "Details"],
        correct: "The To field",
      },
      {
        question: "Which button actually sends your typed message?",
        options: ["Attach", "Send", "Camera", "Back"],
        correct: "Send",
      },
    ],
    scenario: {
      instruction: "Start a new conversation, add a recipient, write a message, and send it.",
      expectedTargets: ["compose", "to:", "message", "send"],
    },
  },
  {
    id: "add-an-attachment",
    title: "Add an attachment",
    steps: [
      { target: "add", instruction: "Look at Attach and select the + button to open attachment choices" },
      { target: "photos", instruction: "Look at Photos and select it to open your photo library" },
      { target: "*", highlight: false, instruction: "Choose any photo from the library to add it to your message" },
      { target: "send", instruction: "Check the photo preview, then look at Send and select it" },
    ],
    quiz: [
      {
        question: "Which button lets you attach a photo or file?",
        options: ["Emoji", "Attach", "App Store", "Details"],
        correct: "Attach",
      },
      {
        question: "After tapping Attach, which option picks a photo from your library?",
        options: ["Photos", "Stickers", "Genmoji", "Filter"],
        correct: "Photos",
      },
    ],
    scenario: {
      instruction: "Attach a photo to your message and send it.",
      expectedTargets: ["add", "photos", "*", "send"],
    },
  },
  {
    id: "search-a-conversation",
    title: "Search your messages",
    steps: [
      { target: "search", instruction: "Look at the search field, then say or type a name" },
    ],
    quiz: [
      {
        question: "You remember a phrase from an older message but not which chat it was in. What should you use?",
        options: ["Filter", "Search", "Details", "Compose"],
        correct: "Search",
      },
      {
        question: "What can you say after selecting the Search field?",
        options: ["Type followed by a name or phrase", "Select followed by Send", "Compose followed by a date", "Explain followed by a contact"],
        correct: "Type followed by a name or phrase",
        explanation: "After selecting Search, say “type” followed by the person or phrase you want to find.",
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
        question: "You are already viewing a conversation and want to talk face-to-face. Which control should you choose?",
        options: ["Camera", "FaceTime", "Emoji", "Attach"],
        correct: "FaceTime",
      },
      {
        question: "What happens when you activate FaceTime from a conversation?",
        options: ["It starts a call with that conversation", "It attaches a recorded video", "It opens the photo library", "It sends your draft"],
        correct: "It starts a call with that conversation",
        explanation: "The FaceTime control calls the person or group in the conversation you are viewing.",
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
      { target: "send", instruction: "Look at the send button to send it" },
    ],
    quiz: [
      {
        question: "You want to add a standard smiley to your draft. Which control should you use?",
        options: ["Emoji", "Filter", "Search", "Back"],
        correct: "Emoji",
      },
      {
        question: "After choosing the emoji, what completes the task?",
        options: ["Send", "Compose", "Filter", "Details"],
        correct: "Send",
      },
    ],
    scenario: {
      instruction: "Add an emoji to your message and send it.",
      expectedTargets: ["emoji", "send"],
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
        question: "You only want to see a particular category of conversations. Which control should you use?",
        options: ["Filter", "Search", "Attach", "Details"],
        correct: "Filter",
      },
      {
        question: "When should you use Search instead of Filter?",
        options: ["When looking for a specific person or phrase", "When narrowing by conversation category", "When attaching a photo", "When starting a call"],
        correct: "When looking for a specific person or phrase",
        explanation: "Search finds specific text or people; Filter narrows the list by category.",
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
      { target: "photos", instruction: "Look at Photos to pick one from your library" },
      { target: "send", instruction: "Look at the send button to send it" },
    ],
    quiz: [
      {
        question: "You want to use a picture that is already in your library. Which option should you choose?",
        options: ["Photos", "Stickers", "Genmoji", "Image Playground"],
        correct: "Photos",
      },
      {
        question: "Which option would you use instead if you wanted to create a brand-new image?",
        options: ["Image Playground", "Photos", "Filter", "Send Later"],
        correct: "Image Playground",
      },
    ],
    scenario: {
      instruction: "Send a photo from your library.",
      expectedTargets: ["photos", "send"],
    },
  },
  {
    id: "send-a-sticker",
    title: "Send a sticker",
    steps: [
      { target: "stickers", instruction: "Look at Stickers to pick one" },
      { target: "send", instruction: "Look at the send button to send it" },
    ],
    quiz: [
      {
        question: "You want to respond with something from your sticker collection. Which option should you open?",
        options: ["Polls", "Stickers", "#images", "Message Effects"],
        correct: "Stickers",
      },
      {
        question: "After selecting a sticker, which control delivers it?",
        options: ["Send", "Search", "Filter", "FaceTime"],
        correct: "Send",
      },
    ],
    scenario: {
      instruction: "Send a sticker.",
      expectedTargets: ["stickers", "send"],
    },
  },
  {
    id: "create-a-poll",
    title: "Create a poll",
    steps: [
      { target: "polls", instruction: "Look at Polls to set one up" },
      { target: "send", instruction: "Look at the send button to send it" },
    ],
    quiz: [
      {
        question: "A group chat needs to vote on a meeting time. Which option should you choose?",
        options: ["Polls", "Send Later", "Genmoji", "Photos"],
        correct: "Polls",
      },
      {
        question: "What should you do after adding the choices to your poll?",
        options: ["Send it to the conversation", "Open Search", "Choose FaceTime", "Filter the chat list"],
        correct: "Send it to the conversation",
        explanation: "Once the poll choices are ready, send the poll so everyone in the conversation can vote.",
      },
    ],
    scenario: {
      instruction: "Create a poll and send it.",
      expectedTargets: ["polls", "send"],
    },
  },
  {
    id: "schedule-a-message",
    title: "Schedule a message",
    steps: [
      { target: "message", instruction: "Type your message" },
      { target: "send later", instruction: "Look at Send Later to schedule it instead of sending now" },
    ],
    quiz: [
      {
        question: "Your draft should arrive tomorrow morning instead of now. Which option should you use?",
        options: ["Send Later", "Polls", "Message Effects", "Filter"],
        correct: "Send Later",
      },
      {
        question: "When do you choose the delivery time?",
        options: ["After writing the message and opening Send Later", "Before opening the conversation", "After sending the message", "Inside the Search field"],
        correct: "After writing the message and opening Send Later",
        explanation: "Write the message first, then use Send Later to select its delivery date and time.",
      },
    ],
    scenario: {
      instruction: "Write a message and schedule it to send later.",
      expectedTargets: ["message", "send later"],
    },
  },
  {
    id: "create-a-genmoji",
    title: "Create a Genmoji",
    steps: [
      { target: "genmoji", instruction: "Look at Genmoji to describe one" },
      { target: "send", instruction: "Look at the send button to send it" },
    ],
    quiz: [
      {
        question: "You want an emoji that does not already exist. Which option can create one from your description?",
        options: ["Genmoji", "Emoji", "Stickers", "Image Playground"],
        correct: "Genmoji",
      },
      {
        question: "How is Genmoji different from the Emoji control?",
        options: ["Genmoji creates a custom emoji", "Genmoji searches old messages", "Genmoji schedules delivery", "Genmoji starts a video call"],
        correct: "Genmoji creates a custom emoji",
        explanation: "Emoji opens standard emoji; Genmoji creates a new one from words you provide.",
      },
    ],
    scenario: {
      instruction: "Create a Genmoji and send it.",
      expectedTargets: ["genmoji", "send"],
    },
  },
  {
    id: "generate-an-image",
    title: "Generate an image",
    steps: [
      { target: "image playground", instruction: "Look at Image Playground to generate one" },
      { target: "send", instruction: "Look at the send button to send it" },
    ],
    quiz: [
      {
        question: "You want Messages to create a new picture from an idea. Which option should you use?",
        options: ["Image Playground", "Genmoji", "#images", "Photos"],
        correct: "Image Playground",
      },
      {
        question: "Which option should you use for a picture that already exists in your library?",
        options: ["Photos", "Image Playground", "Genmoji", "Message Effects"],
        correct: "Photos",
      },
    ],
    scenario: {
      instruction: "Generate an image and send it.",
      expectedTargets: ["image playground", "send"],
    },
  },
  {
    id: "search-the-web-for-images",
    title: "Search the web for images",
    steps: [
      { target: "#images", instruction: "Look at #images and say or type what you're looking for" },
      { target: "send", instruction: "Look at the send button to send it" },
    ],
    quiz: [
      {
        question: "You want to find a reaction image online without leaving Messages. Which option should you use?",
        options: ["#images", "Search", "Photos", "Image Playground"],
        correct: "#images",
      },
      {
        question: "What should you provide after opening #images?",
        options: ["Words describing the image you want", "A delivery date", "A contact's phone number", "Poll choices"],
        correct: "Words describing the image you want",
        explanation: "Use a short search phrase to find a relevant web image, then choose and send it.",
      },
    ],
    scenario: {
      instruction: "Search the web for an image and send it.",
      expectedTargets: ["#images", "send"],
    },
  },
  {
    id: "add-a-message-effect",
    title: "Add a message effect",
    steps: [
      { target: "message effects", instruction: "Look at Message Effects to pick one" },
      { target: "send", instruction: "Look at the send button to send it" },
    ],
    quiz: [
      {
        question: "You want your message to arrive with balloons or confetti. Which option should you use?",
        options: ["Message Effects", "Genmoji", "Stickers", "Emoji"],
        correct: "Message Effects",
      },
      {
        question: "When should you choose the effect?",
        options: ["After writing the message and before sending it", "Before selecting a conversation", "After the message was delivered", "While searching old messages"],
        correct: "After writing the message and before sending it",
        explanation: "Write the message, choose Message Effects, pick an animation, and then send it.",
      },
    ],
    scenario: {
      instruction: "Add a message effect and send it.",
      expectedTargets: ["message effects", "send"],
    },
  },
];

const question = (prompt, options, correct, explanation) => ({
  question: prompt,
  options,
  correct,
  ...(explanation ? { explanation } : {}),
});

// Each lesson combines its focused questions above with these transfer and
// sequencing questions. Five questions is enough to check recall, order, and
// when to use the skill without turning the review into a long exam.
const EXTRA_QUIZ_QUESTIONS = {
  "send-a-message": [
    question("Which order correctly starts a new message?", ["Compose → To field → Message field → Send", "To field → Send → Compose → Message field", "Search → Compose → Send → To field", "Compose → Send → To field → Message field"], "Compose → To field → Message field → Send", "Start the conversation, choose its recipient, write the message, and then send it."),
    question("After selecting the To field, what phrase enters a contact hands-free?", ["Type followed by the contact's name", "Send followed by the contact's name", "Explain followed by the message", "Compose followed by the message"], "Type followed by the contact's name", "Say “type” and then the contact's name; Gaize enters only the name."),
  ],
  "add-an-attachment": [
    question("What should you do before choosing Photos?", ["Open Attach", "Open Filter", "Press Send", "Start FaceTime"], "Open Attach"),
    question("You selected the wrong photo. What should you avoid doing until it is corrected?", ["Send", "Search", "Compose", "Filter"], "Send", "Review the selected attachment before sending it to the conversation."),
    question("Which sequence adds and delivers a library photo?", ["Attach → Photos → choose a photo → Send", "Photos → Filter → Send Later", "Compose → FaceTime → Send", "Search → Photos → Filter"], "Attach → Photos → choose a photo → Send", "Open attachment choices, select Photos, choose the picture, and send it."),
  ],
  "search-a-conversation": [
    question("Search returns too many results. What should you try next?", ["Use a more specific name or phrase", "Press Send", "Start FaceTime", "Open Message Effects"], "Use a more specific name or phrase", "A distinctive word, phrase, or full contact name narrows the results."),
    question("Which task is Search designed for?", ["Finding an existing conversation or message", "Creating a custom emoji", "Scheduling a draft", "Adding confetti"], "Finding an existing conversation or message"),
    question("Which sequence searches hands-free?", ["Select Search → say “type” and a phrase", "Select Compose → say “send”", "Select Filter → say “FaceTime”", "Select Attach → say “search”"], "Select Search → say “type” and a phrase", "Focus Search first, then dictate the name or phrase you want to find."),
  ],
  "start-a-facetime-call": [
    question("Before starting FaceTime, what should you verify?", ["You are in the intended conversation", "A photo is attached", "A poll is open", "Search is empty"], "You are in the intended conversation", "FaceTime calls the person or group in the current conversation."),
    question("Which control records or adds media instead of starting a live call?", ["Camera", "FaceTime", "Filter", "Send Later"], "Camera", "Camera handles media; FaceTime starts the live call."),
    question("Which sequence starts the intended video call?", ["Open the conversation → choose FaceTime", "Choose Attach → choose Photos", "Choose Search → choose Send", "Choose Filter → choose Camera"], "Open the conversation → choose FaceTime", "Open the correct conversation before activating FaceTime."),
  ],
  "add-an-emoji": [
    question("Which option creates a new custom emoji rather than choosing a standard one?", ["Genmoji", "Emoji", "Stickers", "Photos"], "Genmoji"),
    question("Where does the chosen emoji appear before it is sent?", ["In the message draft", "In the Search field", "In the conversation filter", "In the To field"], "In the message draft", "A selected emoji becomes part of the draft, where you can review it before sending."),
    question("Which sequence sends a standard emoji?", ["Emoji → choose one → Send", "Genmoji → Filter → Send Later", "Photos → Emoji → Search", "Compose → FaceTime → Emoji"], "Emoji → choose one → Send", "Open Emoji, choose one, then send the completed draft."),
  ],
  "filter-conversations": [
    question("What does Filter change?", ["Which conversations are shown in the list", "Who receives your next message", "When a draft is delivered", "Which camera is used"], "Which conversations are shown in the list", "Filtering changes the visible conversation list without searching message text."),
    question("You want to find one contact by name. Which control is more direct?", ["Search", "Filter", "Attach", "Message Effects"], "Search"),
    question("You want to narrow the list by category rather than keywords. Which control fits?", ["Filter", "Search", "Compose", "FaceTime"], "Filter"),
  ],
  "send-a-photo": [
    question("What should you check before sending the selected photo?", ["That the preview is the photo you intended", "That Search is empty", "That Filter is active", "That FaceTime is open"], "That the preview is the photo you intended", "Review the preview before delivering a photo to the conversation."),
    question("Which control completes delivery after a photo is selected?", ["Send", "Compose", "Filter", "Search"], "Send"),
    question("Which sequence sends an existing picture?", ["Photos → choose a picture → Send", "Image Playground → Filter → Send Later", "Search → Photos → Compose", "Genmoji → Photos → FaceTime"], "Photos → choose a picture → Send", "Choose an existing picture in Photos, review it, and send it."),
  ],
  "send-a-sticker": [
    question("How is a sticker different from a standard emoji in this lesson?", ["It comes from the Stickers collection", "It schedules the message", "It starts a call", "It filters conversations"], "It comes from the Stickers collection", "Use Stickers for saved or created sticker artwork and Emoji for standard emoji characters."),
    question("What should you check before sending a sticker?", ["That the selected sticker is the one you intended", "That FaceTime is active", "That Search has results", "That a poll is open"], "That the selected sticker is the one you intended"),
    question("Which sequence sends a sticker?", ["Stickers → choose one → Send", "Emoji → Filter → Compose", "Polls → Photos → Send", "Search → Stickers → FaceTime"], "Stickers → choose one → Send", "Open Stickers, choose the right sticker, and send it."),
  ],
  "create-a-poll": [
    question("What information must a useful poll contain?", ["A question and choices", "A contact and delivery time", "A photo and effect", "A search phrase and filter"], "A question and choices", "A poll needs a clear question and distinct choices for participants."),
    question("Where can people vote after you send the poll?", ["In the group conversation", "In your photo library", "In Search", "In FaceTime"], "In the group conversation"),
    question("Which sequence creates a group vote?", ["Polls → add choices → Send", "Filter → Compose → Search", "Photos → Genmoji → Send", "FaceTime → Polls → Attach"], "Polls → add choices → Send", "Set up the poll and its choices before sending it to the group."),
  ],
  "schedule-a-message": [
    question("What is the key difference between Send and Send Later?", ["Send delivers now; Send Later delivers at a chosen time", "Send adds a photo; Send Later adds an emoji", "Send searches; Send Later filters", "There is no difference"], "Send delivers now; Send Later delivers at a chosen time", "Choose based on when the recipient should receive the message."),
    question("What should you verify before scheduling?", ["The message and delivery time are correct", "A poll is open", "The photo library is empty", "FaceTime is active"], "The message and delivery time are correct"),
    question("Which sequence schedules a draft?", ["Write the message → Send Later → choose a time", "Send → write the message → Filter", "Search → choose a time → Compose", "Attach → FaceTime → Send Later"], "Write the message → Send Later → choose a time", "Finish the draft before selecting its future delivery time."),
  ],
  "create-a-genmoji": [
    question("What should your Genmoji description communicate?", ["The custom emoji you want to create", "A delivery time", "A contact to call", "A phrase from an old message"], "The custom emoji you want to create", "A clear visual description helps Genmoji produce the intended result."),
    question("What should you do after choosing the generated result?", ["Send it", "Filter conversations", "Start FaceTime", "Open Search"], "Send it"),
    question("Which sequence creates and delivers a custom emoji?", ["Genmoji → describe it → choose one → Send", "Emoji → Search → Filter", "Photos → Polls → Send Later", "Compose → FaceTime → Genmoji"], "Genmoji → describe it → choose one → Send", "Describe, select, and review the generated emoji before sending."),
  ],
  "generate-an-image": [
    question("What should you give Image Playground?", ["A description of the image you want", "A contact's phone number", "A delivery date only", "A conversation filter"], "A description of the image you want", "Describe the scene or subject you want Image Playground to create."),
    question("What should you do before sending the generated result?", ["Review that it matches your intent", "Open FaceTime", "Clear Search", "Create a poll"], "Review that it matches your intent"),
    question("Which sequence creates and sends a new image?", ["Image Playground → describe → choose → Send", "Photos → Filter → Compose", "#images → Polls → Send Later", "Genmoji → FaceTime → Search"], "Image Playground → describe → choose → Send", "Generate the image, select the preferred result, and send it."),
  ],
  "search-the-web-for-images": [
    question("How is #images different from Photos?", ["#images searches online; Photos uses your library", "#images schedules delivery", "#images starts a call", "They do exactly the same thing"], "#images searches online; Photos uses your library", "Choose based on whether the picture is online or already saved."),
    question("What should you check before sending a web image?", ["That the selected result fits the conversation", "That Filter is active", "That FaceTime is open", "That the To field is blank"], "That the selected result fits the conversation"),
    question("Which sequence finds and sends an online image?", ["#images → search phrase → choose → Send", "Photos → Compose → Filter", "Search → FaceTime → Send Later", "Genmoji → Polls → Attach"], "#images → search phrase → choose → Send", "Search with useful words, choose the right result, and send it."),
  ],
  "add-a-message-effect": [
    question("What does a message effect change?", ["How the message appears when delivered", "Who receives the message", "The conversation search results", "The scheduled delivery time"], "How the message appears when delivered", "Effects add presentation and animation without changing the recipient or text."),
    question("Which feature should you use for a visual object instead of an animation?", ["Stickers", "Message Effects", "Filter", "Send Later"], "Stickers", "Stickers are visual items; Message Effects animate the delivery of a message."),
    question("Which sequence sends a message with an effect?", ["Write message → Message Effects → choose effect → Send", "Filter → Search → Compose", "Photos → FaceTime → Send Later", "Polls → Genmoji → Attach"], "Write message → Message Effects → choose effect → Send", "Finish the message, select its effect, and then send it."),
  ],
};

GOALS.forEach((goal) => {
  goal.quiz = [...goal.quiz, ...(EXTRA_QUIZ_QUESTIONS[goal.id] || [])];
  if (goal.quiz.length !== 5) {
    throw new Error(`Expected 5 quiz questions for ${goal.id}, found ${goal.quiz.length}`);
  }
});

let socket = null;
let currentGoal = null;
let currentStepIndex = 0;
let quizAnswers = [];
let quizIndex = 0;
let scenarioProgress = 0;
let mode = "goal-list"; // goal-list | goal-detail | goal | quiz | scenario | feedback
let selectedLanguage = "en-US";

function connect() {
  socket = new WebSocket(BRIDGE_URL);
  socket.addEventListener("open", () => {
    setStatus(true, "Connected to Gaize");
    requestSetLanguage(selectedLanguage);
    reportState();
    if (mode !== "goal") clearHighlight();
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

// The highlight box only belongs to an active goal - leaving it (home,
// goal detail, quiz, scenario) removes the box from the screen.
function clearHighlight() {
  if (!socket || socket.readyState !== WebSocket.OPEN) return;
  socket.send(JSON.stringify({ type: "clear_highlight" }));
}

function requestHighlight(target) {
  if (!target || !socket || socket.readyState !== WebSocket.OPEN) return;
  socket.send(JSON.stringify({ type: "highlight", target }));
}

function requestOpenMessages() {
  if (!socket || socket.readyState !== WebSocket.OPEN) return;
  socket.send(JSON.stringify({ type: "open_messages" }));
}

function handleCompanionEvent(msg) {
  if (msg.type === "voice_action") {
    handleVoiceAction(msg.action);
    return;
  }

  if (msg.type !== "action_completed") return;
  const title = (msg.title || "").toLowerCase();
  const keyTargets = { to_field: "to:", message_field: "message" };
  const canonicalTarget = keyTargets[msg.key] || (msg.key || "").replaceAll("_", " ");
  const matches = (expectedTarget) =>
    expectedTarget === "*" || title.includes(expectedTarget) || canonicalTarget === expectedTarget;

  if (mode === "goal") {
    const expected = currentGoal.steps[currentStepIndex];
    if (expected && matches(expected.target)) {
      currentStepIndex += 1;
      renderGoal();
    }
  } else if (mode === "scenario") {
    const expectedTarget = currentGoal.scenario.expectedTargets[scenarioProgress];
    if (expectedTarget && matches(expectedTarget)) {
      scenarioProgress += 1;
      renderScenario();
    }
  }
}

// Direct voice navigation of this page's own buttons ("home", "back",
// "learn", "quiz", "scenario") - sent by the companion app regardless of
// gaze, so it works even if the target button is too small/precise to
// reliably hit with gaze alone. Each action is a no-op outside the screen
// it applies to (e.g. "learn" only makes sense from goal-detail).
function handleVoiceAction(action) {
  switch (action) {
    case "home":
    case "back":
      renderGoalList();
      break;
    case "learn":
      if (mode === "goal-detail") beginLearning();
      break;
    case "quiz":
      if (mode === "goal-detail" || mode === "goal") startQuiz();
      break;
    case "scenario":
      if (mode === "goal-detail" || mode === "goal") startScenario();
      break;
    default:
      // "start_goal:<id>" - the AI assistant picked the goal that answers
      // the user's spoken question; start it so each step is highlighted.
      // "open_goal:<id>" - the user said a goal's name; open its page,
      // same as clicking the goal card.
      if (action && action.startsWith("quiz_say:")) {
        handleQuizSpeech(action.slice("quiz_say:".length));
      } else if (action && action.startsWith("open_goal:")) {
        const goal = GOALS.find((g) => g.id === action.slice("open_goal:".length));
        if (goal) showGoalDetail(goal);
      } else if (action && action.startsWith("start_goal:")) {
        const goal = GOALS.find((g) => g.id === action.slice("start_goal:".length));
        if (goal) {
          showGoalDetail(goal);
          beginLearning();
        }
      }
  }
}

// ---- Goal list ----

function renderGoalList() {
  mode = "goal-list";
  clearHighlight();
  show("intro", "goals");
  hide("goal-detail", "active-goal", "quiz");

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
    card.addEventListener("click", () => showGoalDetail(goal));
    li.appendChild(card);
    list.appendChild(li);
  });
}

function showGoalDetail(goal) {
  currentGoal = goal;
  mode = "goal-detail";
  clearHighlight();
  hide("intro", "goals", "active-goal", "quiz");
  show("goal-detail");

  document.getElementById("goal-detail-title").textContent = goal.title;

  const preview = document.getElementById("steps-preview");
  preview.innerHTML = "";
  goal.steps.forEach((step) => {
    const li = document.createElement("li");
    li.textContent = step.instruction;
    preview.appendChild(li);
  });
}

function beginLearning() {
  currentStepIndex = 0;
  mode = "goal";
  hide("goal-detail", "quiz");
  show("active-goal");
  document.getElementById("followup-choice").hidden = true;
  renderGoal();
  requestOpenMessages();
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
    if (step.highlight !== false) requestHighlight(step.target);
  } else {
    stepEl.textContent = "Nice — you finished the steps. Ready to check what you learned?";
    followup.hidden = false;
    // The companion clears the highlight box and shows a "Goal complete"
    // popup over the app the user is in.
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "goal_complete", title: currentGoal.title }));
    }
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
  clearHighlight();
  quizIndex = 0;
  quizAnswers = [];
  hide("goal-detail", "active-goal");
  show("quiz");
  document.getElementById("quiz-heading").textContent = `${currentGoal.title} check`;
  renderQuizQuestion();
}

function shuffled(options) {
  const result = [...options];
  for (let i = result.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [result[i], result[j]] = [result[j], result[i]];
  }
  return result;
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

  let answered = false;
  shuffled(question.options).forEach((option) => {
    const button = document.createElement("button");
    button.className = "quiz-option";
    button.textContent = option;
    button.addEventListener("click", () => {
      if (answered) return;
      answered = true;

      const isCorrect = option === question.correct;
      const explanation = question.explanation || QUIZ_EXPLANATIONS[question.correct] || "Review the tutorial step and try it in Messages.";
      quizAnswers.push({
        question: question.question,
        answer: option,
        correct: question.correct,
        explanation,
      });

      options.querySelectorAll("button").forEach((choice) => {
        choice.disabled = true;
        if (choice.textContent === question.correct) choice.classList.add("correct");
        if (choice === button && !isCorrect) choice.classList.add("incorrect");
      });

      const feedback = document.createElement("p");
      feedback.className = `quiz-answer-feedback ${isCorrect ? "correct" : "incorrect"}`;
      feedback.textContent = isCorrect
        ? `Correct. ${explanation}`
        : `Not quite. ${question.correct} is the right choice. ${explanation}`;
      body.appendChild(feedback);

      const nextButton = document.createElement("button");
      nextButton.className = "btn-primary quiz-next";
      nextButton.textContent = quizIndex + 1 === currentGoal.quiz.length ? "See results" : "Next question";
      nextButton.addEventListener("click", () => {
        quizIndex += 1;
        renderQuizQuestion();
      });
      body.appendChild(nextButton);
      nextButton.focus();
    });
    options.appendChild(button);
  });

  body.appendChild(options);
}

// Spoken quiz input, relayed by the companion. Answers are labeled A-D on
// screen (see .quiz-option::before); say the letter ("B", "option C") or the
// answer itself. Recognition spells a lone letter as a word - "bee", "see".
const LETTER_SOUNDS = [
  ["a", "ay", "eh"],
  ["b", "be", "bee", "bea"],
  ["c", "see", "sea", "si", "cee"],
  ["d", "dee", "de"],
];
const ORDINALS = [
  ["1", "one", "first"],
  ["2", "two", "second"],
  ["3", "three", "third"],
  ["4", "four", "fourth"],
];

function normalizeSpeech(text) {
  return text.toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
}

function handleQuizSpeech(text) {
  const said = normalizeSpeech(text);
  if (!said) return;

  if (mode === "feedback") {
    if (/\b(try again|retry|again)\b/.test(said)) startQuiz();
    else if (/\b(back|goals|done|finish)\b/.test(said)) renderGoalList();
    return;
  }
  if (mode !== "quiz") return;

  const next = document.querySelector("#quiz-body .quiz-next");
  if (next && /\b(next|continue|results|done)\b/.test(said)) {
    next.click();
    return;
  }

  const buttons = [...document.querySelectorAll("#quiz-body .quiz-option")];
  if (!buttons.length || buttons[0].disabled) return;

  // Letter or number: the whole phrase, optionally after a lead-in word.
  const choice = said.replace(/^(option|answer|letter|choice|number|choose|pick|it s|its|is it|the)\s+/, "")
    .replace(/\s+(one)$/, "");
  let index = LETTER_SOUNDS.findIndex((sounds) => sounds.includes(choice));
  if (index < 0) index = ORDINALS.findIndex((words) => words.includes(choice));
  let pick = index >= 0 ? buttons[index] : null;

  // Or the answer's own text ("compose", "the to field").
  if (!pick) {
    pick = buttons.find((b) => said.includes(normalizeSpeech(b.textContent)))
      || buttons.find((b) => said.length >= 3 && normalizeSpeech(b.textContent).includes(said));
  }
  if (pick) pick.click();
}

// ---- Scenario (live-tracked in the real app) ----

function startScenario() {
  mode = "scenario";
  scenarioProgress = 0;
  hide("goal-detail", "active-goal");
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

  const target = scenario.expectedTargets[scenarioProgress];
  if (target !== "*") requestHighlight(target);
}

// ---- Feedback ----

function renderFeedback() {
  mode = "feedback";
  // Lets the companion know results are showing ("try again" / "back to goals").
  reportState();
  const body = document.getElementById("quiz-body");
  body.innerHTML = "";
  const completedQuiz = quizAnswers.length > 0;

  const title = document.createElement("h3");
  title.className = "feedback-title";

  if (completedQuiz) {
    const correctCount = quizAnswers.filter((a) => a.answer === a.correct).length;
    const perfect = correctCount === quizAnswers.length;
    title.textContent = perfect
      ? `Great work — ${correctCount} of ${quizAnswers.length} correct.`
      : `${correctCount} of ${quizAnswers.length} correct. Review the notes below.`;
    body.appendChild(title);

    quizAnswers.forEach((a) => {
      const row = document.createElement("div");
      const isCorrect = a.answer === a.correct;
      row.className = `feedback-row ${isCorrect ? "correct" : "incorrect"}`;
      const q = document.createElement("span");
      q.className = "feedback-row-question";
      q.textContent = isCorrect
        ? `Correct: ${a.correct}. ${a.explanation}`
        : `Your answer: ${a.answer}. Correct answer: ${a.correct}. ${a.explanation}`;
      row.appendChild(q);
      body.appendChild(row);
    });
  } else {
    title.textContent = "Scenario complete — you did it correctly.";
    body.appendChild(title);
  }

  const actions = document.createElement("div");
  actions.className = "feedback-actions";

  if (completedQuiz) {
    const retryBtn = document.createElement("button");
    retryBtn.className = "btn-ghost";
    retryBtn.textContent = "Try quiz again";
    retryBtn.addEventListener("click", startQuiz);
    actions.appendChild(retryBtn);
  }

  const doneBtn = document.createElement("button");
  doneBtn.className = "btn-primary";
  doneBtn.textContent = "Back to goals";
  doneBtn.addEventListener("click", renderGoalList);
  actions.appendChild(doneBtn);
  body.appendChild(actions);
}

// ---- DOM helpers ----

function show(...ids) {
  ids.forEach((id) => (document.getElementById(id).hidden = false));
  reportState();
}

// Every screen change goes through show(), so this tells the companion
// (and its log) which screen the site is on.
function reportState() {
  if (!socket || socket.readyState !== WebSocket.OPEN) return;
  // Wait a frame so the newly shown screen has been laid out.
  requestAnimationFrame(() => {
    // Screen-space centers of visible buttons (content area assumed to sit
    // at the bottom of the window, as on macOS Chrome) - used by the
    // automated select tests to aim the cursor.
    const chromeTop = window.outerHeight - window.innerHeight;
    const buttons = [...document.querySelectorAll("button")]
      .filter((b) => b.offsetParent !== null)
      .map((b) => {
        const r = b.getBoundingClientRect();
        return {
          t: b.textContent.replace(/\s+/g, " ").trim().slice(0, 40),
          x: Math.round(window.screenX + r.left + r.width / 2),
          y: Math.round(window.screenY + chromeTop + r.top + r.height / 2),
        };
      });
    socket.send(JSON.stringify({ type: "page_state", mode, goal: currentGoal ? currentGoal.id : null, buttons }));
  });
}

function hide(...ids) {
  ids.forEach((id) => (document.getElementById(id).hidden = true));
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

document.getElementById("home-link").addEventListener("click", renderGoalList);
document.getElementById("back-from-detail").addEventListener("click", renderGoalList);
document.getElementById("btn-learn").addEventListener("click", beginLearning);
document.getElementById("cancel-goal").addEventListener("click", renderGoalList);
document.getElementById("cancel-quiz").addEventListener("click", renderGoalList);
document.getElementById("btn-quiz").addEventListener("click", startQuiz);
document.getElementById("btn-scenario").addEventListener("click", startScenario);
document.getElementById("language-select").addEventListener("change", (event) => {
  selectedLanguage = event.target.value;
  requestSetLanguage(selectedLanguage);
});

renderGoalList();
connect();
