"""Phase 6: the launch checklist on the server (temp DB per test, mock LLM)."""
import pytest
from fastapi.testclient import TestClient

from app import checklist
from app.main import app
from app.plan_models import LaunchStep

client = TestClient(app)
ANSWERS = ["I want to start a healthy tiffin service", "bees hazaar", "I live in Ghaziabad",
           "Basic cooking", "Gym-goers near my home"]


@pytest.fixture
def planned_session(fake_scheme_index) -> str:
    sid = client.post("/api/session", json={"language": "en"}).json()["session_id"]
    for text in ANSWERS:
        client.post("/api/chat", json={"session_id": sid, "message": text})
    assert client.post("/api/plan", json={"session_id": sid}).status_code == 200
    return sid


def get(sid):
    return client.get(f"/api/checklist/{sid}").json()


def test_plan_creates_checklist(planned_session):
    data = get(planned_session)
    plan = client.get(f"/api/plan/{planned_session}").json()
    assert [i["title"] for i in data["items"]] == [s["title"] for s in plan["draft"]["launch_steps"]]
    assert data["progress"] == {"done": 0, "total": 6, "percent": 0}
    assert not any(i["is_custom"] for i in data["items"])


def test_tick_and_untick(planned_session):
    first = get(planned_session)["items"][0]["id"]
    data = client.patch(f"/api/checklist/{planned_session}/{first}", json={"done": True}).json()
    assert data["items"][0]["done"] is True and data["items"][0]["done_at"]
    assert data["progress"] == {"done": 1, "total": 6, "percent": 17}
    data = client.patch(f"/api/checklist/{planned_session}/{first}", json={"done": False}).json()
    assert data["items"][0]["done"] is False and data["items"][0]["done_at"] is None


def test_custom_step_add_and_delete(planned_session):
    r = client.post(f"/api/checklist/{planned_session}", json={"title": "Buy a weighing scale", "detail": "Digital one"})
    assert r.status_code == 201
    items = r.json()["items"]
    custom = items[-1]
    assert custom["is_custom"] is True and custom["title"] == "Buy a weighing scale" and custom["position"] == 6
    r = client.delete(f"/api/checklist/{planned_session}/{custom['id']}")
    assert r.status_code == 200 and len(r.json()["items"]) == 6


def test_cannot_delete_plan_step(planned_session):
    plan_step = get(planned_session)["items"][0]["id"]
    r = client.delete(f"/api/checklist/{planned_session}/{plan_step}")
    assert r.status_code == 403


def test_errors(planned_session):
    assert client.get("/api/checklist/nope").status_code == 404
    assert client.patch(f"/api/checklist/{planned_session}/99999", json={"done": True}).status_code == 404
    assert client.delete(f"/api/checklist/{planned_session}/99999").status_code == 404
    assert client.post(f"/api/checklist/{planned_session}", json={"title": ""}).status_code == 422
    assert client.post(f"/api/checklist/{planned_session}", json={"title": "   "}).status_code == 400


def test_regeneration_keeps_custom_and_done(planned_session):
    items = get(planned_session)["items"]
    client.patch(f"/api/checklist/{planned_session}/{items[1]['id']}", json={"done": True})  # "Get FSSAI registration"
    client.patch(f"/api/checklist/{planned_session}/{items[0]['id']}", json={"done": True})  # "Fix the menu"
    client.post(f"/api/checklist/{planned_session}", json={"title": "My own step"})

    # New plan: step 0 renamed, step 1 same title (different case/spaces), one step removed.
    new_steps = [
        LaunchStep(title="Fix a new menu", detail="x", estimated_days=1),
        LaunchStep(title="get  FSSAI registration", detail="y", estimated_days=7),
        LaunchStep(title="Start taking orders", detail="z", estimated_days=1),
    ]
    result = checklist.sync_from_plan(planned_session, new_steps)
    assert [(i.title, i.done, i.is_custom) for i in result] == [
        ("Fix a new menu", False, False),
        ("get  FSSAI registration", True, False),   # done kept: same title
        ("Start taking orders", False, False),
        ("My own step", False, True),               # custom kept, moved after plan steps
    ]
    assert [i.position for i in result] == [0, 1, 2, 3]


def test_regenerating_through_api_keeps_ticks(planned_session):
    first = get(planned_session)["items"][0]["id"]
    client.patch(f"/api/checklist/{planned_session}/{first}", json={"done": True})
    client.post("/api/plan", json={"session_id": planned_session})  # same mock steps again
    data = get(planned_session)
    assert data["items"][0]["done"] is True and data["progress"]["done"] == 1
