"""Phase 2: the intake chat brain. One call to `process_message` = one user turn.

Each turn does 4 small steps:
  1. PRIVACY  - mask Aadhaar / PAN / bank / phone numbers before anything is stored or sent.
  2. EXTRACT  - pull business details out of the message (LLM first, rules as a backup).
  3. MERGE    - copy the new details into the profile (budget is normalised in code).
  4. RESPOND  - ask for the next missing detail, or show a summary when we have everything.

Mock mode (LLM_PROVIDER=mock) skips the LLM completely: rule-based extraction + fixed
template questions. That keeps tests offline and the app usable without an API key.
"""
import json
import logging
import re
from functools import lru_cache
from typing import Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import PydanticOutputParser, StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.config import settings
from app.llm import get_llm, load_prompt
from app.models import LANGUAGES, PROFILE_FIELDS, BusinessProfile, ProfileUpdate
from app.session_store import Message, Session, create_session, save_session

logger = logging.getLogger(__name__)

HISTORY_SIZE = 6  # how many earlier messages the extractor gets to see

EXTRACT_PROMPT = "intake_extract_v1"
QUESTION_PROMPT = "intake_question_v1"
SUMMARY_PROMPT = "intake_summary_v1"
TEMPLATES_FILE = "intake_templates_v1.json"


class IntakeLLMError(RuntimeError):
    """The LLM could not write a reply (network down, rate limit, bad model...). API -> 502."""


@lru_cache(maxsize=1)
def load_templates() -> dict:
    """Field labels + fixed mock-mode messages, from app/prompts/intake_templates_v1.json."""
    return json.loads((settings.PROMPTS_DIR / TEMPLATES_FILE).read_text(encoding="utf-8"))


def is_mock() -> bool:
    return settings.LLM_PROVIDER == "mock"


# =====================================================================
# 1. PRIVACY: mask personal ID numbers
# =====================================================================

# Order matters: bank accounts first (they are long digit strings that could look like
# a phone or Aadhaar number), then Aadhaar, PAN and phone.
BANK_RE = re.compile(
    r"((?:account|acct|a/c|khata|bank)\s*(?:no\.?|number|num|#)?\s*(?:is|hai)?\s*[:\-]?\s*)(\d{9,18})(?!\d)",
    re.IGNORECASE,
)
AADHAAR_RE = re.compile(r"(?<!\d)\d{4}[ -]?\d{4}[ -]?\d{4}(?!\d)")
PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[ -]?|0)?[6-9]\d{4}[ -]?\d{5}(?!\d)")


def mask_pii(text: str) -> tuple[str, list[str]]:
    """Replace ID/bank/phone numbers with a placeholder.

    Returns (masked_text, list of what was found), e.g. ("my PAN is [PAN REMOVED]", ["pan"]).
    """
    found: list[str] = []

    def bank(match: re.Match) -> str:
        found.append("bank_account")
        return match.group(1) + "[BANK ACCOUNT REMOVED]"

    def simple(kind: str, label: str):
        def repl(_match: re.Match) -> str:
            found.append(kind)
            return label
        return repl

    text = BANK_RE.sub(bank, text)
    text = AADHAAR_RE.sub(simple("aadhaar", "[AADHAAR REMOVED]"), text)
    text = PAN_RE.sub(simple("pan", "[PAN REMOVED]"), text)
    text = PHONE_RE.sub(simple("phone", "[PHONE REMOVED]"), text)
    return text, found


# =====================================================================
# 2a. BUDGET: turn "1.5 lakh" / "bees hazaar" / "Rs. 20k" into a number
# =====================================================================

MULTIPLIERS = {
    "k": 1_000, "thousand": 1_000, "thousands": 1_000,
    "hazaar": 1_000, "hazar": 1_000, "hajar": 1_000, "hajaar": 1_000, "hazzar": 1_000,
    "हज़ार": 1_000, "हजार": 1_000,
    "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000, "laakh": 100_000,
    "लाख": 100_000,
    "crore": 10_000_000, "crores": 10_000_000, "cr": 10_000_000,
    "करोड़": 10_000_000, "करोड": 10_000_000,
}

