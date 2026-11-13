// plan_view.js - turns a BusinessPlan (from POST /api/plan) into DOM cards.
//
// Safety rule: text from the API (written by the LLM) is ALWAYS inserted as text nodes via el(),
// never with innerHTML, so it can never inject HTML or scripts.
// Money rule: every computed number (totals, profit, break-even...) comes from plan.financials
// (our calculator). The draft only supplies item names and the LLM's input amounts.

// ---------- Small DOM helper (used by every screen) ----------

/**
 * el("p", { class: "muted", onclick: fn, "aria-live": "polite" }, "text", childNode, ...)
 * Strings become text nodes (safe). null / false children are skipped.
 */
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (key === "class") node.className = value;
    else if (key === "checked" || key === "disabled" || key === "open") node[key] = Boolean(value);
    else if (key === "value") node.value = value;
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

// ---------- Formatting ----------

const inrFormat = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const numFormat = new Intl.NumberFormat("en-IN");

/** 150000 -> "₹1,50,000" (Indian digit grouping). */
export function formatInr(amount) {
  return amount === null || amount === undefined ? "-" : inrFormat.format(amount);
}
export function formatNum(n) {
  return numFormat.format(n);
}

// Validation codes we run (same list as app/plan_validation.py). Used for "Checks we ran".
export const CHECK_CODES = [
  "BUDGET_OVER", "LOW_RESERVE", "PRICE_BELOW_COST", "PRICE_OUT_OF_MARKET", "BREAK_EVEN_UNREALISTIC",
  "HALLUCINATED_SCHEME", "GUARANTEE_LANGUAGE", "MISSING_SECTION", "BAD_STEP_COUNT",
];

function card(icon, title, ...content) {
  return el("section", { class: "card" }, el("h2", {}, el("span", { class: "icon", "aria-hidden": "true" }, icon), title), ...content);
}

function list(items) {
  return el("ul", { class: "plain" }, items.map((item) => el("li", {}, item)));
}

function stat(label, value, extraClass = "") {
  return el("div", { class: `stat ${extraClass}` }, el("span", { class: "label" }, label), el("span", { class: "value" }, value));
}

// ---------- Cards ----------

function summaryCard(plan, t) {
  return card("📝", t("summary"), el("p", { id: "plan-summary" }, plan.draft.business_summary));
}

function costRows(items) {
  return items.map((c) => el("tr", {}, el("td", {}, c.name), el("td", { class: "num" }, formatInr(c.amount_inr))));
}

function budgetCard(plan, t) {
  const b = plan.financials.budget;
  const usedPct = Math.min(100, Math.max(0, b.percent_used));
  const table = el("div", { class: "table-scroll" }, el("table", {},
    el("thead", {}, el("tr", {}, el("th", { scope: "col" }, t("oneTime")), el("th", { scope: "col", class: "num" }, t("amount")))),
    el("tbody", {},
      costRows(plan.draft.startup_costs),
      el("tr", { class: "total" }, el("td", {}, t("oneTime")), el("td", { class: "num" }, formatInr(b.one_time_total))),
    ),
  ));
  const monthly = el("div", { class: "table-scroll" }, el("table", {},
    el("thead", {}, el("tr", {}, el("th", { scope: "col" }, t("monthly")), el("th", { scope: "col", class: "num" }, t("amount")))),
    el("tbody", {},
      costRows(plan.draft.fixed_monthly_costs),
      el("tr", { class: "total" }, el("td", {}, t("monthly")), el("td", { class: "num" }, formatInr(b.monthly_total))),
    ),
  ));
  // Horizontal bar: used vs left (pure CSS widths).
  const bar = el("div", {
    class: `budget-bar${b.over_budget ? " over" : ""}`,
    role: "img",
    "aria-label": t("budgetOf", { used: formatInr(b.startup_need), budget: formatInr(b.budget_inr) }),
  }, el("span", { class: "used", style: `width:${usedPct}%` }), el("span", { class: "left", style: `width:${100 - usedPct}%` }));

  const warnings = b.warnings.length
    ? el("div", { class: "alert warn", role: "note" }, el("strong", {}, "⚠️ " + t("checkThis")), list(b.warnings))
    : null;

  return card("💰", t("budgetTitle"),
    table, el("h3", {}, t("monthly")), monthly,
    el("div", { class: "stats" }, stat(t("totalStart"), formatInr(b.startup_need), "wide")),
    bar,
    el("div", { class: "legend" },
      el("span", {}, el("span", { class: "dot", style: `background:${b.over_budget ? "var(--red)" : "var(--green)"}` }),
        `${t("budgetUsed")}: ${formatInr(b.startup_need)}`),
      el("span", {}, el("span", { class: "dot", style: "background:#9fd3b6" }), `${t("budgetLeft")}: ${formatInr(b.remaining)}`),
    ),
    warnings,
  );
}

