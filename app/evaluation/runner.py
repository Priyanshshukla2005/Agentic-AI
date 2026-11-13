"""Phase 7: run the prompt-version evaluation.

For every (prompt version x test profile):
  1. generate a plan with the planner (directly, not over HTTP)
  2. compute the automatic metrics (app/evaluation/metrics.py)
  3. (optional) score it with the blind LLM judge (app/evaluation/judge.py), in shuffled order
Every result is cached in <results_dir>/raw/<version>/<profile_id>.json, so an interrupted run
can continue with --resume. Then results.csv, report.md and the charts are written.

Groq free tier friendly: a pause between real LLM calls (EVAL_DELAY_SECONDS) and exponential
backoff on rate limits (429) and server errors (5xx).
"""
import csv
import json
import random
import time
from pathlib import Path
from typing import Callable, Optional

from app import rag
from app.config import BASE_DIR, settings
from app.evaluation.judge import judge_plan
from app.evaluation.metrics import compute_metrics
from app.models import BusinessProfile
from app.plan_models import BusinessPlan
from app.planner import generate_plan

ALL_VERSIONS = ["plan_v1", "plan_v2", "plan_v3", "plan_v4", "plan_v5"]
TEST_PROFILES_FILE = BASE_DIR / "data" / "eval" / "test_profiles.json"
DEFAULT_RESULTS_DIR = BASE_DIR / "data" / "eval" / "results"
DEFAULT_REPORT = BASE_DIR / "data" / "eval" / "report.md"
DEFAULT_CHARTS_DIR = BASE_DIR / "docs" / "charts"

METRIC_COLUMNS = [
    "structure_score", "budget_fit", "price_above_cost", "break_even_realistic", "hallucinated_schemes",
    "guarantee_phrases", "language_match", "issues_before_repair", "llm_repairs", "auto_fixes",
    "final_passed", "final_issues", "latency_seconds", "output_tokens_est", "readability",
]
JUDGE_COLUMNS = ["judge_personalisation", "judge_practicality", "judge_simplicity", "judge_grounding",
                 "judge_completeness", "judge_avg"]
CSV_COLUMNS = (["version", "profile_id", "language", "edge_case", "translate_mode", "error"] + METRIC_COLUMNS
               + ["initial_issue_codes", "final_issue_codes"] + JUDGE_COLUMNS)


def load_test_profiles(path: Path = TEST_PROFILES_FILE) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def select_profiles(profiles: list[dict], ids: Optional[list[str]] = None, limit: Optional[int] = None) -> list[dict]:
    chosen = [p for p in profiles if not ids or p["id"] in ids]
    return chosen[:limit] if limit else chosen


def to_profile(entry: dict) -> BusinessProfile:
    return BusinessProfile(language=entry["language"], **entry["profile"])


# ---------------------------------------------------------------------------
# Retries (Groq free tier: 429 rate limits, occasional 5xx)
# ---------------------------------------------------------------------------
RETRY_MARKERS = ("429", "rate limit", "rate_limit", "too many requests", "500", "502", "503", "504",
                 "overloaded", "timed out", "timeout", "temporarily")


def is_retryable(error: Exception) -> bool:
    text = str(error).lower()
    return any(marker in text for marker in RETRY_MARKERS)


def with_retry(func: Callable, label: str, max_retries: Optional[int] = None, base_delay: float = 5.0,
               sleep: Callable = time.sleep):
    max_retries = settings.EVAL_MAX_RETRIES if max_retries is None else max_retries
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as e:
            if attempt >= max_retries or not is_retryable(e):
                raise
            wait = base_delay * (2 ** attempt)
            print(f"    {label}: {str(e)[:80]} -> retry {attempt + 1}/{max_retries} in {wait:.0f}s")
            sleep(wait)


def pause() -> None:
    """Pause between real LLM calls (not in mock mode)."""
    if settings.LLM_PROVIDER != "mock" and settings.EVAL_DELAY_SECONDS > 0:
        time.sleep(settings.EVAL_DELAY_SECONDS)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
def raw_path(results_dir: Path, version: str, profile_id: str) -> Path:
    return Path(results_dir) / "raw" / version / f"{profile_id}.json"


