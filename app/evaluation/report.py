"""Phase 7: turn evaluation rows into data/eval/report.md and the charts in docs/charts/."""
import os
import re
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Optional

from app.config import BASE_DIR, settings
from app.evaluation import charts
from app.models import LANGUAGES

HUMAN_START = "<!-- human-review:start -->"
HUMAN_END = "<!-- human-review:end -->"
LANGUAGE_REPORT = BASE_DIR / "data" / "eval" / "language_report.md"
LANGUAGE_AWARE = ("plan_v4", "plan_v5")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _num(value) -> Optional[float]:
    if value in ("", None):
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return 1.0 if value.lower() == "true" else 0.0
    try:
        return float(value)
    except ValueError:
        return None


def avg(rows: list[dict], key: str) -> Optional[float]:
    values = [v for v in (_num(r.get(key)) for r in rows) if v is not None]
    return round(mean(values), 2) if values else None


def pct(rows: list[dict], key: str) -> Optional[float]:
    a = avg(rows, key)
    return None if a is None else round(a * 100)


def fmt(value, suffix: str = "", digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.{digits}f}{suffix}"
    return f"{int(value) if isinstance(value, float) else value}{suffix}"


def ok_rows(rows: list[dict], version: str) -> list[dict]:
    return [r for r in rows if r["version"] == version and not r["error"]]


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
def make_charts(rows: list[dict], versions: list[str], charts_dir: Path) -> dict:
    charts_dir = Path(charts_dir)
    out = {}
    judge = [avg(ok_rows(rows, v), "judge_avg") for v in versions]
    if any(j is not None for j in judge):
        out["judge"] = charts.bar_chart(charts_dir / "judge_scores.png", versions, judge,
                                        "Average judge score (1-5)", "Plan quality by prompt version (LLM judge)", ymax=5.5)
    structured = [v for v in versions if v != "plan_v1"]
    if structured:
        out["issues"] = charts.grouped_bar_chart(
            charts_dir / "validation_issues.png", structured,
            {"First draft": [avg(ok_rows(rows, v), "issues_before_repair") for v in structured],
             "Final plan": [avg(ok_rows(rows, v), "final_issues") for v in structured]},
            "Validation issues per plan (average)", "Validation issues by prompt version")
    lang_version = next((v for v in reversed(versions) if v in LANGUAGE_AWARE), versions[-1])
    langs = [code for code in LANGUAGES if any(r["language"] == code for r in ok_rows(rows, lang_version))]
    if langs:
        out["language"] = charts.bar_chart(
            charts_dir / "language_match.png", [LANGUAGES[c].split(" ")[0] for c in langs],
            [avg([r for r in ok_rows(rows, lang_version) if r["language"] == c], "language_match") for c in langs],
            "Letters in the expected script (%)", f"Language match by language ({lang_version})", ymax=110,
            fmt="{:.0f}", threshold=60, threshold_label="60% = WRONG_LANGUAGE limit")
    return out


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------
def summary_table(rows: list[dict], versions: list[str]) -> list[str]:
    head = ("| Version | Plans | Judge avg | Personal. | Practical. | Simplicity | Grounding | Complete. | Structure "
            "| Budget fit | Price > cost | Break-even ok | Halluc. schemes | Promise words | Language match "
            "| Issues 1st draft | Final passed | Latency (s) |")
    lines = [head, "|" + "---|" * (head.count("|") - 1)]
    for v in versions:
        r = ok_rows(rows, v)
        lines.append(
            f"| {v} | {len(r)} | {fmt(avg(r, 'judge_avg'))} | {fmt(avg(r, 'judge_personalisation'))} "
            f"| {fmt(avg(r, 'judge_practicality'))} | {fmt(avg(r, 'judge_simplicity'))} | {fmt(avg(r, 'judge_grounding'))} "
            f"| {fmt(avg(r, 'judge_completeness'))} | {fmt(avg(r, 'structure_score'))} | {fmt(pct(r, 'budget_fit'), '%')} "
            f"| {fmt(pct(r, 'price_above_cost'), '%')} | {fmt(pct(r, 'break_even_realistic'), '%')} "
            f"| {fmt(avg(r, 'hallucinated_schemes'))} | {fmt(avg(r, 'guarantee_phrases'))} "
            f"| {fmt(avg(r, 'language_match'), '%', 0)} | {fmt(avg(r, 'issues_before_repair'))} "
            f"| {fmt(pct(r, 'final_passed'), '%')} | {fmt(avg(r, 'latency_seconds'), '', 1)} |"
        )
    return lines


