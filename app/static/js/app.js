// app.js - the Business Starter web app: one state object + one render function per screen.
//
// Screens:  welcome (language) or resume -> chat (intake) -> loading -> plan
// Phase 6: the session id is kept on the phone, so a returning user can continue their plan;
// the checklist, the next-step card and the question box on the plan screen use the server.
// Every screen function returns DOM built with el() (text is always inserted safely).

import * as api from "./api.js";
import { LANGUAGES, getLocale, savedLanguage, setLanguage, t } from "./i18n.js";
import { askCard, checklistCard, guideCard, micButton } from "./plan_tools.js";
import { el, formatInr, renderPlan } from "./plan_view.js";

// ---------------------------------------------------------------------------
// State: everything the app knows lives in this one object.
// ---------------------------------------------------------------------------
const REQUIRED_FIELDS = ["business_idea", "budget_inr", "location", "skills", "target_customers"];
const OPTIONAL_FIELDS = ["time_available", "sales_channel", "experience", "extra_notes"];
const BUDGET_CHIPS = [5000, 10000, 20000, 50000];
const LOADING_KEYS = ["loading1", "loading2", "loading3", "loading4"];

const state = {
  language: "en",
  screen: "welcome",   // welcome | resume | chat | loading | error | plan
  resume: null,        // saved session found on start-up (offered as "Continue")
  sessionId: null,
  profile: null,
  missing: [...REQUIRED_FIELDS],
  isComplete: false,
  messages: [],        // [{ role: "agent" | "user", text }]
  plan: null,
  sampleIndex: null,   // set when the plan comes from "Try a sample"
  busy: false,
  loadingTimer: null,
  error: null,         // { err, retry, back }
  editing: null,       // field currently being edited in "Your details"
  detailsOpen: false,  // is the "Your details" card expanded?
};

const root = document.getElementById("app");
let ui = {}; // references to live chat elements (log, input...) while the chat screen is shown

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------
function show(screen) {
  state.screen = screen;
  render();
}

function render() {
  clearInterval(state.loadingTimer);
  ui = {};
  const screens = {
    welcome: welcomeScreen, resume: resumeScreen, chat: chatScreen, loading: loadingScreen, error: errorScreen, plan: planScreen,
  };
  root.replaceChildren(screens[state.screen]());
  translateStatic();
  // Move focus to the new screen's heading so keyboard and screen-reader users know it changed.
  const heading = root.querySelector("h1");
  if (heading) {
    heading.setAttribute("tabindex", "-1");
    heading.focus({ preventScroll: true });
  }
  window.scrollTo(0, 0);
}

/** Translate the fixed parts of index.html (header, footer) marked with data-i18n. */
function translateStatic() {
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  document.title = t("appName");
}

function errorMessage(err) {
  const key = { offline: "errOffline", timeout: "errTimeout", server: "errServer", notFound: "errNotFound" }[err && err.kind];
  return t(key || "errGeneric");
}

/** Friendly error box with a Retry button (never a raw stack trace). */
function errorBox(err, retry) {
  return el("div", { class: "alert error", role: "alert" },
    el("p", {}, "😟 " + errorMessage(err)),
    err && err.kind === "notFound"
      ? el("button", { class: "btn", type: "button", onclick: startOver }, t("startOver"))
      : retry ? el("button", { class: "btn", type: "button", onclick: retry }, "🔄 " + t("retry")) : null,
  );
}

// ---------------------------------------------------------------------------
// Screen 1: welcome + language
// ---------------------------------------------------------------------------
function welcomeScreen() {
  return el("div", { class: "welcome" },
    el("div", { class: "hero-icon", "aria-hidden": "true" }, "🌱"),
    el("h1", {}, t("appName")),
    el("p", { class: "muted" }, t("tagline")),
    el("h2", { id: "lang-heading" }, t("chooseLanguage")),
    el("div", { class: "lang-grid", role: "group", "aria-labelledby": "lang-heading" },
      LANGUAGES.map((lang) => el("button", {
        class: "btn secondary lang-btn",
        type: "button",
        lang: lang.code,
        "aria-pressed": String(lang.code === state.language),
        onclick: () => chooseLanguage(lang.code),
      }, lang.native)),
    ),
    el("button", { class: "link-btn", type: "button", onclick: loadSample }, "✨ " + t("trySample")),
  );
}

