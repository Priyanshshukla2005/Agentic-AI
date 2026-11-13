"""Phase 6: language checks with plain Unicode ranges (no extra libraries).

script_ratio("मेरा बिज़नेस FSSAI", "hi") -> share of letters written in the script expected for
Hindi (Devanagari). Below MIN_SCRIPT_RATIO the text counts as WRONG_LANGUAGE.
rupee_numbers("₹3,500 and Rs 500") -> Counter({3500: 1, 500: 1}), used for NUMBER_MISMATCH.
"""
import re
import unicodedata
from collections import Counter
from typing import Iterable, Optional

MIN_SCRIPT_RATIO = 0.6

# Unicode blocks of each script.
SCRIPT_RANGES = {
    "devanagari": (0x0900, 0x097F),
    "bengali": (0x0980, 0x09FF),
    "gujarati": (0x0A80, 0x0AFF),
    "tamil": (0x0B80, 0x0BFF),
    "telugu": (0x0C00, 0x0C7F),
}
LANG_SCRIPT = {
    "en": "latin", "hi": "devanagari", "mr": "devanagari", "bn": "bengali",
    "ta": "tamil", "te": "telugu", "gu": "gujarati",
}


def char_script(ch: str) -> Optional[str]:
    """Script of one character, or None for digits, spaces, punctuation, emoji..."""
    if ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
        return "latin"
    code = ord(ch)
    for name, (low, high) in SCRIPT_RANGES.items():
        if low <= code <= high and not unicodedata.category(ch).startswith("N"):  # skip native digits
            return name
    return None


# Acronyms (FSSAI, GST, UPI) and links are the same in every language, so they are not counted.
_IGNORE_RE = re.compile(r"https?://\S+|\b[A-Z]{2,}[a-z]?\b")


def script_counts(text: str) -> Counter:
    return Counter(s for s in map(char_script, _IGNORE_RE.sub(" ", text)) if s)


def script_ratio(text: str, language: str) -> Optional[float]:
    """Share (0-1) of letters in the expected script. None if the text has no letters at all."""
    counts = script_counts(text)
    total = sum(counts.values())
    if total == 0:
        return None
    return round(counts[LANG_SCRIPT.get(language, "latin")] / total, 3)


def detect_script(text: str) -> Optional[str]:
    """The most used script in the text ("latin", "devanagari", "tamil"...)."""
    counts = script_counts(text)
    return counts.most_common(1)[0][0] if counts else None


def is_wrong_language(texts: Iterable[str], language: str) -> tuple[bool, Optional[float]]:
    """(True, ratio) if the joined texts are mostly NOT in the language's script."""
    ratio = script_ratio(" ".join(texts), language)
    return (ratio is not None and ratio < MIN_SCRIPT_RATIO), ratio


# ---------- Rupee numbers ----------

RUPEE_RE = re.compile(r"(?:₹|\brs\.?|\binr\b|रु\.?|रुपये)\s*([\d०-९০-৯૦-૯௦-௯౦-౯][\d,०-९০-৯૦-૯௦-௯౦-౯]*)", re.IGNORECASE)


def to_ascii_digits(text: str) -> str:
    """Native digits (४, ৫, ௩ ...) -> 0-9, so ₹३५०० and ₹3500 compare equal."""
    return "".join(str(unicodedata.digit(ch)) if ch.isdigit() and not ch.isascii() else ch for ch in text)


def rupee_numbers(text: str) -> Counter:
    found = Counter()
    for raw in RUPEE_RE.findall(text):
        digits = to_ascii_digits(raw).replace(",", "")
        if digits.isdigit():
            found[int(digits)] += 1
    return found


def plan_texts(draft) -> list[str]:
    """Text fields of a PlanDraft that should be in the user's language. Scheme names and
    links stay as in the official documents, so they are not checked."""
    texts = [draft.business_summary, draft.unit_name]
    texts += [c.name for c in draft.startup_costs + draft.fixed_monthly_costs]
    texts += draft.marketing_ideas + draft.assumptions + draft.risks
    texts += [f"{s.title} {s.detail}" for s in draft.launch_steps]
    texts += [s.why_it_fits for s in draft.schemes]
    return [t for t in texts if t]