def improvement_text(rows: list[dict], versions: list[str]) -> list[str]:
    if "plan_v1" not in versions or len(versions) < 2:
        return ["Run with plan_v1 and a later version to compare the baseline with the improved prompts."]
    best = versions[-1]
    a, b = ok_rows(rows, "plan_v1"), ok_rows(rows, best)
    if not a or not b:
        return [f"Not enough successful plans for plan_v1 and {best} to compare."]
    lines = []
    ja, jb = avg(a, "judge_avg"), avg(b, "judge_avg")
    if ja is not None and jb is not None:
        lines.append(f"- **Judge score:** {fmt(ja)} -> {fmt(jb)} out of 5 ({jb - ja:+.2f}).")
    sa, sb = avg(a, "structure_score"), avg(b, "structure_score")
    lines.append(f"- **Structure:** {fmt(sa)} -> {fmt(sb)}. The baseline is free text; from plan_v2 the output "
                 "follows a fixed schema, so every plan has costs, pricing, marketing, launch steps, risks and assumptions.")
    lines.append(f"- **Money maths:** plan_v1 numbers are written by the model and cannot be checked; in {best} every "
                 f"total comes from the calculator. Budget fits in {fmt(pct(b, 'budget_fit'), '%')} of {best} plans, "
                 f"price is above cost in {fmt(pct(b, 'price_above_cost'), '%')}.")
    lines.append(f"- **Invented schemes:** {fmt(avg(a, 'hallucinated_schemes'))} -> {fmt(avg(b, 'hallucinated_schemes'))} per plan "
                 "(plan_v4 and later may only use schemes from the retrieved official documents).")
    lines.append(f"- **Promise words** (\"guaranteed\", \"pakka munafa\"): {fmt(avg(a, 'guarantee_phrases'))} -> "
                 f"{fmt(avg(b, 'guarantee_phrases'))} per plan.")
    lines.append(f"- **Language match:** {fmt(avg(a, 'language_match'), '%', 0)} -> {fmt(avg(b, 'language_match'), '%', 0)} "
                 "of letters in the user's script.")
    lines.append(f"- **Validation:** {fmt(pct(b, 'final_passed'), '%')} of {best} plans pass all checks after repair "
                 f"(first drafts had {fmt(avg(b, 'issues_before_repair'))} issues on average).")
    la, lb = avg(a, "latency_seconds"), avg(b, "latency_seconds")
    if la is not None and lb is not None:
        lines.append(f"- **Cost:** average time per plan {fmt(la, ' s', 1)} -> {fmt(lb, ' s', 1)} "
                     "(structured output, retrieval, validation and repairs usually add time).")
    return lines


def edge_case_table(rows: list[dict], profiles: list[dict], versions: list[str]) -> list[str]:
    edges = [p for p in profiles if p.get("edge_case")]
    if not edges:
        return ["No edge-case profiles in this run (p12, p13, p14 are the edge cases)."]
    lines = []
    for p in edges:
        lines += [f"**{p['id']}** - {p['notes']}", "",
                  "| Version | Passed | Final issues | Budget fit | Judge avg |", "|---|---|---|---|---|"]
        for v in versions:
            r = next((x for x in rows if x["version"] == v and x["profile_id"] == p["id"]), None)
            if r is None:
                continue
            if r["error"]:
                lines.append(f"| {v} | error | {r['error'][:60]} | | |")
                continue
            passed = "n/a (free text)" if r["final_passed"] == "" else ("yes" if _num(r["final_passed"]) else "no")
            budget = "n/a" if r["budget_fit"] == "" else ("yes" if _num(r["budget_fit"]) else "**no (shown as a warning)**")
            lines.append(f"| {v} | {passed} | {r['final_issue_codes'] or '-'} | {budget} | {fmt(_num(r['judge_avg']))} |")
        lines.append("")
    return lines