function chooseLanguage(code) {
  setLanguage(code);
  state.language = code;
  startChat();
}

// ---------------------------------------------------------------------------
// Screen 2: intake chat
// ---------------------------------------------------------------------------
async function startChat() {
  showLoading([t("loadingStart")]);
  try {
    const data = await api.createSession(state.language);
    state.sessionId = data.session_id;
    rememberSession(state.sessionId);
    state.messages = [{ role: "agent", text: data.reply }];
    applyChatData(data);
    show("chat");
  } catch (err) {
    showError(err, startChat);
  }
}

function applyChatData(data) {
  state.profile = data.profile;
  state.missing = data.missing_fields;
  state.isComplete = data.is_complete;
}

function chatScreen() {
  ui.log = el("div", { class: "chat-log", role: "log", "aria-live": "polite", "aria-label": t("chatTitle") });
  state.messages.forEach((m) => ui.log.append(bubble(m)));

  ui.progress = el("div", { class: "progress-wrap" });
  ui.chips = el("div", { class: "chips no-print" });
  ui.error = el("div", { "aria-live": "assertive" });
  ui.createArea = el("div");
  ui.details = el("div");

  ui.input = el("input", {
    id: "chat-input", type: "text", autocomplete: "off", enterkeyhint: "send",
    placeholder: t("inputPlaceholder"),
  });
  ui.send = el("button", { class: "btn icon-btn", type: "submit", "aria-label": t("send") }, "➤");
  const form = el("form", {
    class: "chat-form",
    onsubmit: (e) => {
      e.preventDefault();
      sendMessage(ui.input.value);
    },
  }, el("label", { for: "chat-input", class: "sr-only" }, t("inputLabel")), ui.input, micButton(ui.input, state.language), ui.send);

  const screen = el("div", {},
    el("h1", {}, t("chatTitle")),
    ui.progress, ui.log, ui.chips, form, ui.error, ui.createArea, ui.details,
    el("div", { class: "btn-row" }, el("button", { class: "btn ghost", type: "button", onclick: startOver }, "↺ " + t("startOver"))),
  );
  updateChatExtras();
  // Scroll the log to the newest message once it is on the page.
  requestAnimationFrame(() => { ui.log.scrollTop = ui.log.scrollHeight; });
  return screen;
}

function bubble(message) {
  return el("div", { class: `bubble ${message.role}` }, message.text);
}

