// compare.js - prompt comparison page (our prompt-engineering demo).
// Pick a sample profile + prompt versions (plan_v1 to plan_v5) -> POST /api/plan/compare -> one column per version.
// This page is for judges and the team, so its own labels are in English; each plan is
// rendered with the normal plan cards in the profile's language.

import * as api from "./api.js";
import { setLanguage, t } from "./i18n.js";
import { el, formatInr, renderPlan } from "./plan_view.js";

const VERSIONS = [
  { id: "plan_v1", note: "Baseline prompt, free text" },
  { id: "plan_v2", note: "Rules + JSON schema" },
  { id: "plan_v3", note: "+ 2 worked examples" },
  { id: "plan_v4", note: "+ scheme documents (grounding)" },
  { id: "plan_v5", note: "+ language guidance (default)" },
];

const select = document.getElementById("sample-select");
const picks = document.getElementById("version-picks");
const runButton = document.getElementById("run-btn");
const status = document.getElementById("compare-status");
const results = document.getElementById("compare-results");
let samples = [];

// Version checkboxes (all ticked by default).
VERSIONS.forEach((v) => {
  picks.append(el("label", {}, el("input", { type: "checkbox", value: v.id, checked: true }), `${v.id} `, el("span", { class: "muted" }, `(${v.note})`)));
});

async function loadSamples() {
  try {
    samples = (await api.getSamples()).samples;
    select.replaceChildren(...samples.map((s) =>
      el("option", { value: String(s.index) }, `${s.index}. ${s.label} (${formatInr(s.profile.budget_inr)}, ${s.profile.location})`)));
  } catch (err) {
    status.replaceChildren(errorBox(err, loadSamples));
  }
}

function errorBox(err, retry) {
  return el("div", { class: "alert error", role: "alert" },
    el("p", {}, `Could not load: ${err.message}`),
    el("button", { class: "btn", type: "button", onclick: retry }, "Try again"));
}

async function runCompare() {
  const sample = samples[Number(select.value)];
  const versions = [...picks.querySelectorAll("input:checked")].map((i) => i.value);
  if (!sample || versions.length === 0) {
    status.replaceChildren(el("div", { class: "alert warn" }, "Pick a profile and at least one version."));
    return;
  }
  runButton.disabled = true;
  results.replaceChildren();
  status.replaceChildren(el("div", { class: "loading", role: "status" }, el("div", { class: "spinner", "aria-hidden": "true" }),
    el("p", {}, `Running ${versions.length} version(s)… this can take a few minutes with a real model.`)));
  try {
    const data = await api.comparePlans(sample.profile, versions, sample.language);
    status.replaceChildren();
    setLanguage(sample.language); // plan cards use the profile's language
    results.append(summaryTable(data.results), columns(data.results));
  } catch (err) {
    status.replaceChildren(errorBox(err, runCompare));
  } finally {
    runButton.disabled = false;
  }
}

function schemeCount(plan) {
  return plan.draft ? plan.draft.schemes.length : 0;
}

/** Summary row at the top: issues per version, so the v1 -> v4 improvement is visible at a glance. */
function summaryTable(rows) {
  return el("section", { class: "card" },
    el("h2", {}, "Summary"),
    el("div", { class: "table-scroll" }, el("table", {},
      el("thead", {}, el("tr", {},
        ["Version", "Validation", "Issues", "Schemes", "Attempts", "Seconds"].map((h, i) => el("th", { scope: "col", class: i > 1 ? "num" : "" }, h)))),
      el("tbody", {}, rows.map((r) => el("tr", {},
        el("th", { scope: "row" }, r.prompt_version),
        el("td", {}, r.passed === null ? "not checked (free text)" : r.passed ? "✔️ passed" : "❌ failed"),
        el("td", { class: "num" }, r.passed === null ? "-" : String(r.issue_codes.length)),
        el("td", { class: "num" }, String(schemeCount(r.plan))),
        el("td", { class: "num" }, r.plan.validation ? String(r.plan.validation.attempts) : "-"),
        el("td", { class: "num" }, r.seconds.toFixed(1)),
      ))),
    )),
  );
}

/** One column per version (stacked on phones). */
function columns(rows) {
  return el("div", { class: "compare-grid" }, rows.map((r) => {
    const v = r.plan.validation;
    return el("section", { class: "card" },
      el("h2", {}, r.prompt_version, " ",
        el("span", { class: `badge ${r.passed === null ? "" : r.passed ? "ok" : "bad"}` },
          r.passed === null ? "free text" : r.passed ? "passed" : "failed")),
      el("ul", { class: "plain" },
        el("li", {}, `Time: ${r.seconds.toFixed(1)} s`),
        el("li", {}, `Issues: ${v ? v.issues.length : "-"}${r.issue_codes.length ? ` (${r.issue_codes.join(", ")})` : ""}`),
        el("li", {}, `Schemes found: ${schemeCount(r.plan)}`),
        v && v.repairs_made.length ? el("li", {}, `Auto-fixes: ${v.repairs_made.length}`) : null,
        r.plan.financials ? el("li", {}, `Profit/month (expected): ${formatInr(r.plan.financials.scenarios.scenarios[1].profit)}`) : null,
      ),
      el("details", {}, el("summary", { class: "btn secondary small" }, "Show full output"),
        renderPlan(r.plan, { t, storageKey: `bs-compare-${r.prompt_version}` })),
    );
  }));
}

runButton.addEventListener("click", runCompare);
loadSamples();