# Hindi number words 1-100 (romanised, with common spellings) + a few fractions.
_HINDI_1_TO_100 = [
    "ek", "do", "teen", "char", "paanch", "chhe", "saat", "aath", "nau", "das",
    "gyarah", "barah", "terah", "chaudah", "pandrah", "solah", "satrah", "atharah", "unnis", "bees",
    "ikkis", "bais", "teis", "chaubis", "pachis", "chhabbis", "sattais", "atthais", "untis", "tees",
    "iktis", "battis", "taintis", "chautis", "paintis", "chhattis", "saintis", "adtis", "untalis", "chalis",
    "iktalis", "bayalis", "taintalis", "chavalis", "paintalis", "chhiyalis", "saintalis", "adtalis", "unchas", "pachas",
    "ikyavan", "bavan", "tirpan", "chauvan", "pachpan", "chhappan", "sattavan", "atthavan", "unsath", "saath",
    "iksath", "basath", "tirsath", "chausath", "painsath", "chhiyasath", "sadsath", "adsath", "unhattar", "sattar",
    "ikhattar", "bahattar", "tihattar", "chauhattar", "pachhattar", "chhihattar", "satattar", "athattar", "unasi", "assi",
    "ikyasi", "bayasi", "tirasi", "chaurasi", "pachasi", "chhiyasi", "sattasi", "athasi", "navasi", "nabbe",
    "ikyanve", "banve", "tiranve", "chauranve", "pachanve", "chhiyanve", "sattanve", "atthanve", "ninyanve", "sau",
]
NUMBER_WORDS: dict[str, float] = {word: i for i, word in enumerate(_HINDI_1_TO_100, start=1)}
NUMBER_WORDS.update({
    # common alternative spellings
    "chaar": 4, "panch": 5, "paach": 5, "chah": 6, "chhah": 6, "che": 6, "aat": 8, "dus": 10,
    "gyaarah": 11, "baarah": 12, "pandrah": 15, "pandhrah": 15, "unees": 19, "bis": 20,
    "pachees": 25, "pacchis": 25, "tis": 30, "chaalis": 40, "pachaas": 50, "pachpan": 55,
    "saath": 60, "sattar": 70, "assi": 80, "nabbe": 90, "nabbey": 90, "so": 100,
    # fractions: dedh lakh = 1.5 lakh, dhai lakh = 2.5 lakh, sava = 1.25, aadha = 0.5
    "dedh": 1.5, "derh": 1.5, "dhai": 2.5, "dhaai": 2.5, "sava": 1.25, "aadha": 0.5,
    # Devanagari
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6, "सात": 7, "आठ": 8,
    "नौ": 9, "दस": 10, "पंद्रह": 15, "बीस": 20, "पच्चीस": 25, "तीस": 30, "चालीस": 40,
    "पचास": 50, "साठ": 60, "सत्तर": 70, "अस्सी": 80, "नब्बे": 90, "सौ": 100, "डेढ़": 1.5, "ढाई": 2.5,
    # English words
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "twenty-five": 25, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
})


def _alternation(words) -> str:
    # Longest first so "lakhs" wins over "lakh" and "hazaar" over "hazar".
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))


_MULT = _alternation(MULTIPLIERS)
_LETTER = r"a-zऀ-ॿ"  # English + Devanagari letters
# "20000", "1.5 lakh", "20k"  (number must not be part of a longer word like "20kg")
DIGIT_AMOUNT_RE = re.compile(rf"(?<![\d.])(\d+(?:\.\d+)?)(?![\d.])\s*({_MULT})?(?![{_LETTER}])")
# "bees hazaar", "dedh lakh", "do लाख"  (a number word only counts with a multiplier)
WORD_AMOUNT_RE = re.compile(
    rf"(?<![{_LETTER}])({_alternation(NUMBER_WORDS)})\s+({_MULT})(?![{_LETTER}])"
)
CURRENCY_RE = re.compile(r"₹|\b(?:rs|inr|rupees?|rupaye|rupaiye|rupay|rupiya|rupaya)\b\.?|रुपये|रुपए|रुपया")


