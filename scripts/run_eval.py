"""Phase 7: evaluate the plan prompt versions (the main result of the project).

Run from the project folder:
    python scripts/run_eval.py                                  # all 5 versions x 15 profiles + judge
    python scripts/run_eval.py --versions plan_v1,plan_v5       # only some versions
    python scripts/run_eval.py --profiles p01,p12 --no-judge    # some profiles, no LLM judge
    python scripts/run_eval.py --limit 3                        # first 3 profiles (quick check)
    python scripts/run_eval.py --resume                         # continue after an interruption
    LLM_PROVIDER=mock python scripts/run_eval.py --limit 3      # offline pipeline check

Outputs: data/eval/results/raw/<version>/<profile>.json (cache), data/eval/results/results.csv,
data/eval/report.md and docs/charts/*.png. EVAL_DELAY_SECONDS in .env sets the pause between calls.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.evaluation.runner import ALL_VERSIONS, run_evaluation  # noqa: E402
from app.llm import LLMConfigError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate plan prompt versions.")
    parser.add_argument("--versions", default=",".join(ALL_VERSIONS), help="comma-separated, default: all")
    parser.add_argument("--profiles", default="all", help="'all' or comma-separated ids like p01,p05")
    parser.add_argument("--limit", type=int, default=None, help="only the first N profiles")
    parser.add_argument("--no-judge", action="store_true", help="skip the LLM judge (fewer API calls)")
    parser.add_argument("--resume", action="store_true", help="reuse cached results in data/eval/results/raw")
    parser.add_argument("--no-rag", action="store_true", help="skip the RAG hit-rate evaluation")
    args = parser.parse_args()

    versions = [v.strip() for v in args.versions.split(",") if v.strip()]
    unknown = [v for v in versions if v not in ALL_VERSIONS]
    if unknown:
        print(f"Unknown version(s): {unknown}. Choose from {ALL_VERSIONS}")
        return 1
    ids = None if args.profiles == "all" else [p.strip() for p in args.profiles.split(",")]

    print(f"Provider: {settings.LLM_PROVIDER} | model: {settings.model_name} | judge: "
          f"{'off' if args.no_judge else settings.JUDGE_MODEL} | delay: {settings.EVAL_DELAY_SECONDS}s\n")
    start = time.perf_counter()
    try:
        out = run_evaluation(versions=versions, profile_ids=ids, limit=args.limit, judge=not args.no_judge,
                             resume=args.resume, rag_eval=not args.no_rag)
    except LLMConfigError as e:
        print(f"CONFIG ERROR: {e}")
        return 1
    errors = sum(1 for r in out["rows"] if r["error"])
    print(f"\nDone in {time.perf_counter() - start:.0f}s: {len(out['rows'])} plans, {errors} errors")
    print(f"  {out['csv_path']}\n  {out['report_path']}")
    for path in out["charts"].values():
        print(f"  {path}")
    if errors:
        print("Some plans failed. Run again with --resume to retry only those.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