/** Progress bar, quick-reply chips, "Create my plan" button and the details card. */
function updateChatExtras() {
  const total = REQUIRED_FIELDS.length;
  const done = total - state.missing.length;
  ui.progress.replaceChildren(
    el("div", { class: "progress-label" }, el("span", {}, t("progress", { done, total })), el("span", {}, `${Math.round((done / total) * 100)}%`)),
    el("div", { class: "progress-bar", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": String(total), "aria-valuenow": String(done) },
      el("span", { style: `width:${(done / total) * 100}%` })),
  );

  // Budget chips only when the next question is about the budget.
  ui.chips.replaceChildren(...(state.missing[0] === "budget_inr" && !state.isComplete
    ? BUDGET_CHIPS.map((amount) => el("button", {
        class: "chip", type: "button", onclick: () => sendMessage(formatInr(amount)),
      }, formatInr(amount)))
    : []));

  ui.createArea.replaceChildren(state.isComplete
    ? el("button", { class: "btn big", type: "button", onclick: generatePlan }, "📋 " + t("createPlan"))
    : "");
  ui.details.replaceChildren(detailsCard());
}

async function sendMessage(text, { retry = false } = {}) {
  text = (text || "").trim();
  if (!text || state.busy) return;
  state.busy = true;
  ui.error.replaceChildren();
  if (!retry) {
    state.messages.push({ role: "user", text });
    ui.log.append(bubble({ role: "user", text }));
    ui.input.value = "";
  }
  const typing = el("div", { class: "typing" }, t("typing"), el("span", { class: "dots", "aria-hidden": "true" }, el("span", {}, "."), el("span", {}, "."), el("span", {}, ".")));
  ui.log.append(typing);
  ui.log.scrollTop = ui.log.scrollHeight;
  ui.send.disabled = true;
  try {
    const data = await api.sendChat(state.sessionId, text);
    typing.remove();
    state.messages.push({ role: "agent", text: data.reply });
    ui.log.append(bubble({ role: "agent", text: data.reply }));
    applyChatData(data);
    updateChatExtras();
  } catch (err) {
    typing.remove();
    ui.error.replaceChildren(errorBox(err, () => sendMessage(text, { retry: true })));
  } finally {
    state.busy = false;
    if (ui.send) ui.send.disabled = false;
    if (ui.log) ui.log.scrollTop = ui.log.scrollHeight;
    if (ui.input && !state.isComplete) ui.input.focus({ preventScroll: true });
  }
}

// ----- "Your details" card with an Edit button per field (PATCH /api/session/{id}/profile) -----
function detailsCard() {
  const p = state.profile || {};
  const fields = [...REQUIRED_FIELDS, ...OPTIONAL_FIELDS.filter((f) => p[f])];
  return el("details", {
    class: "card",
    open: state.detailsOpen || state.editing !== null,
    ontoggle: (e) => { state.detailsOpen = e.target.open; },
  },
    el("summary", {}, "👤 " + t("yourDetails")),
    el("ul", { class: "field-list" }, fields.map((field) => fieldRow(field, p[field]))),
  );
}

function displayValue(field, value) {
  if (value === null || value === undefined || value === "") return null;
  return field === "budget_inr" ? formatInr(value) : String(value);
}

function fieldRow(field, value) {
  const shown = displayValue(field, value);
  if (state.editing === field) {
    const input = el("input", { id: `edit-${field}`, type: field === "budget_inr" ? "text" : "text", inputmode: field === "budget_inr" ? "numeric" : null, value: value ?? "" });
    const error = el("div", { "aria-live": "assertive" });
    const save = async () => {
      try {
        const data = await api.patchProfile(state.sessionId, { [field]: input.value.trim() || null });
        applyChatData(data);
        state.editing = null;
        updateChatExtras();
      } catch (err) {
        error.replaceChildren(el("div", { class: "alert error" }, err.kind === "client" && field === "budget_inr" ? t("errBudget") : errorMessage(err)));
      }
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); save(); } });
    requestAnimationFrame(() => input.focus());
    return el("li", {},
      el("label", { class: "field-label", for: `edit-${field}` }, t(`f_${field}`)),
      el("div", { class: "field-edit" }, input,
        el("button", { class: "btn small", type: "button", onclick: save }, t("save")),
        el("button", { class: "btn small secondary", type: "button", onclick: () => { state.editing = null; updateChatExtras(); } }, t("cancel"))),
      error,
    );
  }
  return el("li", {}, el("div", { class: "field-row" },
    el("div", { class: "field-text" },
      el("span", { class: "field-label" }, t(`f_${field}`)),
      el("span", { class: `field-value${shown ? "" : " empty"}` }, shown || t("notGiven"))),
    el("button", {
      class: "btn small secondary", type: "button", "aria-label": `${t("edit")}: ${t(`f_${field}`)}`,
      onclick: () => { state.editing = field; updateChatExtras(); },
    }, "✏️ " + t("edit")),
  ));
}

// ---------------------------------------------------------------------------
// Loading + error screens
// ---------------------------------------------------------------------------
let loadingMessages = [];

function showLoading(messages) {
  loadingMessages = messages;
  show("loading");
}

function loadingScreen() {
  const text = el("p", { class: "loading-text", "aria-live": "polite" }, loadingMessages[0]);
  let i = 0;
  if (loadingMessages.length > 1) {
    // Cycle through friendly messages while the plan is being made (10-40 seconds).
    setTimeout(() => {
      state.loadingTimer = setInterval(() => {
        i = (i + 1) % loadingMessages.length;
        text.textContent = loadingMessages[i];
      }, 3500);
    });
  }
  return el("div", { class: "loading", role: "status" },
    el("div", { class: "spinner", "aria-hidden": "true" }),
    el("h1", { class: "sr-only" }, t("appName")),
    text,
    loadingMessages.length > 1 ? el("p", { class: "muted" }, t("loadingNote")) : null,
  );
}

