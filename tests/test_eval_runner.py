"""Phase 7: the evaluation runner end to end in mock mode (temp folders, no network)."""
import csv
import json

import pytest

from app.evaluation import human, runner
from app.evaluation.runner import CSV_COLUMNS, run_evaluation, with_retry

PROFILES = ["p01", "p02"]
VERSIONS = ["plan_v1", "plan_v5"]


@pytest.fixture
def eval_dirs(tmp_path, fake_scheme_index):
    return {"results_dir": tmp_path / "results", "report_path": tmp_path / "report.md", "charts_dir": tmp_path / "charts"}


def run(eval_dirs, **kwargs):
    return run_evaluation(versions=VERSIONS, profile_ids=PROFILES, judge=False, rag_eval=False, **eval_dirs, **kwargs)


def test_csv_report_and_charts(eval_dirs):
    out = run(eval_dirs)
    with open(out["csv_path"], encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == CSV_COLUMNS
        rows = list(reader)
    assert len(rows) == 4 and {(r["version"], r["profile_id"]) for r in rows} == {(v, p) for v in VERSIONS for p in PROFILES}
    v1 = next(r for r in rows if r["version"] == "plan_v1")
    v5 = next(r for r in rows if r["version"] == "plan_v5" and r["profile_id"] == "p01")
    assert v1["final_passed"] == "" and v1["budget_fit"] == ""      # free text: n/a
    assert v5["final_passed"] == "True" and float(v5["structure_score"]) == 1.0
    assert v5["judge_avg"] == ""                                     # --no-judge

    report = out["report_path"].read_text(encoding="utf-8")
    for section in ["MOCK RUN", "## 1. Summary per prompt version", "## 2. What improved", "## 3. Edge cases",
                    "## 4. Languages", "## 5. Side by side", "## 6. Scheme search", "## 7. Human review", "## Limitations"]:
        assert section in report, section
    assert "| plan_v5 | 2 |" in report
    assert "(judge skipped)" in report
    assert set(out["charts"]) == {"issues", "language"}  # no judge chart without judge scores
    assert all(p.exists() for p in out["charts"].values())
    assert (eval_dirs["results_dir"] / "raw" / "plan_v5" / "p02.json").exists()


def test_judge_scores_included(eval_dirs):
    out = run_evaluation(versions=VERSIONS, profile_ids=["p01"], judge=True, rag_eval=False, **eval_dirs)
    assert all(1 <= float(r["judge_avg"]) <= 5 for r in out["rows"])
    assert "judge" in out["charts"]


def test_resume_skips_cached_results(eval_dirs, monkeypatch):
    run(eval_dirs)
    calls = []
    real = runner.generate_plan
    monkeypatch.setattr(runner, "generate_plan", lambda *a, **k: calls.append(1) or real(*a, **k))
    run(eval_dirs, resume=True)
    assert calls == []  # everything came from the cache
    (eval_dirs["results_dir"] / "raw" / "plan_v1" / "p02.json").unlink()
    run(eval_dirs, resume=True)
    assert len(calls) == 1  # only the missing result is generated again


def test_errors_are_recorded_and_retried_on_resume(eval_dirs, monkeypatch):
    def broken(*a, **k):
        raise ValueError("model exploded")

    monkeypatch.setattr(runner, "generate_plan", broken)
    out = run(eval_dirs)
    assert all("model exploded" in r["error"] for r in out["rows"])
    monkeypatch.undo()
    out = run(eval_dirs, resume=True)  # failed results are not treated as cached
    assert not any(r["error"] for r in out["rows"])


def test_with_retry_backs_off_on_rate_limits():
    waits, attempts = [], []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("Error code: 429 - rate limit reached")
        return "ok"

    assert with_retry(flaky, "test", max_retries=5, base_delay=1, sleep=waits.append) == "ok"
    assert waits == [1, 2]  # exponential backoff
    with pytest.raises(ValueError):
        with_retry(lambda: (_ for _ in ()).throw(ValueError("bad input")), "test", sleep=waits.append)


def test_human_review_round_trip(eval_dirs, tmp_path):
    run(eval_dirs)
    out_dir = tmp_path / "human"
    made = human.make_review(runner.select_profiles(runner.load_test_profiles(), PROFILES), eval_dirs["results_dir"], out_dir, n=6)
    assert made["items"] == 2
    key = json.loads((out_dir / "key.json").read_text())
    assert {key[i]["A"] for i in key} | {key[i]["B"] for i in key} == {"plan_v1", "plan_v5"}
    pack = (out_dir / "review_pack.md").read_text(encoding="utf-8")
    assert "Plan A" in pack and "plan_v1" not in pack and "plan_v5" not in pack  # blind

    # Fill the sheet as a reviewer who always prefers plan_v5 and scores it higher.
    sheet = out_dir / "review_sheet.csv"
    with open(sheet, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        v5_label = "A" if key[row["item"]]["A"] == "plan_v5" else "B"
        other = "B" if v5_label == "A" else "A"
        row.update({"reviewer": "Asha", "preferred": v5_label})
        for c in human.CRITERIA:
            row[f"plan_{v5_label}_{c}"], row[f"plan_{other}_{c}"] = "5", "2"
    with open(sheet, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=human.SHEET_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    result = human.score_review([sheet], out_dir / "key.json")
    assert result["prefer_v5_percent"] == 100 and result["ratings"] == 2 and result["reviewers"] == 1
    assert result["averages"]["plan_v5"]["clarity"] == 5 and result["averages"]["plan_v1"]["trust"] == 2

    human.write_human_section(result, eval_dirs["report_path"])
    report = eval_dirs["report_path"].read_text(encoding="utf-8")
    assert "100% of choices preferred plan_v5" in report and report.count(human.HUMAN_START) == 1
    run(eval_dirs, resume=True)  # re-running the evaluation keeps the human review section
    assert "100% of choices preferred plan_v5" in eval_dirs["report_path"].read_text(encoding="utf-8")
