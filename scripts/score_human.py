"""Phase 7: score the blind human review and add it to data/eval/report.md.

    python scripts/score_human.py                                   # data/eval/human_review/review_sheet.csv
    python scripts/score_human.py --sheets sheet_asha.csv sheet_ravi.csv   # several filled sheets
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.evaluation.human import REVIEW_DIR, score_review, write_human_section  # noqa: E402
from app.evaluation.runner import DEFAULT_REPORT  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sheets", nargs="+", type=Path, default=[REVIEW_DIR / "review_sheet.csv"])
    parser.add_argument("--key", type=Path, default=REVIEW_DIR / "key.json")
    args = parser.parse_args()
    for path in [*args.sheets, args.key]:
        if not path.exists():
            print(f"Missing {path}. Run scripts/make_human_review.py first.")
            return 1
    result = score_review(args.sheets, args.key)
    write_human_section(result, DEFAULT_REPORT)
    if result["ratings"] == 0:
        print("No ratings filled in yet. Ask reviewers to fill in review_sheet.csv.")
        return 0
    print(f"Preferred plan_v5: {result['prefer_v5_percent']}% of {result['ratings']} choices")
    for version, scores in result["averages"].items():
        print(f"  {version}: " + ", ".join(f"{c} {s}" for c, s in scores.items()))
    print(f"Added to {DEFAULT_REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
