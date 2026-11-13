"""Phase 2 tests. Run:  pytest -v   (works offline, LLM_PROVIDER=mock is forced in conftest.py)"""
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app import intake
from app.config import settings
from app.intake import mask_pii, parse_budget_inr, rule_based_extract
from app.main import app
from app.models import BusinessProfile

client = TestClient(app)


def test_runs_in_mock_mode():
    assert settings.LLM_PROVIDER == "mock"


# ---------- Budget parsing ----------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("20000", 20_000),
        ("20,000", 20_000),
        ("₹20,000", 20_000),
        ("Rs. 20k", 20_000),
        ("20k", 20_000),
        ("1.5 lakh", 150_000),
        ("2 lakh", 200_000),
        ("50 hazaar", 50_000),
        ("bees hazaar", 20_000),
        ("bees hazar", 20_000),
        ("dedh lakh", 150_000),
        ("pachas hazaar rupaye", 50_000),
        ("₹1,50,000", 150_000),
        ("mere paas 2 lakh hai", 200_000),
        ("बीस हज़ार", 20_000),
        ("my budget is twenty thousand", 20_000),
        (35000, 35_000),
    ],
)
def test_parse_budget(text, expected):
    assert parse_budget_inr(text) == expected


@pytest.mark.parametrize("text", ["", "some money", "0", "20kg tomatoes", None, -5])
def test_parse_budget_rejects_non_amounts(text):
    assert parse_budget_inr(text) is None


# ---------- Privacy ----------

def test_masks_aadhaar():
    masked, found = mask_pii("my aadhaar is 1234 5678 9012")
    assert "1234" not in masked and "[AADHAAR REMOVED]" in masked
    assert found == ["aadhaar"]


def test_masks_pan():
    masked, found = mask_pii("PAN: ABCDE1234F")
    assert "ABCDE1234F" not in masked and found == ["pan"]


def test_masks_phone():
    for phone in ["9876543210", "+91 98765 43210", "098765-43210"]:
        masked, found = mask_pii(f"call me on {phone}")
        assert "[PHONE REMOVED]" in masked and found == ["phone"], phone


def test_masks_bank_account():
    masked, found = mask_pii("my account number is 123456789012")
    assert "123456789012" not in masked and found == ["bank_account"]


def test_budget_is_not_masked():
    masked, found = mask_pii("budget 20000, I want 1.5 lakh")
    assert masked == "budget 20000, I want 1.5 lakh" and found == []


# ---------- Profile ----------

def test_missing_fields_order_and_is_complete():
    p = BusinessProfile()
    assert p.missing_fields() == ["business_idea", "budget_inr", "location", "skills", "target_customers"]
    assert not p.is_complete

    p.location = "Pune"
    p.budget_inr = 10_000
    assert p.missing_fields() == ["business_idea", "skills", "target_customers"]

    p.business_idea, p.skills, p.target_customers = "pickles", "cooking", "neighbours"
    assert p.missing_fields() == [] and p.is_complete
    p.time_available = None  # optional fields never block completion
    assert p.is_complete


# ---------- Rule-based extractor ----------

def test_rules_find_budget_and_location_anywhere():
    u = rule_based_extract("I live in Indore and have Rs 30k", asked_field="business_idea")
    assert u.location == "Indore" and parse_budget_inr(u.budget_inr) == 30_000


def test_rules_hinglish_location():
    assert rule_based_extract("main Lucknow mein rehta hoon", "location").location == "Lucknow"


def test_rules_use_whole_reply_for_asked_field():
    assert rule_based_extract("Office workers and students", "target_customers").target_customers == (
        "Office workers and students"
    )


def test_rules_question_is_not_an_answer():
    u = rule_based_extract("Do I need a licence?", "skills")
    assert u.skills is None and u.user_question == "Do I need a licence?"


# ---------- API flow (mock mode) ----------

def answer_all(session_id):
    answers = [
        "I want to sell homemade mango pickles",
        "bees hazaar",
        "I live in Lucknow",
        "I make very tasty pickles, learnt from my mother",
        "Families and office workers in my area",
    ]
    data = None
    for text in answers:
        r = client.post("/api/chat", json={"session_id": session_id, "message": text})
        assert r.status_code == 200, r.text
        data = r.json()
    return data


def test_full_flow_until_complete():
    r = client.post("/api/session", json={"language": "en"})
    assert r.status_code == 200
    start = r.json()
    assert start["is_complete"] is False
    assert start["missing_fields"][0] == "business_idea"
    assert "business" in start["reply"].lower()

    data = answer_all(start["session_id"])
    assert data["is_complete"] is True
    assert data["missing_fields"] == []
    p = data["profile"]
    assert p["budget_inr"] == 20_000
    assert p["location"] == "Lucknow"
    assert "pickles" in p["business_idea"]
    assert "business plan" in data["reply"].lower()

    # Session keeps all messages: greeting + 5 x (user + assistant)
    full = client.get(f"/api/session/{start['session_id']}").json()
    assert len(full["messages"]) == 11


def test_questions_follow_missing_order():
    sid = client.post("/api/session", json={"language": "en"}).json()["session_id"]
    data = client.post("/api/chat", json={"session_id": sid, "message": "Tea stall"}).json()
    assert data["missing_fields"][0] == "budget_inr"
    assert "money" in data["reply"].lower()


