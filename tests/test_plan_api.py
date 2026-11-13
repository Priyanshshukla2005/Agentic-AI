"""Phase 4 API tests (offline, mock mode)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PROFILE = {
    "business_idea": "Healthy meal service", "budget_inr": 20000, "location": "Ghaziabad",
    "skills": "Basic cooking", "target_customers": "Gym-goers",
}
ANSWERS = ["I want to start a healthy tiffin service", "bees hazaar", "I live in Ghaziabad",
           "Basic cooking", "Gym-goers near my home"]


@pytest.fixture(autouse=True)
def _index(fake_scheme_index):
    yield


def finished_session() -> str:
    sid = client.post("/api/session", json={"language": "en"}).json()["session_id"]
    for text in ANSWERS:
        data = client.post("/api/chat", json={"session_id": sid, "message": text}).json()
    assert data["is_complete"]
    return sid


def test_plan_for_session_and_get():
    sid = finished_session()
    r = client.post("/api/plan", json={"session_id": sid})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["validation"]["passed"] is True
    assert plan["sources"] and plan["financials"]["break_even"]["units_per_day"] == 2
    assert plan["prompt_version"] == "plan_v5"

    saved = client.get(f"/api/plan/{sid}")
    assert saved.status_code == 200
    assert saved.json()["generated_at"] == plan["generated_at"]


def test_incomplete_profile_gives_409():
    sid = client.post("/api/session", json={"language": "en"}).json()["session_id"]
    r = client.post("/api/plan", json={"session_id": sid})
    assert r.status_code == 409
    assert r.json()["detail"]["missing_fields"][0] == "business_idea"


def test_unknown_session_gives_404():
    assert client.post("/api/plan", json={"session_id": "nope"}).status_code == 404
    assert client.get("/api/plan/nope").status_code == 404


def test_get_before_generating_gives_404():
    sid = finished_session()
    r = client.get(f"/api/plan/{sid}")
    assert r.status_code == 404 and "POST /api/plan" in r.json()["detail"]


def test_preview():
    r = client.post("/api/plan/preview", json={"profile": PROFILE, "prompt_version": "plan_v3"})
    assert r.status_code == 200 and r.json()["prompt_version"] == "plan_v3"
    incomplete = client.post("/api/plan/preview", json={"profile": {"business_idea": "Tea"}})
    assert incomplete.status_code == 409
    assert client.post("/api/plan/preview", json={"profile": PROFILE, "prompt_version": "plan_v9"}).status_code == 422


def test_compare_all_versions():
    versions = ["plan_v1", "plan_v2", "plan_v3", "plan_v4"]
    r = client.post("/api/plan/compare", json={"profile": PROFILE, "versions": versions})
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    assert [x["prompt_version"] for x in results] == versions
    assert results[0]["passed"] is None and results[0]["plan"]["raw_text"]
    assert all(x["passed"] is True for x in results[1:])
    assert all("seconds" in x and x["plan"]["timings"] for x in results)
