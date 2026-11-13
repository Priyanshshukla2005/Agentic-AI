// plan_tools.js - Phase 6 widgets on the plan screen, all backed by the server:
//   guideCard()     "Your next step"  (GET /api/guide/{id})
//   checklistCard() launch checklist  (GET/PATCH/POST/DELETE /api/checklist/{id})
//   askCard()       question thread   (POST /api/ask, GET /api/ask/{id}/history)
//   micButton()     speech input for any text box (Web Speech API, hidden if not supported)
//
// Each function returns a DOM node at once and fills it when the data arrives.
// All API text is inserted with el() (text nodes), never as HTML.

import * as api from "./api.js";
import { getLocale, t } from "./i18n.js";
import { el, formatInr } from "./plan_view.js";

function cardShell(icon, title) {
  const body = el("div", { "aria-live": "polite" }, el("p", { class: "muted" }, t("loadingStart")));
  const node = el("section", { class: "card no-print-empty" },
    el("h2", {}, el("span", { class: "icon", "aria-hidden": "true" }, icon), title), body);
  return { node, body };
}

function friendlyError(err) {
  const key = { offline: "errOffline", timeout: "errTimeout", server: "errServer", notFound: "errNotFound" }[err && err.kind];
  return t(key || "errGeneric");
}

function errorWithRetry(err, retry) {
  return el("div", { class: "alert error", role: "alert" },
    el("p", {}, "😟 " + friendlyError(err)),
    el("button", { class: "btn small", type: "button", onclick: retry }, "🔄 " + t("retry")));
}

// ---------------------------------------------------------------------------
// Mic button (shared by the intake chat and the Ask box)
// ---------------------------------------------------------------------------
export function micButton(input, language) {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) return null; // not supported: no button at all
  let recognizer = null;
  const placeholder = input.placeholder;
  const button = el("button", { class: "btn secondary icon-btn", type: "button", "aria-label": t("mic"), title: t("mic") }, "🎤");
  button.addEventListener("click", () => {
    if (recognizer) {
      recognizer.stop();
      return;
    }
    recognizer = new Recognition();
    recognizer.lang = getLocale(language); // e.g. hi-IN, ta-IN
    recognizer.interimResults = false;
    recognizer.maxAlternatives = 1;
    recognizer.onresult = (event) => {
      input.value = event.results[0][0].transcript;
      input.focus();
    };
    recognizer.onend = () => {
      recognizer = null;
      button.classList.remove("listening");
      button.setAttribute("aria-label", t("mic"));
      input.placeholder = placeholder;
    };
    recognizer.onerror = () => recognizer && recognizer.stop();
    button.classList.add("listening");
    button.setAttribute("aria-label", t("micListening"));
    input.placeholder = t("micListening");
    recognizer.start();
  });
  return button;
}

// ---------------------------------------------------------------------------
// "Your next step" card
// ---------------------------------------------------------------------------
export function guideCard(sessionId) {
  const { node, body } = cardShell("👉", t("nextStepTitle"));
  node.classList.add("guide-card");
  const load = async () => {
    try {
      const g = await api.getGuide(sessionId);
      body.replaceChildren(
        el("p", { class: "guide-progress" }, "🎉 " + g.progress_line),
        g.next_step ? el("p", { class: "guide-step" }, el("strong", {}, g.next_step.title)) : null,
        g.tip ? el("p", { class: "muted" }, "💡 " + g.tip) : null,
      );
    } catch (err) {
      body.replaceChildren(errorWithRetry(err, load));
    }
  };
  load();
  node.refresh = load; // the checklist calls this after a tick
  return node;
}

// ---------------------------------------------------------------------------
// Launch checklist (server)
// ---------------------------------------------------------------------------

/** Phase 5 kept ticks in localStorage by step number. Send them to the server once, then forget them. */
async function migrateOldTicks(sessionId, items) {
  const key = `bs-checklist-${sessionId}`;
  let old = null;
  try {
    old = JSON.parse(localStorage.getItem(key) || "null");
  } catch {
    return null;
  }
  if (!Array.isArray(old)) return null;
  let latest = null;
  const planItems = items.filter((i) => !i.is_custom);
  for (const [index, ticked] of old.entries()) {
    const item = planItems[index];
    if (ticked && item && !item.done) latest = await api.setStepDone(sessionId, item.id, true);
  }
  try {
    localStorage.removeItem(key);
  } catch {
    /* ignore */
  }
  return latest;
}

function progressRing(progress) {
  // Pure CSS ring: conic-gradient fills `percent` of the circle.
  return el("div", {
    class: "ring",
    role: "img",
    style: `--pct:${progress.percent}`,
    "aria-label": t("stepsDone", { done: progress.done, total: progress.total }),
  }, el("span", {}, `${progress.percent}%`));
}

