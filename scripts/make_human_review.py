"""Phase 7: export a blind A/B human review of plan_v1 vs plan_v5.

Run after scripts/run_eval.py (it uses the cached plans):
    python scripts/make_human_review.py            # 6 profiles
    python scripts/make_human_review.py --n 8

Writes data/eval/human_review/review_sheet.csv (reviewers fill in), review_pack.md (what they read)
and key.json (the answer key: keep it away from reviewers).
If plans are missing, generate them first:
    python scripts/run_eval.py --versions plan_v1,plan_v5 --no-judge --resume
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.evaluation.human import REVIEW_DIR, make_review  # noqa: E402
from app.evaluation.runner import DEFAULT_RESULTS_DIR, load_test_profiles  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=6, help="number of profiles")
    args = parser.parse_args()
    out = make_review(load_test_profiles(), DEFAULT_RESULTS_DIR, REVIEW_DIR, n=args.n)
    if out["items"] == 0:
        print("No profile has both plan_v1 and plan_v5 results. Run:\n"
              "  python scripts/run_eval.py --versions plan_v1,plan_v5 --no-judge --resume")
        return 1
    print(f"Exported {out['items']} A/B items to {out['dir']}/")
    print("  review_pack.md   -> give to reviewers (the plans)")
    print("  review_sheet.csv -> reviewers fill in scores 1-5 and A/B preference")
    print("  key.json         -> answer key, do NOT share")
    print("Then: python scripts/score_human.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