def parse_budget_inr(text) -> Optional[int]:
    """Convert a budget written any common Indian way into whole rupees.

    "20,000" / "₹20,000" / "Rs. 20k" -> 20000, "1.5 lakh" -> 150000, "bees hazaar" -> 20000.
    If the text holds several amounts we take the biggest one. Returns None if no
    amount > 0 is found.
    """
    if text is None:
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return int(text) if text > 0 else None

    t = str(text).lower()
    t = re.sub(r"(?<=\d),(?=\d)", "", t)  # 1,50,000 -> 150000
    t = CURRENCY_RE.sub(" ", t)           # drop ₹ / Rs / rupees

    amounts: list[float] = []
    for number, mult in DIGIT_AMOUNT_RE.findall(t):
        amounts.append(float(number) * MULTIPLIERS.get(mult, 1))
    for word, mult in WORD_AMOUNT_RE.findall(t):
        amounts.append(NUMBER_WORDS[word] * MULTIPLIERS[mult])

    best = max(amounts, default=0)
    return int(round(best)) if best > 0 else None


def format_inr(amount: int) -> str:
    """150000 -> '₹1,50,000' (Indian digit grouping)."""
    digits = str(amount)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        digits = f"{head},{tail}"
    return f"₹{digits}"


# =====================================================================
# 2b. EXTRACT (rule-based backup): regex + keywords, works offline
# =====================================================================

BUDGET_HINT_RE = re.compile(
    rf"budget|paise|paisa|₹|\brs\b|rupee|rupay|rupaye|\binr\b|\d\s*k\b|{_MULT}|बजट|पैसे|रुपये",
    re.IGNORECASE,
)
LOCATION_PATTERNS = [
    # "I live in Indore", "I'm from Navi Mumbai", "my city is Pune"
    re.compile(
        r"(?:i live in|i stay in|i am from|i'm from|im from|living in|staying in|based in|located in|"
        r"my (?:city|town|village) is)\s+([^\s,.!?][^,.!?]*)",
        re.IGNORECASE,
    ),
    # Hinglish: "main Lucknow mein rehta hoon"
    re.compile(
        r"([^\s,.!?]+)\s+(?:mein|me|में)\s+(?:rehta|rehti|rehte|rahta|rahti|rahte|रहता|रहती|रहते)",
        re.IGNORECASE,
    ),
    # "... in Indore" - only a Capitalised word, so "in cooking" is not a place
    re.compile(r"\b(?:in|at|from)\s+([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?)"),
]
NOT_PLACES = {"i", "india", "english", "hindi", "the", "my", "a"}
STOP_WORDS_RE = re.compile(r"\s+(?:and|but|where|with|aur|par|lekin|se)\b.*$", re.IGNORECASE)


def find_location(text: str) -> Optional[str]:
    for pattern in LOCATION_PATTERNS:
        match = pattern.search(text)
        if match:
            place = STOP_WORDS_RE.sub("", match.group(1)).strip(" .!?")
            if place and place.lower() not in NOT_PLACES and len(place.split()) <= 4:
                return place
    return None


def is_question(text: str) -> bool:
    return text.strip().endswith("?")


def rule_based_extract(message: str, asked_field: Optional[str]) -> ProfileUpdate:
    """Backup extractor. `asked_field` = the field our last question asked for.

    - catches budget amounts and "I live in X" / "in X" locations anywhere in the message;
    - if nothing was found for the asked field, the whole reply is taken as its answer
      (this covers the "only one field missing" case, and makes mock mode usable).
    """
    update = ProfileUpdate()
    text = message.strip()

    if BUDGET_HINT_RE.search(text) or asked_field == "budget_inr":
        budget = parse_budget_inr(text)
        if budget:
            update.budget_inr = str(budget)

    update.location = find_location(text)

    clean = text.strip(" .!")
    shared_pii = "REMOVED]" in text  # e.g. "my aadhaar is [AADHAAR REMOVED]" is not an answer
    if (
        asked_field
        and not shared_pii
        and asked_field != "budget_inr"  # budget is only ever taken as a parsed number
        and getattr(update, asked_field) is None
        and len(clean) >= 2
    ):
        if is_question(clean):
            update.user_question = clean
        else:
            setattr(update, asked_field, clean)
    elif is_question(clean):
        update.user_question = clean
    return update