def test_hindi_session_uses_hindi_questions():
    r = client.post("/api/session", json={"language": "hi"}).json()
    assert "बिज़नेस" in r["reply"]
    assert r["profile"]["language"] == "hi"


def test_budget_correction_updates_profile():
    sid = client.post("/api/session", json={"language": "en"}).json()["session_id"]
    data = answer_all(sid)
    assert data["profile"]["budget_inr"] == 20_000

    data = client.post("/api/chat", json={"session_id": sid, "message": "Sorry, my budget is actually 1.5 lakh"}).json()
    assert data["profile"]["budget_inr"] == 150_000
    assert data["is_complete"] is True


def test_pii_is_masked_and_user_is_told():
    sid = client.post("/api/session", json={"language": "en"}).json()["session_id"]
    data = client.post(
        "/api/chat", json={"session_id": sid, "message": "Samosa shop. My phone is 9876543210"}
    ).json()
    assert "not save" in data["reply"].lower()
    stored = client.get(f"/api/session/{sid}").json()
    assert all("9876543210" not in m["content"] for m in stored["messages"])
    assert "9876543210" not in str(stored["profile"])


def test_message_with_only_pii_is_not_taken_as_answer():
    sid = client.post("/api/session", json={"language": "en"}).json()["session_id"]
    data = client.post("/api/chat", json={"session_id": sid, "message": "my aadhaar is 1234 5678 9012"}).json()
    assert data["profile"]["business_idea"] is None
    assert data["missing_fields"][0] == "business_idea"


def test_off_topic_question_then_back_to_intake():
    sid = client.post("/api/session", json={"language": "en"}).json()["session_id"]
    data = client.post("/api/chat", json={"session_id": sid, "message": "Is GST needed?"}).json()
    assert "good question" in data["reply"].lower()
    assert data["missing_fields"][0] == "business_idea"  # still asking the same thing


def test_patch_profile():
    sid = client.post("/api/session", json={"language": "en"}).json()["session_id"]
    r = client.patch(f"/api/session/{sid}/profile", json={"budget_inr": "2 lakh", "location": "Surat"})
    assert r.status_code == 200
    assert r.json()["profile"]["budget_inr"] == 200_000
    assert r.json()["missing_fields"] == ["business_idea", "skills", "target_customers"]

    bad = client.patch(f"/api/session/{sid}/profile", json={"budget_inr": "lots"})
    assert bad.status_code == 422
    typo = client.patch(f"/api/session/{sid}/profile", json={"budjet": 5})
    assert typo.status_code == 422


def test_errors_404_and_422():
    assert client.post("/api/session", json={"language": "fr"}).status_code == 422
    assert client.get("/api/session/does-not-exist").status_code == 404
    assert client.post("/api/chat", json={"session_id": "nope", "message": "hi"}).status_code == 404
    assert client.patch("/api/session/nope/profile", json={}).status_code == 404


def test_phase1_endpoints_still_work():
    assert client.get("/health").json()["status"] == "ok"
    r = client.post(
        "/api/test-prompt",
        json={"business_idea": "Meals", "budget": "Rs 20,000", "location": "Ghaziabad",
              "skills": "Cooking", "target_customers": "Gym-goers"},
    )
    assert r.status_code == 200 and "MOCK" in r.json()["output"]


# ---------- LLM path, with a fake model (still offline) ----------

def use_fake_llm(monkeypatch, responses):
    monkeypatch.setattr(intake, "is_mock", lambda: False)
    monkeypatch.setattr(intake, "get_llm", lambda: FakeListChatModel(responses=responses))


def test_llm_extraction_falls_back_to_raw_json(monkeypatch):
    # The fake model cannot do structured output, so json_schema and function_calling fail
    # and the code must dig the JSON out of a chatty text reply.
    sid = client.post("/api/session", json={"language": "en"}).json()["session_id"]
    use_fake_llm(monkeypatch, [
        'Sure! {"business_idea": "tiffin service", "budget_inr": "dedh lakh", "location": "Pune"}',
        "Nice! What are you good at? (Example: cooking)",
    ])
    data = client.post("/api/chat", json={"session_id": sid, "message": "tiffin in Pune, dedh lakh"}).json()
    assert data["profile"]["budget_inr"] == 150_000
    assert data["profile"]["location"] == "Pune"
    assert data["missing_fields"] == ["skills", "target_customers"]
    assert data["reply"].startswith("Nice!")


def test_llm_failure_returns_502_and_keeps_session(monkeypatch):
    sid = client.post("/api/session", json={"language": "en"}).json()["session_id"]

    class BrokenLLM(FakeListChatModel):
        def _call(self, *args, **kwargs):
            raise ConnectionError("network down")

    monkeypatch.setattr(intake, "is_mock", lambda: False)
    monkeypatch.setattr(intake, "get_llm", lambda: BrokenLLM(responses=["x"]))
    r = client.post("/api/chat", json={"session_id": sid, "message": "Tea stall"})
    assert r.status_code == 502 and "LLM call failed" in r.json()["detail"]
    assert len(client.get(f"/api/session/{sid}").json()["messages"]) == 1  # nothing saved
