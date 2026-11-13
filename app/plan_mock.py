"""Fixed plan drafts for mock mode (LLM_PROVIDER=mock): tests and demos without an LLM.

valid   - the healthy-meal example (Rs 20,000 budget). Its schemes are picked from the documents
          actually retrieved, like a well-behaved LLM following plan_v4.
invalid - the same plan broken on purpose: over budget, a promise word and an invented scheme.
          It stays broken on every attempt, so the repair rounds and then auto_fix run.
Choose with generate_plan(mock_variant=...) or the MOCK_PLAN_VARIANT environment variable.
"""
import copy

from app.plan_models import PlanDraft
from app.rag import RetrievedChunk

MOCK_RAW_TEXT = (
    "Business Plan (MOCK MODE - free-text plan_v1 output, not validated)\n"
    "Startup: stove, utensils and boxes about Rs 10,000. Price Rs 170 per meal.\n"
    "Set LLM_PROVIDER=groq or ollama in .env to get real answers."
)

FAKE_SCHEME = {
    "scheme": "PM Free Money Yojana",
    "why_it_fits": "Gives free money to every new business.",
    "source_url": "https://example.com/free-money",
}

VALID_PLAN = {
    "business_summary": "A home kitchen in Ghaziabad that cooks fresh, high-protein lunch boxes for gym-goers. Meals are delivered near 3-4 local gyms. Start small with lunch only and grow with regular monthly customers.",
    "unit_name": "meal",
    "startup_costs": [
        {
            "name": "Gas stove and pressure cooker",
            "amount_inr": 3500,
            "kind": "one_time"
        },
        {
            "name": "Utensils and kitchen scale",
            "amount_inr": 2500,
            "kind": "one_time"
        },
        {
            "name": "Insulated delivery bag and 30 steel boxes",
            "amount_inr": 2000,
            "kind": "one_time"
        },
        {
            "name": "First stock of disposable boxes",
            "amount_inr": 1500,
            "kind": "one_time"
        },
        {
            "name": "Printed menu cards for gyms",
            "amount_inr": 500,
            "kind": "one_time"
        }
    ],
    "fixed_monthly_costs": [
        {
            "name": "Cooking gas",
            "amount_inr": 1200,
            "kind": "monthly"
        },
        {
            "name": "Delivery fuel",
            "amount_inr": 1300,
            "kind": "monthly"
        },
        {
            "name": "Phone and internet",
            "amount_inr": 500,
            "kind": "monthly"
        }
    ],
    "unit_cost_inr": 100,
    "selling_price_inr": 170,
    "market_price_low_inr": 150,
    "market_price_high_inr": 200,
    "units_per_day_low": 5,
    "units_per_day_expected": 10,
    "units_per_day_high": 15,
    "marketing_ideas": [
        "Give free tasting boxes to 2 gym trainers in the first week",
        "Put menu cards at the gym reception with a WhatsApp number",
        "Start a WhatsApp group that shares the daily menu and protein grams",
        "Offer a monthly plan with one free meal for regular customers"
    ],
    "launch_steps": [
        {
            "title": "Fix the menu",
            "detail": "Plan 6 high-protein dishes and write the protein in grams for each.",
            "estimated_days": 3,
            "estimated_cost_inr": None
        },
        {
            "title": "Get FSSAI registration",
            "detail": "Apply for basic FSSAI Registration online on FoSCoS before selling food.",
            "estimated_days": 7,
            "estimated_cost_inr": None
        },
        {
            "title": "Buy equipment",
            "detail": "Buy the stove, utensils, delivery bag and boxes from the startup list.",
            "estimated_days": 2,
            "estimated_cost_inr": 9500
        },
        {
            "title": "Talk to gyms",
            "detail": "Visit 3-4 nearby gyms and ask to keep menu cards at the reception.",
            "estimated_days": 3,
            "estimated_cost_inr": 500
        },
        {
            "title": "Trial week",
            "detail": "Cook for 5 friends or trainers for a week and improve taste and timing.",
            "estimated_days": 7,
            "estimated_cost_inr": None
        },
        {
            "title": "Start taking orders",
            "detail": "Take orders on WhatsApp by 10 am and deliver lunch by 1 pm.",
            "estimated_days": 1,
            "estimated_cost_inr": None
        }
    ],
    "assumptions": [
        "Ingredients for one meal (chicken or paneer, rice, vegetables, box) cost about Rs 100",
        "Gyms nearby allow a menu card at the reception",
        "The owner cooks and delivers alone at the start"
    ],
    "risks": [
        "Fewer orders in the first months until people trust the taste",
        "Ingredient prices (chicken, paneer) can go up",
        "Late deliveries can lose customers"
    ]
}