function showError(err, retry, back = null) {
  state.error = { err, retry, back };
  show("error");
}

function errorScreen() {
  const { err, retry, back } = state.error;
  return el("div", {},
    el("h1", { class: "sr-only" }, t("appName")),
    errorBox(err, retry),
    back ? el("button", { class: "btn secondary", type: "button", onclick: back }, "← " + t("editDetails")) : null,
  );
}

// ---------------------------------------------------------------------------
// Screen 3: the plan
// ---------------------------------------------------------------------------
async function generatePlan() {
  showLoading(LOADING_KEYS.map((k) => t(k)));
  try {
    state.plan = await api.createPlan(state.sessionId);
    state.sampleIndex = null;
    show("plan");
  } catch (err) {
    showError(err, generatePlan, () => show("chat"));
  }
}

async function loadSample() {
  showLoading(LOADING_KEYS.map((k) => t(k)));
  try {
    const { samples } = await api.getSamples();
    // Always the first sample (healthy meal service, Rs 20,000): it matches the offline mock plan,
    // so demos look the same every time. The plan is still written in the chosen language.
    const sample = samples[0];
    state.plan = await api.previewPlan(sample.profile, state.language);
    state.sampleIndex = sample.index;
    state.sessionId = null;
    show("plan");
  } catch (err) {
    showError(err, loadSample, startOver);
  }
}

function planScreen() {
  const plan = state.plan;
  const storageKey = `bs-checklist-sample-${state.sampleIndex}`; // samples only: own plans use the server
  const guide = state.sessionId ? guideCard(state.sessionId) : null; // "Your next step" at the top
  return el("div", {},
    el("div", { class: "plan-head" },
      el("h1", {}, t("planTitle")),
      state.sampleIndex !== null ? el("span", { class: "badge" }, t("sampleBadge")) : null,
    ),
    el("div", { class: "btn-row no-print" },
      el("button", { class: "btn", type: "button", onclick: () => window.print() }, "⬇️ " + t("downloadPdf")),
      listenButton(plan),
    ),
    state.sessionId ? guide : null,
    renderPlan(plan, { t, storageKey, checklist: state.sessionId && plan.draft ? checklistCard(state.sessionId, () => guide.refresh()) : null }),
    state.sessionId ? askCard(state.sessionId, state.language) : askNeedsPlanCard(),
    el("div", { class: "btn-row no-print" },
      state.sessionId ? el("button", { class: "btn secondary", type: "button", onclick: () => show("chat") }, "✏️ " + t("editDetails")) : null,
      el("button", { class: "btn secondary", type: "button", onclick: startOver }, "↺ " + t("startOver")),
    ),
  );
}

/** Sample plans have no session, so questions need the user's own plan. */
function askNeedsPlanCard() {
  return el("section", { class: "card ask no-print" },
    el("h2", {}, el("span", { class: "icon", "aria-hidden": "true" }, "💬"), t("askTitle")),
    el("p", { class: "muted" }, t("askNeedsPlan")),
    el("button", { class: "btn secondary", type: "button", onclick: startOver }, t("startNew")),
  );
}

/** "Listen": reads the summary aloud if the phone has a voice for this language. Hidden otherwise. */
function listenButton(plan) {
  if (!("speechSynthesis" in window) || !plan.draft) return null;
  const button = el("button", { class: "btn secondary", type: "button", hidden: true }, "🔊 " + t("listen"));
  const findVoice = () => {
    const prefix = state.language.toLowerCase();
    return window.speechSynthesis.getVoices().find((v) => v.lang.toLowerCase().replace("_", "-").startsWith(prefix));
  };
  const refresh = () => { button.hidden = !findVoice(); };
  refresh();
  window.speechSynthesis.addEventListener("voiceschanged", refresh, { once: true });
  button.addEventListener("click", () => {
    if (window.speechSynthesis.speaking) {
      window.speechSynthesis.cancel();
      button.textContent = "🔊 " + t("listen");
      return;
    }
    const utterance = new SpeechSynthesisUtterance(plan.draft.business_summary);
    utterance.voice = findVoice();
    utterance.lang = getLocale(state.language);
    utterance.onend = () => { button.textContent = "🔊 " + t("listen"); };
    button.textContent = "⏹ " + t("stop");
    window.speechSynthesis.speak(utterance);
  });
  return button;
}

