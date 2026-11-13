"""Phase 6: how well do plans come out in each language?

Run from the project folder:
    python scripts/eval_language.py                  # uses LLM_PROVIDER from .env
    python scripts/eval_language.py --profiles 0 3   # choose sample profiles

For each sample profile x 7 languages it generates a plan_v5 plan and records:
  translate mode (direct / pivot), script match (% of letters in the right script),
  WRONG_LANGUAGE and NUMBER_MISMATCH counts, validation result and time.
The table is printed and saved to data/eval/language_report.md for our report.
Mock mode cannot translate, so only English and Hindi pass there; real numbers need Groq.
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import BASE_DIR, settings  # noqa: E402
from app.llm import LLMConfigError  # noqa: E402
from app.models import LANGUAGES, BusinessProfile  # noqa: E402
from app.planner import PlanLLMError, generate_plan  # noqa: E402

PROFILES_FILE = BASE_DIR / "data" / "eval" / "sample_profiles.json"
REPORT_FILE = BASE_DIR / "data" / "eval" / "language_report.md"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", type=int, nargs="+", default=[0, 1])
    args = parser.parse_args()
    samples = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))

    rows = []
    print(f"Provider: {settings.LLM_PROVIDER} | Model: {settings.model_name} | TRANSLATE_MODE: {settings.TRANSLATE_MODE}\n")
    for lang in LANGUAGES:
        stats = {"runs": 0, "ratio_sum": 0.0, "wrong": 0, "mismatch": 0, "passed": 0, "seconds": 0.0, "modes": set()}
        for index in args.profiles:
            profile = BusinessProfile(**{**samples[index], "language": lang})
            start = time.perf_counter()
            try:
                plan = generate_plan(profile, language=lang, prompt_version="plan_v5")
            except (LLMConfigError, PlanLLMError) as e:
                print(f"ERROR {lang} profile {index}: {e}")
                return 1
            seconds = time.perf_counter() - start
            codes = [i.code for i in plan.validation.issues]
            stats["runs"] += 1
            stats["ratio_sum"] += plan.script_match or 0
            stats["wrong"] += "WRONG_LANGUAGE" in codes
            stats["mismatch"] += "NUMBER_MISMATCH" in codes
            stats["passed"] += plan.validation.passed
            stats["seconds"] += seconds
            stats["modes"].add(plan.translate_mode)
            print(f"  {lang} profile {index}: {plan.translate_mode:<6} script {plan.script_match or 0:.0%} "
                  f"issues {codes or 'none'} ({seconds:.1f}s)")
        rows.append((lang, stats))

    lines = [
        "# Language evaluation (plan_v5)",
        "",
        f"Generated {datetime.now():%Y-%m-%d %H:%M} with `{settings.LLM_PROVIDER}/{settings.model_name}`, "
        f"TRANSLATE_MODE=`{settings.TRANSLATE_MODE}`, sample profiles {args.profiles}.",
        "",
        "| Language | Mode | Script match | WRONG_LANGUAGE | NUMBER_MISMATCH | Passed validation | Avg seconds |",
        "|---|---|---|---|---|---|---|",
    ]
    for lang, s in rows:
        n = s["runs"]
        lines.append(
            f"| {LANGUAGES[lang]} | {'/'.join(sorted(s['modes']))} | {s['ratio_sum'] / n:.0%} | {s['wrong']}/{n} "
            f"| {s['mismatch']}/{n} | {s['passed']}/{n} | {s['seconds'] / n:.1f} |"
        )
    lines += [
        "",
        "Script match = share of letters written in the expected script (Devanagari for Hindi/Marathi, "
        "Bengali, Tamil, Telugu, Gujarati, Latin for English). Below 60% counts as WRONG_LANGUAGE.",
    ]
    if settings.LLM_PROVIDER == "mock":
        lines.append("Mock mode only has English and Hindi plans and cannot translate, so the other "
                     "languages are expected to show WRONG_LANGUAGE here. Run with Groq for real numbers.")
    report = "\n".join(lines) + "\n"
    REPORT_FILE.write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"Saved {REPORT_FILE.relative_to(BASE_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