def language_section(rows: list[dict], versions: list[str]) -> list[str]:
    version = next((v for v in reversed(versions) if v in LANGUAGE_AWARE), None)
    if version is None:
        return ["Language checks apply to plan_v4 and plan_v5; neither was in this run."]
    lines = [f"Plans from **{version}** grouped by language:", "",
             "| Language | Plans | Mode | Language match | WRONG_LANGUAGE | NUMBER_MISMATCH | Passed |", "|---|---|---|---|---|---|---|"]
    for code, name in LANGUAGES.items():
        r = [x for x in ok_rows(rows, version) if x["language"] == code]
        if not r:
            continue
        modes = "/".join(sorted({x["translate_mode"] for x in r if x["translate_mode"]}))
        wrong = sum("WRONG_LANGUAGE" in x["final_issue_codes"] for x in r)
        mismatch = sum("NUMBER_MISMATCH" in x["final_issue_codes"] for x in r)
        lines.append(f"| {name} | {len(r)} | {modes} | {fmt(avg(r, 'language_match'), '%', 0)} | {wrong}/{len(r)} "
                     f"| {mismatch}/{len(r)} | {fmt(pct(r, 'final_passed'), '%')} |")
    if LANGUAGE_REPORT.exists():
        body = LANGUAGE_REPORT.read_text(encoding="utf-8").strip().splitlines()
        body = [re.sub(r"^# ", "#### ", line) for line in body]
        lines += ["", "#### Language evaluation from scripts/eval_language.py (2 sample profiles x 7 languages)", ""]
        lines += body[1:] if body and body[0].startswith("####") else body
    return lines


def excerpt(results: dict, version: str, profile_id: str, limit: int = 700) -> Optional[str]:
    from app.evaluation.render import plan_to_text
    from app.plan_models import BusinessPlan

    record = results.get((version, profile_id))
    if not record or not record.get("plan"):
        return None
    text = plan_to_text(BusinessPlan.model_validate(record["plan"]))
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


def examples_section(results: dict, profiles: list[dict], versions: list[str]) -> list[str]:
    if "plan_v1" not in versions or "plan_v5" not in versions:
        return ["Needs both plan_v1 and plan_v5 in the run."]
    lines, shown = [], 0
    preferred = sorted(profiles, key=lambda p: (p["language"] not in ("hi", "en"), p.get("edge_case", False)))
    for p in preferred:
        a, b = excerpt(results, "plan_v1", p["id"]), excerpt(results, "plan_v5", p["id"])
        if not a or not b:
            continue
        lines += [f"### Example {shown + 1}: {p['id']} ({LANGUAGES[p['language']]}) - {p['profile']['business_idea']}, "
                  f"₹{p['profile']['budget_inr']:,}", "",
                  "**plan_v1 (baseline prompt, free text)**", "", "```text", a, "```", "",
                  "**plan_v5 (structured, grounded, calculator numbers, language rules)**", "", "```text", b, "```", ""]
        shown += 1
        if shown == 2:
            break
    return lines or ["No profile has both a plan_v1 and a plan_v5 result yet."]


def rag_section(rag_result: Optional[dict]) -> list[str]:
    if rag_result is None:
        return ["Skipped in this run (`--no-rag`). Run `python scripts/eval_rag.py`."]
    if "error" in rag_result:
        return [f"Not available: {rag_result['error']}"]
    lines = [f"- **hit-rate@4: {rag_result['hits']}/{rag_result['total']} = {rag_result['hit_rate']:.0%}** "
             f"(expected scheme among the top 4 chunks)",
             f"- hit-rate@1: {rag_result['hits_at_1']}/{rag_result['total']} = {rag_result['hit_rate_at_1']:.0%}",
             f"- {rag_result['total']} questions, 4+ in Hindi/Hinglish, embedding model `{settings.EMBEDDING_MODEL}`"]
    misses = [r for r in rag_result["rows"] if not r["hit"]]
    if misses:
        lines.append("- Misses: " + "; ".join(f"#{r['id']} expected {r['expected_scheme']}" for r in misses))
    return lines