# Hindi version of the same plan (same numbers), used in mock mode for Hindi in "direct" mode,
# so a Hindi demo works offline. Other languages need a real LLM.
VALID_PLAN_HI = {
    "business_summary": "गाज़ियाबाद में घर की रसोई से जिम जाने वालों के लिए ताज़ा, ज़्यादा प्रोटीन वाला लंच बॉक्स। खाना पास के 3-4 जिम के आसपास पहुँचाया जाएगा। शुरुआत सिर्फ़ दोपहर के खाने से करें और हर महीने वाले पक्के ग्राहक बनाकर आगे बढ़ें।",
    "unit_name": "थाली",
    "startup_costs": [
        {"name": "गैस चूल्हा और प्रेशर कुकर", "amount_inr": 3500, "kind": "one_time"},
        {"name": "बर्तन और रसोई का तराज़ू", "amount_inr": 2500, "kind": "one_time"},
        {"name": "डिलीवरी बैग और 30 स्टील के डिब्बे", "amount_inr": 2000, "kind": "one_time"},
        {"name": "डिस्पोज़ेबल डिब्बों का पहला स्टॉक", "amount_inr": 1500, "kind": "one_time"},
        {"name": "जिम के लिए छपे मेन्यू कार्ड", "amount_inr": 500, "kind": "one_time"},
    ],
    "fixed_monthly_costs": [
        {"name": "रसोई गैस", "amount_inr": 1200, "kind": "monthly"},
        {"name": "डिलीवरी का पेट्रोल", "amount_inr": 1300, "kind": "monthly"},
        {"name": "फ़ोन और इंटरनेट", "amount_inr": 500, "kind": "monthly"},
    ],
    "unit_cost_inr": 100,
    "selling_price_inr": 170,
    "market_price_low_inr": 150,
    "market_price_high_inr": 200,
    "units_per_day_low": 5,
    "units_per_day_expected": 10,
    "units_per_day_high": 15,
    "marketing_ideas": [
        "पहले हफ़्ते में 2 जिम ट्रेनरों को मुफ़्त में खाना चखाएँ",
        "जिम के रिसेप्शन पर अपने व्हाट्सऐप नंबर के साथ मेन्यू कार्ड रखें",
        "एक व्हाट्सऐप ग्रुप बनाएँ जिसमें रोज़ का मेन्यू और प्रोटीन ग्राम में बताएँ",
        "महीने का प्लान लेने वाले ग्राहकों को एक थाली मुफ़्त दें",
    ],
    "launch_steps": [
        {"title": "मेन्यू तय करें", "detail": "ज़्यादा प्रोटीन वाली 6 चीज़ें चुनें और हर एक का प्रोटीन ग्राम में लिखें।", "estimated_days": 3, "estimated_cost_inr": None},
        {"title": "FSSAI रजिस्ट्रेशन कराएँ", "detail": "खाना बेचने से पहले FoSCoS वेबसाइट पर बेसिक FSSAI रजिस्ट्रेशन के लिए आवेदन करें।", "estimated_days": 7, "estimated_cost_inr": None},
        {"title": "सामान खरीदें", "detail": "सूची के हिसाब से चूल्हा, बर्तन, डिलीवरी बैग और डिब्बे खरीदें।", "estimated_days": 2, "estimated_cost_inr": 9500},
        {"title": "जिम से बात करें", "detail": "पास के 3-4 जिम जाएँ और रिसेप्शन पर मेन्यू कार्ड रखने की बात करें।", "estimated_days": 3, "estimated_cost_inr": 500},
        {"title": "एक हफ़्ता आज़माएँ", "detail": "एक हफ़्ते तक 5 दोस्तों या ट्रेनरों के लिए खाना बनाएँ और स्वाद व समय सुधारें।", "estimated_days": 7, "estimated_cost_inr": None},
        {"title": "ऑर्डर लेना शुरू करें", "detail": "सुबह 10 बजे तक व्हाट्सऐप पर ऑर्डर लें और दोपहर 1 बजे तक खाना पहुँचाएँ।", "estimated_days": 1, "estimated_cost_inr": None},
    ],
    "assumptions": [
        "एक थाली की सामग्री (चिकन या पनीर, चावल, सब्ज़ी, डिब्बा) लगभग ₹100 की है",
        "पास के जिम रिसेप्शन पर मेन्यू कार्ड रखने देंगे",
        "शुरुआत में मालिक खुद खाना बनाएँगे और पहुँचाएँगे",
    ],
    "risks": [
        "शुरू के महीनों में ऑर्डर कम आ सकते हैं, जब तक लोग स्वाद पर भरोसा न करें",
        "चिकन और पनीर के दाम बढ़ सकते हैं",
        "देर से डिलीवरी होने पर ग्राहक छूट सकते हैं",
    ],
}
SCHEME_WHY = {
    "en": "Found in the official documents for this business ({category}).",
    "hi": "इस बिज़नेस के लिए सरकारी दस्तावेज़ों में मिली ({category})।",
}


def mock_draft(variant: str, chunks: list[RetrievedChunk], language: str = "en") -> PlanDraft:
    """Build the mock draft for this variant ("valid" or "invalid"). language="hi" gives the
    Hindi version; any other language gets the English plan (mock mode cannot translate)."""
    data = copy.deepcopy(VALID_PLAN_HI if language == "hi" else VALID_PLAN)
    why = SCHEME_WHY.get(language, SCHEME_WHY["en"])
    # Like a grounded LLM: suggest up to 2 schemes that really appear in the retrieved chunks.
    seen = []
    for chunk in chunks:
        if chunk.scheme not in [s["scheme"] for s in seen]:
            seen.append({
                "scheme": chunk.scheme,
                "why_it_fits": why.format(category=chunk.category),
                "source_url": chunk.source_url,
            })
        if len(seen) == 2:
            break
    data["schemes"] = seen

    if variant == "invalid":
        data["startup_costs"].append({"name": "Second-hand food cart", "amount_inr": 25000, "kind": "one_time"})
        data["business_summary"] += (
            " इसमें पहले दिन से पक्का मुनाफा है।" if language == "hi" else " This business gives guaranteed profit from day one."
        )
        data["schemes"].append(dict(FAKE_SCHEME))
    return PlanDraft.model_validate(data)