function startOver() {
  forgetSession();
  Object.assign(state, {
    sessionId: null, profile: null, missing: [...REQUIRED_FIELDS], isComplete: false,
    messages: [], plan: null, sampleIndex: null, editing: null, error: null, resume: null,
  });
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  show("welcome");
}

// ---------------------------------------------------------------------------
// Resume: the session id is saved on the phone (Phase 6)
// ---------------------------------------------------------------------------
const SESSION_KEY = "bs-session";

function rememberSession(id) {
  try { localStorage.setItem(SESSION_KEY, id); } catch { /* storage blocked: no resume */ }
}
function forgetSession() {
  try { localStorage.removeItem(SESSION_KEY); } catch { /* ignore */ }
}
function savedSessionId() {
  try { return localStorage.getItem(SESSION_KEY); } catch { return null; }
}

/** Put a session from the server (GET /api/session/{id}) into the app state. */
function loadSessionIntoState(session) {
  state.sessionId = session.session_id;
  state.profile = session.profile;
  state.messages = session.messages.map((m) => ({ role: m.role === "user" ? "user" : "agent", text: m.content }));
  state.missing = REQUIRED_FIELDS.filter((f) => session.profile[f] === null || session.profile[f] === "");
  state.isComplete = state.missing.length === 0;
  state.plan = session.plan;
  state.sampleIndex = null;
}

function resumeScreen() {
  const session = state.resume;
  const idea = session.profile.business_idea;
  const text = session.plan ? t("resumeWithPlan", { idea }) : idea ? t("resumeChat", { idea }) : t("resumeChatEmpty");
  return el("div", { class: "welcome" },
    el("div", { class: "hero-icon", "aria-hidden": "true" }, "👋"),
    el("h1", {}, t("resumeTitle")),
    el("p", {}, text),
    el("div", { class: "btn-row" },
      el("button", {
        class: "btn big", type: "button",
        onclick: () => { loadSessionIntoState(session); show(session.plan ? "plan" : "chat"); },
      }, session.plan ? "📋 " + t("continuePlan") : "💬 " + t("continueChat")),
    ),
    el("button", { class: "btn secondary big", type: "button", onclick: startOver }, "↺ " + t("startNew")),
  );
}

/** On start-up: if this phone has a saved session that still exists, offer to continue it. */
async function init() {
  const id = savedSessionId();
  if (id) {
    try {
      const session = await api.getSession(id);
      setLanguage(session.profile.language);
      state.language = session.profile.language;
      state.resume = session;
      show("resume");
      return;
    } catch (err) {
      if (err.kind === "notFound") forgetSession(); // e.g. the database was reset
    }
  }
  show("welcome");
}

// ---------------------------------------------------------------------------
// Start-up
// ---------------------------------------------------------------------------

// Print / "Download PDF": open every collapsible section so nothing is hidden on paper.
window.addEventListener("beforeprint", () => {
  document.querySelectorAll("details").forEach((d) => { d.dataset.wasOpen = d.open; d.open = true; });
});
window.addEventListener("afterprint", () => {
  document.querySelectorAll("details").forEach((d) => { d.open = d.dataset.wasOpen === "true"; });
});

// Offline banner.
const banner = document.getElementById("offline-banner");
function updateOnline() {
  banner.hidden = navigator.onLine;
  banner.textContent = navigator.onLine ? "" : "📶 " + t("errOffline");
}
window.addEventListener("online", updateOnline);
window.addEventListener("offline", updateOnline);

state.language = savedLanguage() || "en";
setLanguage(state.language);
updateOnline();
init();

// Expose state for debugging in the browser console (read it, do not change it).
window.__businessStarter = state;