def load_cached(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:  # half-written file from an interrupted run
        return None


def save_cached(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)  # atomic: never leaves a half-written result


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------
def run_evaluation(
    versions: Optional[list[str]] = None,
    profile_ids: Optional[list[str]] = None,
    limit: Optional[int] = None,
    judge: bool = True,
    resume: bool = False,
    results_dir: Path = DEFAULT_RESULTS_DIR,
    report_path: Path = DEFAULT_REPORT,
    charts_dir: Path = DEFAULT_CHARTS_DIR,
    rag_eval: bool = True,
    profiles_file: Path = TEST_PROFILES_FILE,
    seed: int = 42,
) -> dict:
    """Generate, measure, judge and report. Returns {"rows", "report_path", "csv_path", "charts"}."""
    from app.evaluation import (
        report as report_module,  # local import: report imports this module
    )

    versions = versions or ALL_VERSIONS
    profiles = select_profiles(load_test_profiles(profiles_file), profile_ids, limit)
    known_sources = rag.index_info()["sources"]
    total = len(versions) * len(profiles)
    results: dict[tuple, dict] = {}

    # 1 + 2: generate plans and compute metrics
    print(f"Generating {total} plans ({len(versions)} versions x {len(profiles)} profiles) "
          f"with {settings.LLM_PROVIDER}/{settings.model_name}")
    step = 0
    for entry in profiles:
        for version in versions:
            step += 1
            path = raw_path(results_dir, version, entry["id"])
            cached = load_cached(path) if resume else None
            if cached and cached.get("plan"):
                results[(version, entry["id"])] = cached
                print(f"[{step}/{total}] {version} / {entry['id']} cached")
                continue
            start = time.perf_counter()
            record = {"version": version, "profile_id": entry["id"], "language": entry["language"],
                      "edge_case": entry.get("edge_case", False)}
            try:
                plan = with_retry(lambda e=entry, v=version: generate_plan(to_profile(e), language=e["language"],
                                                                           prompt_version=v), f"{version}/{entry['id']}")
                record["plan"] = plan.model_dump(mode="json")
                record["metrics"] = compute_metrics(plan, entry["language"], known_sources)
                mark = "✓"
            except Exception as e:
                record["error"] = str(e)[:500]
                mark = "✗ " + str(e)[:60]
            save_cached(path, record)
            results[(version, entry["id"])] = record
            print(f"[{step}/{total}] {version} / {entry['id']} {mark} {time.perf_counter() - start:.1f}s")
            pause()

    # 3: blind judging in shuffled order (the judge never sees the version)
    if judge:
        todo = [key for key, r in results.items() if r.get("plan") and not r.get("judge")]
        random.Random(seed).shuffle(todo)
        by_id = {p["id"]: p for p in profiles}
        for i, key in enumerate(todo, 1):
            record = results[key]
            plan = BusinessPlan.model_validate(record["plan"])
            start = time.perf_counter()
            try:
                scores = with_retry(lambda k=key, p=plan, r=record: judge_plan(to_profile(by_id[k[1]]), p, r["metrics"]),
                                    f"judge {key[1]}")
                record["judge"] = scores.model_dump()
                record["judge_flat"] = scores.flat()
                mark = f"✓ avg {scores.average()}"
            except Exception as e:
                record["judge_error"] = str(e)[:300]
                mark = "✗ " + str(e)[:60]
            save_cached(raw_path(results_dir, *key), record)
            print(f"[judge {i}/{len(todo)}] plan #{i} ({key[1]}) {mark} {time.perf_counter() - start:.1f}s")
            pause()

    rows = [to_row(results[(v, p["id"])]) for p in profiles for v in versions]
    csv_path = write_csv(rows, Path(results_dir) / "results.csv")
    rag_result = None
    if rag_eval:
        from app.evaluation.rag_eval import evaluate_rag

        rag_result = evaluate_rag()
    charts = report_module.make_charts(rows, versions, charts_dir)
    report_module.write_report(rows, results, profiles, versions, report_path, charts, rag_result, judge)
    return {"rows": rows, "csv_path": csv_path, "report_path": Path(report_path), "charts": charts}


def to_row(record: dict) -> dict:
    row = {c: "" for c in CSV_COLUMNS}
    row.update({"version": record["version"], "profile_id": record["profile_id"], "language": record["language"],
                "edge_case": record.get("edge_case", False), "error": record.get("error", "")})
    plan = record.get("plan")
    if plan:
        row["translate_mode"] = plan.get("translate_mode", "")
        row.update({k: v for k, v in record.get("metrics", {}).items() if k in METRIC_COLUMNS})
        validation = plan.get("validation") or {}
        row["initial_issue_codes"] = ";".join(validation.get("initial_issue_codes", []))
        row["final_issue_codes"] = ";".join(i["code"] for i in validation.get("issues", []))
    row.update(record.get("judge_flat", {}))
    return {k: ("" if v is None else v) for k, v in row.items()}


def write_csv(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path
