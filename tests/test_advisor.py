"""Phase 6: Q&A advisor with memory, tools and guidance (offline, temp DB per test)."""
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage

from app import advisor, db
from app.main import app

client = TestClient(app)
ANSWERS = ["I want to start a healthy tiffin service", "bees hazaar", "I live in Ghaziabad",
           "Basic cooking", "Gym-goers near my home"]


@pytest.fixture
def sid(fake_scheme_index) -> str:
    """A session with a finished intake and a plan (mock meal plan: cost ₹100, price ₹170, fixed ₹3,000)."""
    session_id = client.post("/api/session", json={"language": "en"}).json()["session_id"]
    for text in ANSWERS:
        client.post("/api/chat", json={"session_id": session_id, "message": text})
    assert client.post("/api/plan", json={"session_id": session_id}).status_code == 200
    return session_id


def ask(session_id, question):
    r = client.post("/api/ask", json={"session_id": session_id, "question": question})
    assert r.status_code == 200, r.text
    return r.json()


def test_answer_returned_and_stored(sid):
    data = ask(sid, "What should I do first?")
    assert "Fix the menu" in data["answer"]           # next unfinished checklist step
    assert data["next_step_hint"] == "Fix the menu"
    history = client.get(f"/api/ask/{sid}/history").json()["messages"]
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[0]["content"] == "What should I do first?"
    assert history[1]["content"] == data["answer"]


def test_what_if_routes_to_calculator(sid):
    data = ask(sid, "What if I sell at ₹150?")
    assert "calculate_break_even" in data["used_tools"]
    # 150 - 100 = ₹50 profit per meal; 3000 / 50 = 60 a month; 60 / 26 = 3 a day (all from the calculator)
    assert "₹50" in data["answer"] and "60 a month" in data["answer"] and "3 sales a day" in data["answer"]
    loss = ask(sid, "What if I sell at ₹90?")
    assert "do not make any profit" in loss["answer"]


def test_scheme_question_uses_documents_with_source(sid):
    data = ask(sid, "How do I register for FSSAI?")
    assert data["used_tools"] == ["search_schemes"]
    assert data["sources"] and data["sources"][0]["source_url"].startswith("http")
    stored = client.get(f"/api/ask/{sid}/history").json()["messages"][-1]
    assert stored["sources"] == data["sources"]


def test_off_topic_and_privacy(sid):
    assert "only help with your business" in ask(sid, "Who won the cricket match?")["answer"]
    data = ask(sid, "My aadhaar is 1234 5678 9012, what next?")
    assert "PRIVACY" in data["checks"] and "did not save" in data["answer"]
    history = client.get(f"/api/ask/{sid}/history").json()["messages"]
    assert all("1234 5678 9012" not in m["content"] for m in history)


def test_memory_summarisation_after_10_turns(sid):
    for i in range(10):
        ask(sid, f"Question number {i}?")
    assert advisor.get_memory(sid)["summary"] == ""  # 10 turns: nothing summarised yet
    ask(sid, "Question number 10?")                  # 11th turn
    memory = advisor.get_memory(sid)
    assert "Question number 0" in memory["summary"] and "Question number 4" in memory["summary"]
    assert "Question number 5" not in memory["summary"]  # last 6 turns stay word for word
    text = advisor.memory_text(sid)
    assert text.count("User: ") == 6 and "Summary of older questions" in text


def test_guarantee_language_softened(sid, monkeypatch):
    monkeypatch.setattr(advisor, "mock_answer",
                        lambda *a, **k: ("This plan gives guaranteed profit, it is risk-free.", [], []))
    data = ask(sid, "Will I make money?")
    assert "guaranteed" not in data["answer"].lower() and "risk-free" not in data["answer"].lower()
    assert "GUARANTEE_LANGUAGE" in data["checks"]


def test_tool_calling_failure_falls_back_to_grounded_call(sid, monkeypatch):
    # FakeListChatModel has no bind_tools(), so the ReAct agent fails -> one grounded call.
    llm = FakeListChatModel(responses=["Visit the FSSAI office near you. Numbers are estimates."])
    monkeypatch.setattr(advisor, "is_mock", lambda: False)
    monkeypatch.setattr(advisor, "get_llm", lambda: llm)
    data = ask(sid, "How do I get FSSAI registration?")
    assert data["answer"].startswith("Visit the FSSAI office")
    assert data["used_tools"] == []


class ToolCallingFake(FakeListChatModel):
    """Fake model that CAN call tools: first asks for the break-even tool, then answers."""
    step: int = 0

    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, input, config=None, **kwargs):
        self.step += 1
        if self.step == 1:
            return AIMessage(content="", tool_calls=[{
                "name": "calculate_break_even", "args": {"fixed_monthly_costs": 3000, "profit_per_unit": 50}, "id": "call1"}])
        return AIMessage(content="At ₹150 you need about 3 sales a day. These are estimates.")


def test_react_agent_records_used_tools(sid, monkeypatch):
    monkeypatch.setattr(advisor, "is_mock", lambda: False)
    monkeypatch.setattr(advisor, "get_llm", lambda: ToolCallingFake(responses=["x"]))
    data = ask(sid, "What if I sell at ₹150?")
    assert data["used_tools"] == ["calculate_break_even"]
    assert "3 sales a day" in data["answer"]


def test_history_and_errors(sid):
    assert client.get(f"/api/ask/{sid}/history").json() == {"messages": []}
    assert client.post("/api/ask", json={"session_id": "nope", "question": "hi"}).status_code == 404
    assert client.get("/api/ask/nope/history").status_code == 404
    assert client.post("/api/ask", json={"session_id": sid, "question": "  "}).status_code == 400


def test_guide_picks_first_unfinished_step(sid):
    items = client.get(f"/api/checklist/{sid}").json()["items"]
    card = client.get(f"/api/guide/{sid}").json()
    assert card["next_step"]["title"] == items[0]["title"]
    assert card["progress_line"] == "Let's start with the first step today!"
    for item in items[:2]:
        client.patch(f"/api/checklist/{sid}/{item['id']}", json={"done": True})
    card = client.get(f"/api/guide/{sid}").json()
    assert card["next_step"]["title"] == items[2]["title"]
    assert card["progress_line"] == "You have finished 2 of 6 steps!"
    assert items[2]["detail"] in card["tip"]
    assert client.get("/api/guide/nope").status_code == 404


def test_guide_without_plan():
    session_id = client.post("/api/session", json={"language": "ta"}).json()["session_id"]
    card = client.get(f"/api/guide/{session_id}").json()
    assert card["next_step"] is None and card["progress"]["total"] == 0
    assert card["progress_line"] == "இன்று முதல் படியைத் தொடங்குவோம்!"


def test_qa_survives_restart(sid, temp_database):
    ask(sid, "What should I do first?")
    db._initialized.clear()  # forget connections, like a restarted server
    assert len(client.get(f"/api/ask/{sid}/history").json()["messages"]) == 2