def human_placeholder() -> str:
    return (f"{HUMAN_START}\nNot scored yet. Run `python scripts/make_human_review.py`, ask reviewers to fill in "
            "`data/eval/human_review/review_sheet.csv`, then run `python scripts/score_human.py`.\n" + HUMAN_END)


def existing_human_section(path: Path) -> str:
    if path.exists():
        match = re.search(re.escape(HUMAN_START) + r".*?" + re.escape(HUMAN_END), path.read_text(encoding="utf-8"), re.S)
        if match:
            return match.group(0)
    return human_placeholder()


def write_report(rows, results, profiles, versions, report_path, chart_paths, rag_result, judged: bool) -> Path:
    report_path = Path(report_path)
    human = existing_human_section(report_path)  # keep human review scores across re-runs
    mock = settings.LLM_PROVIDER == "mock"

    def rel(p: Path) -> str:
        return os.path.relpath(p, report_path.parent).replace(os.sep, "/")

    lines = ["# Evaluation report: plan prompt versions", ""]
    if mock:
        lines += ["> **MOCK RUN - NOT REAL RESULTS.** This report was produced with `LLM_PROVIDER=mock` to test the "
                  "pipeline. The plans and judge scores are fixed stand-ins. Re-run with Groq for the final numbers.", ""]
    lines += [
        f"Generated {datetime.now():%Y-%m-%d %H:%M} | generator `{settings.LLM_PROVIDER}/{settings.model_name}` | "
        f"judge `{'mock' if mock else settings.JUDGE_MODEL}`{'' if judged else ' (judge skipped)'} | "
        f"{len(profiles)} test profiles x {len(versions)} versions = {len(rows)} plans "
        f"({sum(1 for r in rows if r['error'])} errors).", "",
        "## 1. Summary per prompt version", "",
        *summary_table(rows, versions), "",
        "Judge scores are 1-5 (blind LLM judge). Budget fit / price > cost / break-even ok / final passed are % of plans "
        "(n/a for the free-text plan_v1). Hallucinated schemes and promise words are averages per plan. Language match = "
        "% of letters in the user's script.", "",
    ]
    for key, title in (("judge", "Judge score"), ("issues", "Validation issues"), ("language", "Language match")):
        if key in chart_paths:
            lines += [f"![{title}]({rel(chart_paths[key])})", ""]
    lines += ["## 2. What improved from plan_v1 to the latest version", "", *improvement_text(rows, versions), "",
              "## 3. Edge cases", "", *edge_case_table(rows, profiles, versions), "",
              "## 4. Languages", "", *language_section(rows, versions), "",
              "## 5. Side by side: plan_v1 vs plan_v5", "", *examples_section(results, profiles, versions), "",
              "## 6. Scheme search (RAG)", "", *rag_section(rag_result), "",
              "## 7. Human review (blind A/B, plan_v1 vs plan_v5)", "", human, "",
              "## Limitations", "",
              "- **LLM judge bias:** a model judge can prefer longer or more structured answers, or its own style "
              "(especially if the judge and generator are the same model). Judging is blind (no version shown, shuffled "
              "order, temperature 0), and we add a blind human review for this reason.",
              "- **Small test set:** 15 profiles, one run per version at temperature "
              f"{settings.LLM_TEMPERATURE}; differences of a few tenths may be noise.",
              "- **Language match** only checks the script, not grammar or naturalness; native speakers should read the plans.",
              "- **Scheme facts** come from our starter documents (mostly PIB releases); they must be re-checked against the "
              "official scheme websites.", ""]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