function pricingCard(plan, t) {
  const f = plan.financials;
  const unit = plan.draft.unit_name;
  const be = f.break_even;
  const scenarioLabel = { low: t("low"), expected: t("expected"), high: t("high") };
  // Sales count sits under the row label so only 3 money columns are needed (fits a 360px phone).
  const rows = f.scenarios.scenarios.map((s) => el("tr", {},
    el("th", { scope: "row" }, scenarioLabel[s.label] || s.label,
      el("span", { class: "sub" }, `${t("salesMonth")}: ${formatNum(s.units_per_month)}`)),
    el("td", { class: "num" }, formatInr(s.revenue)),
    el("td", { class: "num" }, formatInr(s.total_cost)),
    el("td", { class: `num ${s.profit >= 0 ? "profit-pos" : "profit-neg"}` }, formatInr(s.profit)),
  ));
  const pricingWarnings = [...f.unit.warnings, ...f.price.warnings];
  return card("📈", t("pricingTitle"),
    el("div", { class: "stats three" },
      stat(t("costPerUnit", { unit }), formatInr(f.unit.unit_cost)),
      stat(t("sellingPrice"), formatInr(f.unit.selling_price)),
      stat(t("profitPerUnit", { unit }), formatInr(f.unit.profit_per_unit),
        f.unit.profit_per_unit > 0 ? "profit-pos" : "profit-neg"),
    ),
    el("div", { class: "stats" },
      stat(t("breakEven"), be.possible
        ? t("breakEvenValue", { day: be.units_per_day, month: be.units_per_month })
        : t("breakEvenNo"), "wide"),
    ),
    pricingWarnings.length ? el("div", { class: "alert warn" }, list(pricingWarnings)) : null,
    el("h3", {}, t("scenarios")),
    el("p", { class: "estimate-note" }, "⚠️ " + t("estimatesNote")),
    el("div", { class: "table-scroll" }, el("table", { class: "scenario-table" },
      el("thead", {}, el("tr", {},
        el("th", { scope: "col" }, ""),
        el("th", { scope: "col", class: "num" }, t("revenue")), el("th", { scope: "col", class: "num" }, t("totalCost")),
        el("th", { scope: "col", class: "num" }, t("profit")),
      )),
      el("tbody", {}, rows),
    )),
    el("p", { class: "muted" }, f.payback_months !== null && f.payback_months !== undefined
      ? t("payback", { months: f.payback_months }) : t("paybackNone")),
    el("h3", {}, t("registrations")),
    list(f.compliance.flags),
  );
}

function marketingCard(plan, t) {
  return card("📣", t("marketingTitle"), list(plan.draft.marketing_ideas));
}

function schemesCard(plan, t) {
  const schemes = plan.draft.schemes;
  const body = schemes.length
    ? schemes.map((s) => el("div", { class: "scheme" },
        el("h3", {}, s.scheme),
        el("p", {}, s.why_it_fits),
        el("a", { href: s.source_url, target: "_blank", rel: "noopener noreferrer" }, "🔗 " + t("viewSource")),
        el("span", { class: "print-url" }, s.source_url), // shown only when printing
      ))
    : el("p", { class: "muted" }, t("noSchemes"));
  return card("🏛️", t("schemesTitle"), body);
}

