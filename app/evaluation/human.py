"""Phase 7: blind human review (A/B) of plan_v1 vs plan_v5.

make_review(): for N profiles, put the plan_v1 and plan_v5 plans in random order as "Plan A" and
  "Plan B". Writes review_sheet.csv (reviewers fill it in), review_pack.md (the plans to read) and
  key.json (which plan is which - do NOT give it to reviewers).
score_review(): reads the filled sheet(s) + key.json and returns the preference for plan_v5 and the
  average scores per version; write_human_section() puts them into report.md.

Reviewers score each plan 1-5 on clarity, usefulness and trust, and pick the plan they prefer.
"""
import csv
import json
import random
import re
from pathlib import Path
from statistics import mean
from typing import Optional

from app.config import BASE_DIR
from app.evaluation.render import plan_to_text
from app.evaluation.report import HUMAN_END, HUMAN_START
from app.evaluation.runner import load_cached, raw_path
from app.models import LANGUAGES
from app.plan_models import BusinessPlan

REVIEW_DIR = BASE_DIR / "data" / "eval" / "human_review"
CRITERIA = ["clarity", "usefulness", "trust"]
SHEET_COLUMNS = (["item", "profile_id", "reviewer"] + [f"plan_A_{c}" for c in CRITERIA]
                 + [f"plan_B_{c}" for c in CRITERIA] + ["preferred", "comments"])
VERSIONS = ("plan_v1", "plan_v5")


def make_review(profiles: list[dict], results_dir: Path, out_dir: Path = REVIEW_DIR, n: int = 6, seed: int = 7) -> dict:
    """Uses cached results from scripts/run_eval.py. Profiles without both plans are skipped."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    items, key = [], {}
    for entry in profiles:
        plans = {v: load_cached(raw_path(results_dir, v, entry["id"])) for v in VERSIONS}
        if not all(p and p.get("plan") for p in plans.values()):
            continue
        order = list(VERSIONS)
        rng.shuffle(order)  # random A/B order per item
        item = f"R{len(items) + 1}"
        key[item] = {"profile_id": entry["id"], "A": order[0], "B": order[1]}
        items.append((item, entry, {label: BusinessPlan.model_validate(plans[v]["plan"]) for label, v in zip("AB", order)}))
        if len(items) == n:
            break

    with open(out_dir / "review_sheet.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        for item, entry, _ in items:
            writer.writerow({"item": item, "profile_id": entry["id"]})

    pack = ["# Human review pack", "",
            "For each item, read the profile and the two plans. In `review_sheet.csv` give each plan a score from "
            "1 (poor) to 5 (excellent) for:", "",
            "- **clarity**: easy to understand for a first-time entrepreneur",
            "- **usefulness**: practical, specific steps this person could follow",
            "- **trust**: honest and believable (numbers, schemes, no overpromising)", "",
            "Then write **A** or **B** in `preferred`, and add your name in `reviewer` (one row per reviewer; copy the "
            "rows if several people review). The plans are in random order; do not try to guess which is which.", ""]
    for item, entry, plans in items:
        p = entry["profile"]
        pack += ["---", "", f"## {item} ({LANGUAGES[entry['language']]})", "",
                 f"**Business:** {p['business_idea']} | **Budget:** ₹{p['budget_inr']:,} | **Place:** {p['location']} | "
                 f"**Skills:** {p['skills']} | **Customers:** {p['target_customers']}", ""]
        for label in "AB":
            pack += [f"### Plan {label}", "", "```text", plan_to_text(plans[label]), "```", ""]
    (out_dir / "review_pack.md").write_text("\n".join(pack), encoding="utf-8")
    (out_dir / "key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    return {"items": len(items), "dir": out_dir}


def _score(value) -> Optional[float]:
    try:
        number = float(str(value).strip())
    except ValueError:
        return None
    return number if 1 <= number <= 5 else None


def score_review(sheet_paths: list[Path], key_path: Path) -> dict:
    """Preference for plan_v5 (%) and average clarity/usefulness/trust per version."""
    key = json.loads(Path(key_path).read_text(encoding="utf-8"))
    scores = {v: {c: [] for c in CRITERIA} for v in VERSIONS}
    preferences, reviewers = [], set()
    for path in sheet_paths:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                answer = key.get(row.get("item", "").strip())
                if not answer:
                    continue
                if row.get("reviewer"):
                    reviewers.add(row["reviewer"].strip())
                for label in "AB":
                    for c in CRITERIA:
                        value = _score(row.get(f"plan_{label}_{c}", ""))
                        if value is not None:
                            scores[answer[label]][c].append(value)
                choice = row.get("preferred", "").strip().upper()
                if choice in ("A", "B"):
                    preferences.append(answer[choice])
    averages = {v: {c: (round(mean(vals), 2) if vals else None) for c, vals in crit.items()} for v, crit in scores.items()}
    v5 = sum(p == "plan_v5" for p in preferences)
    return {
        "ratings": len(preferences),
        "reviewers": len(reviewers),
        "prefer_v5_percent": round(v5 / len(preferences) * 100) if preferences else None,
        "averages": averages,
    }


def write_human_section(result: dict, report_path: Path) -> Path:
    """Replace the human review block in report.md (between the markers)."""
    report_path = Path(report_path)
    if result["ratings"] == 0:
        body = "No filled-in ratings found yet in the review sheet."
    else:
        lines = [f"**{result['prefer_v5_percent']}% of choices preferred plan_v5** over the baseline plan_v1 "
                 f"({result['ratings']} choices from {result['reviewers'] or 'unnamed'} reviewer(s), blind A/B order).", "",
                 "| Version | Clarity | Usefulness | Trust |", "|---|---|---|---|"]
        for v in VERSIONS:
            a = result["averages"][v]
            lines.append(f"| {v} | " + " | ".join("n/a" if a[c] is None else f"{a[c]:.2f}" for c in CRITERIA) + " |")
        body = "\n".join(lines)
    block = f"{HUMAN_START}\n{body}\n{HUMAN_END}"
    text = report_path.read_text(encoding="utf-8") if report_path.exists() else "# Evaluation report\n"
    pattern = re.escape(HUMAN_START) + r".*?" + re.escape(HUMAN_END)
    if re.search(pattern, text, re.S):
        text = re.sub(pattern, lambda _: block, text, flags=re.S)
    else:
        text += f"\n## 7. Human review (blind A/B, plan_v1 vs plan_v5)\n\n{block}\n"
    report_path.write_text(text, encoding="utf-8")
    return report_path