# =====================================================================
# 2c. EXTRACT (LLM): structured output, with two fallbacks
# =====================================================================

def format_history(messages: list[Message]) -> str:
    recent = messages[-HISTORY_SIZE:]
    if not recent:
        return "(no messages yet)"
    return "\n".join(f"{m.role}: {m.content}" for m in recent)


def profile_json(profile: BusinessProfile, filled_only: bool = False) -> str:
    data = profile.model_dump(exclude={"language"})
    if filled_only:
        data = {k: v for k, v in data.items() if v not in (None, "")}
    return json.dumps(data, ensure_ascii=False, indent=2)


def parse_first_json(text: str) -> dict:
    """Find the first {...} block in a reply (models like to add text around JSON)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in: {text[:200]!r}")
    return json.loads(match.group(0))


def llm_extract(llm: BaseChatModel, profile: BusinessProfile, history: list[Message], message: str) -> ProfileUpdate:
    """Ask the LLM for a ProfileUpdate. Tries 3 ways, from most to least reliable:
    1. json_schema structured output  2. function calling  3. plain text + parse the JSON.
    Raises if all three fail (the caller then uses the rule-based extractor).
    """
    prompt = ChatPromptTemplate.from_messages(
        [("system", load_prompt(EXTRACT_PROMPT)), ("human", "{message}")]
    )
    values = {"profile_json": profile_json(profile), "history": format_history(history), "message": message}

    for method in ("json_schema", "function_calling"):
        try:
            chain = prompt | llm.with_structured_output(ProfileUpdate, method=method)
            result = chain.invoke({**values, "format_instructions": ""})
            if isinstance(result, dict):
                result = ProfileUpdate.model_validate(result)
            if isinstance(result, ProfileUpdate):
                return result
            raise ValueError(f"Unexpected result: {result!r}")
        except Exception as e:  # not supported by this model/provider, or bad output
            logger.warning("Extraction with %s failed: %s", method, e)

    # Last try: ask for raw JSON and dig it out of the text ourselves.
    parser = PydanticOutputParser(pydantic_object=ProfileUpdate)
    raw = (prompt | llm | StrOutputParser()).invoke(
        {**values, "format_instructions": parser.get_format_instructions()}
    )
    return ProfileUpdate.model_validate(parse_first_json(raw))


# =====================================================================
# 3. MERGE
# =====================================================================

EMPTY_VALUES = {"", "null", "none", "unknown", "n/a", "na", "not mentioned", "-"}


def apply_update(profile: BusinessProfile, update: ProfileUpdate) -> dict:
    """Copy non-empty values into the profile. New values overwrite old ones, so users
    can correct themselves. Returns {field: new_value} for what changed."""
    changed = {}
    for field in PROFILE_FIELDS:
        value = getattr(update, field)
        if value is None or str(value).strip().lower() in EMPTY_VALUES:
            continue
        if field == "budget_inr":
            value = parse_budget_inr(value)
            if value is None:  # "some money" -> not a usable budget, keep asking
                continue
        else:
            value = str(value).strip()
        if getattr(profile, field) != value:
            setattr(profile, field, value)
            changed[field] = value
    return changed


def apply_patch(profile: BusinessProfile, patch: dict) -> None:
    """Direct edit from the UI (PATCH endpoint). Unlike chat merges, null / "" CLEARS a field.
    Raises ValueError for a budget we cannot understand."""
    for field, value in patch.items():
        if field == "language":
            if value is not None:
                profile.language = value
            continue
        if value is None or str(value).strip() == "":
            setattr(profile, field, None)
        elif field == "budget_inr":
            budget = parse_budget_inr(value)
            if budget is None:
                raise ValueError(f"Could not understand budget '{value}'. Try e.g. 20000 or '1.5 lakh'.")
            profile.budget_inr = budget
        else:
            setattr(profile, field, str(value).strip())


# =====================================================================
# 4. RESPOND
# =====================================================================

def mock_reply(profile: BusinessProfile, is_first: bool, learned: dict, question: Optional[str], pii: bool) -> str:
    """Fixed template replies (English + Hindi; other languages fall back to English)."""
    t = load_templates()["mock"]
    t = t.get(profile.language, t["en"])
    parts = []
    if is_first:
        parts.append(t["greeting"])
    if pii:
        parts.append(t["privacy"])
    missing = profile.missing_fields()
    if learned and not is_first and missing:  # the summary already says thank you
        parts.append(t["ack"])
    if question and not learned:
        parts.append(t["off_topic"])

    if missing:
        parts.append(t["questions"][missing[0]])
    else:
        lines = [t["summary_title"]]
        for field in PROFILE_FIELDS:
            value = getattr(profile, field)
            if value:
                shown = format_inr(value) if field == "budget_inr" else value
                lines.append(f"- {t['summary_labels'][field]}: {shown}")
        lines.append(t["summary_question"])
        parts.append("\n".join(lines))
    return "\n".join(parts)


def llm_reply(
    llm: BaseChatModel,
    profile: BusinessProfile,
    is_first: bool,
    user_message: str,
    learned: dict,
    question: Optional[str],
    pii: bool,
) -> str:
    """Ask the LLM to write the next message (question or summary) in the session language."""
    common = {
        "language_name": LANGUAGES[profile.language],
        "user_question": question or "none",
        "privacy_warning": "yes" if pii else "no",
    }
    missing = profile.missing_fields()
    if missing:
        field = missing[0]
        info = load_templates()["fields"][field]
        prompt_name = QUESTION_PROMPT
        values = {
            **common,
            "field_label": info["label"],
            "field_hint": info["hint"],
            "field_example": info["example"],
            "is_first_turn": "yes" if is_first else "no",
            "user_message": user_message or "(nothing yet, this is the start)",
            "just_learned": "; ".join(f"{k} = {v}" for k, v in learned.items()) or "nothing new",
        }
    else:
        prompt_name = SUMMARY_PROMPT
        values = {**common, "profile_json": profile_json(profile, filled_only=True)}

    # Sent as a "human" message: some providers reject a chat that has only a system message.
    prompt = ChatPromptTemplate.from_messages([("human", load_prompt(prompt_name))])
    try:
        reply = (prompt | llm | StrOutputParser()).invoke(values).strip()
    except Exception as e:
        raise IntakeLLMError(str(e)) from e
    if not reply:
        raise IntakeLLMError("The model returned an empty reply.")
    return reply


def write_reply(llm, profile, is_first=False, user_message="", learned=None, question=None, pii=False) -> str:
    learned = learned or {}
    if llm is None:
        return mock_reply(profile, is_first, learned, question, pii)
    return llm_reply(llm, profile, is_first, user_message, learned, question, pii)


# =====================================================================
# Public functions used by the API and the CLI
# =====================================================================

def start_session(language: str = "en") -> tuple[Session, str]:
    """Create a session and its first message (greeting + first question). Saves it."""
    llm = None if is_mock() else get_llm()  # LLMConfigError (e.g. no API key) goes to the caller
    reply = write_reply(llm, BusinessProfile(language=language), is_first=True)
    session = create_session(language)
    session.messages.append(Message(role="assistant", content=reply))
    save_session(session)
    return session, reply


def process_message(session: Session, message: str) -> str:
    """Handle one user message: updates `session` in place and returns the reply.
    The caller saves the session (so a failed LLM call leaves the stored session untouched)."""
    llm = None if is_mock() else get_llm()
    profile = session.profile

    # 1. Privacy first: from here on we only use the masked text.
    masked, pii_found = mask_pii(message)
    missing = profile.missing_fields()
    asked_field = missing[0] if missing else None

    # 2. Extract: LLM if available, rules as the safety net.
    update = None
    if llm is not None:
        try:
            update = llm_extract(llm, profile, session.messages, masked)
        except Exception as e:
            logger.warning("All LLM extraction attempts failed, using rules: %s", e)
    if update is None:
        update = rule_based_extract(masked, asked_field)

    # 3. Merge into the profile.
    learned = apply_update(profile, update)

    # 4. Respond.
    reply = write_reply(
        llm, profile, user_message=masked, learned=learned,
        question=update.user_question, pii=bool(pii_found),
    )

    session.messages.append(Message(role="user", content=masked))
    session.messages.append(Message(role="assistant", content=reply))
    return reply