/** Launch checklist; ticks are saved in localStorage under `storageKey`. */
function checklistCard(plan, t, storageKey) {
  const steps = plan.draft.launch_steps;
  let ticks = loadTicks(storageKey, steps.length);
  const counter = el("p", { class: "muted", "aria-live": "polite" });
  const updateCounter = () => {
    counter.textContent = t("stepsDone", { done: ticks.filter(Boolean).length, total: steps.length });
  };
  const items = steps.map((step, i) => {
    const meta = [t("days", { n: step.estimated_days })];
    if (step.estimated_cost_inr) meta.push(formatInr(step.estimated_cost_inr));
    const li = el("li", { class: ticks[i] ? "done" : "" });
    const box = el("input", {
      type: "checkbox",
      checked: ticks[i],
      onchange: (e) => {
        ticks[i] = e.target.checked;
        li.className = ticks[i] ? "done" : "";
        saveTicks(storageKey, ticks);
        updateCounter();
      },
    });
    li.append(el("label", {}, box, el("span", {},
      el("span", { class: "step-title" }, `${i + 1}. ${step.title}`),
      el("span", {}, step.detail),
      el("span", { class: "step-meta" }, " · " + meta.join(" · ")),
    )));
    return li;
  });
  updateCounter();
  return card("✅", t("checklistTitle"), counter, el("ul", { class: "checklist" }, items));
}

function loadTicks(key, n) {
  try {
    const saved = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.from({ length: n }, (_, i) => Boolean(saved[i]));
  } catch {
    return Array(n).fill(false);
  }
}

function saveTicks(key, ticks) {
  try {
    localStorage.setItem(key, JSON.stringify(ticks));
  } catch {
    /* storage blocked: ticks just are not remembered */
  }
}

function assumptionsCard(plan, t) {
  return card("🤔", t("assumptionsTitle"),
    el("h3", {}, t("assumptions")), list(plan.draft.assumptions),
    el("h3", {}, t("risks")), list(plan.draft.risks),
  );
}

/** "Checks we ran": the validation report, so users (and judges) can see the safety layer. */
export function checksCard(plan, t) {
  const v = plan.validation;
  const failedCodes = new Set(v.issues.map((i) => i.code));
  const passed = CHECK_CODES.filter((c) => !failedCodes.has(c));
  return el("details", { class: "card checks" },
    el("summary", {}, "🛡️ " + t("checksTitle") + " ",
      el("span", { class: `badge ${v.passed ? "ok" : "bad"}` }, v.passed ? t("checksPassed") : t("checksFailed"))),
    el("ul", { class: "check-list" }, passed.map((c) => el("li", {}, "✔️ " + t(`check_${c}`)))),
    v.issues.length
      ? el("div", { class: "alert warn" }, el("strong", {}, t("toLookAt")),
          list(v.issues.map((i) => `${t(`check_${i.code}`)}: ${i.message}`)))
      : null,
    v.repairs_made.length
      ? el("div", {}, el("h3", {}, t("fixesMade")), list(v.repairs_made))
      : null,
    el("p", { class: "muted" }, t("attempts", { n: v.attempts })),
  );
}

// ---------- Whole plan ----------

/**
 * Render a BusinessPlan.
 * options.t          - translate function from i18n.js
 * options.storageKey - localStorage key for checklist ticks
 * Returns a DocumentFragment with the cards in the agreed order.
 */
export function renderPlan(plan, { t, storageKey = "bs-checklist" }) {
  const frag = document.createDocumentFragment();

  // plan_v1 (baseline prompt) is free text: show it as-is, no cards.
  if (plan.raw_text) {
    frag.append(el("div", { class: "alert warn" }, t("rawNote")));
    frag.append(card("📝", t("planTitle"), el("pre", { class: "raw" }, plan.raw_text)));
    return frag;
  }

  // Problems that are still there after validation are shown first, never hidden.
  if (plan.warnings && plan.warnings.length) {
    // Warnings look like "BUDGET_OVER: message"; users only need the message.
    const messages = plan.warnings.map((w) => w.replace(/^[A-Z_]+:\s*/, ""));
    frag.append(el("div", { class: "alert warn", role: "note" }, el("strong", {}, "⚠️ " + t("checkThis")), list(messages)));
  }
  frag.append(
    summaryCard(plan, t),
    budgetCard(plan, t),
    pricingCard(plan, t),
    marketingCard(plan, t),
    schemesCard(plan, t),
    checklistCard(plan, t, storageKey),
    assumptionsCard(plan, t),
  );
  if (plan.validation) frag.append(checksCard(plan, t));
  return frag;
}