export function checklistCard(sessionId, onChange = () => {}) {
  const { node, body } = cardShell("✅", t("checklistTitle"));
  let data = null; // { items, progress } from the server
  const status = el("div", { "aria-live": "assertive" });

  const render = () => {
    const list = el("ul", { class: "checklist" }, data.items.map(itemRow));
    const input = el("input", { id: "new-step", type: "text", maxlength: "200", placeholder: t("addStepPlaceholder") });
    const form = el("form", {
      class: "chat-form no-print",
      onsubmit: async (e) => {
        e.preventDefault();
        const title = input.value.trim();
        if (!title) return;
        try {
          data = await api.addStep(sessionId, title);
          render();
          onChange(data);
        } catch (err) {
          status.replaceChildren(el("div", { class: "alert error" }, t("saveError")));
        }
      },
    }, el("label", { for: "new-step", class: "sr-only" }, t("addStep")), input,
      el("button", { class: "btn", type: "submit" }, "➕ " + t("add")));

    body.replaceChildren(
      el("div", { class: "progress-row" }, progressRing(data.progress),
        el("p", { class: "muted" }, t("stepsDone", { done: data.progress.done, total: data.progress.total }))),
      list,
      el("h3", { class: "no-print" }, t("addStep")),
      form,
      status,
    );
  };

  const itemRow = (item) => {
    const meta = [];
    if (item.estimated_days) meta.push(t("days", { n: item.estimated_days }));
    if (item.estimated_cost_inr) meta.push(formatInr(item.estimated_cost_inr));
    const li = el("li", { class: item.done ? "done" : "" });
    const box = el("input", {
      type: "checkbox",
      checked: item.done,
      onchange: async (e) => {
        // Optimistic UI: show the tick at once, undo it if the server says no.
        const wanted = e.target.checked;
        li.className = wanted ? "done" : "";
        status.replaceChildren();
        try {
          data = await api.setStepDone(sessionId, item.id, wanted);
          render();
          onChange(data);
        } catch (err) {
          e.target.checked = !wanted;
          li.className = !wanted ? "done" : "";
          status.replaceChildren(el("div", { class: "alert error" }, t("saveError")));
        }
      },
    });
    li.append(el("div", { class: "check-row" },
      el("label", {}, box, el("span", {},
        el("span", { class: "step-title" }, item.title,
          item.is_custom ? el("span", { class: "badge" }, t("customBadge")) : null),
        item.detail ? el("span", {}, item.detail) : null,
        meta.length ? el("span", { class: "step-meta" }, " · " + meta.join(" · ")) : null,
      )),
      item.is_custom
        ? el("button", {
            class: "btn small ghost no-print", type: "button", "aria-label": `${t("deleteStep")}: ${item.title}`,
            onclick: async () => {
              try {
                data = await api.deleteStep(sessionId, item.id);
                render();
                onChange(data);
              } catch (err) {
                status.replaceChildren(el("div", { class: "alert error" }, t("saveError")));
              }
            },
          }, "🗑️")
        : null,
    ));
    return li;
  };

  const load = async () => {
    try {
      data = await api.getChecklist(sessionId);
      const migrated = await migrateOldTicks(sessionId, data.items);
      if (migrated) data = migrated;
      render();
    } catch (err) {
      body.replaceChildren(errorWithRetry(err, load));
    }
  };
  load();
  return node;
}

// ---------------------------------------------------------------------------
// "Ask a question" thread
// ---------------------------------------------------------------------------
export function askCard(sessionId, language) {
  const log = el("div", { class: "chat-log ask-log", role: "log", "aria-live": "polite", "aria-label": t("askTitle") });
  const status = el("div", { "aria-live": "assertive" });
  const input = el("input", { id: "ask-input", type: "text", maxlength: "1000", autocomplete: "off", placeholder: t("askPlaceholder") });
  const send = el("button", { class: "btn icon-btn", type: "submit", "aria-label": t("askSend") }, "➤");
  let busy = false;

  const answerBubble = (m) => el("div", { class: `bubble ${m.role === "user" ? "user" : "agent"}` },
    m.content,
    (m.used_tools || []).some((name) => name.startsWith("calculate"))
      ? el("span", { class: "bubble-note" }, "🧮 " + t("calcUsed")) : null,
    ...(m.sources || []).map((s) => el("a", {
      class: "source-link", href: s.source_url, target: "_blank", rel: "noopener noreferrer",
    }, `🔗 ${t("source")}: ${s.scheme}`)),
  );

  const scrollDown = () => { log.scrollTop = log.scrollHeight; };

  const submit = async (question) => {
    question = (question || "").trim();
    if (!question || busy) return;
    busy = true;
    send.disabled = true;
    status.replaceChildren();
    log.querySelector(".ask-empty")?.remove();
    log.append(answerBubble({ role: "user", content: question }));
    input.value = "";
    const typing = el("div", { class: "typing" }, t("askThinking"),
      el("span", { class: "dots", "aria-hidden": "true" }, el("span", {}, "."), el("span", {}, "."), el("span", {}, ".")));
    log.append(typing);
    scrollDown();
    try {
      const r = await api.ask(sessionId, question);
      typing.remove();
      log.append(answerBubble({ role: "assistant", content: r.answer, sources: r.sources, used_tools: r.used_tools }));
      if (r.next_step_hint) log.append(el("p", { class: "muted small-note" }, "👉 " + t("nextStepHint", { title: r.next_step_hint })));
    } catch (err) {
      typing.remove();
      status.replaceChildren(errorWithRetry(err, () => submit(question)));
    } finally {
      busy = false;
      send.disabled = false;
      scrollDown();
    }
  };

  const chips = el("div", { class: "chips" }, ["sugg1", "sugg2", "sugg3", "sugg4"].map((key) =>
    el("button", { class: "chip", type: "button", onclick: () => submit(t(key)) }, t(key))));

  const form = el("form", { class: "chat-form", onsubmit: (e) => { e.preventDefault(); submit(input.value); } },
    el("label", { for: "ask-input", class: "sr-only" }, t("askTitle")), input, micButton(input, language), send);

  // Earlier questions and answers (they survive a server restart).
  api.getAskHistory(sessionId).then(({ messages }) => {
    if (messages.length === 0) log.append(el("p", { class: "muted ask-empty" }, t("askIntro")));
    messages.forEach((m) => log.append(answerBubble(m)));
    scrollDown();
  }).catch(() => log.append(el("p", { class: "muted ask-empty" }, t("askIntro"))));

  return el("section", { class: "card ask no-print" },
    el("h2", {}, el("span", { class: "icon", "aria-hidden": "true" }, "💬"), t("askTitle")),
    log, chips, form, status);
}
