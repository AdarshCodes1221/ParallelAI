import os
import sys
import asyncio
from types import SimpleNamespace
from pathlib import Path

import pytest

pytest.importorskip("redis")
sys.path.insert(0, str(Path(__file__).parents[1]))

from agent.planner import Planner
from agent.dependency_resolver import topological_layers
from services.session_service import SessionService
from services.query_context_resolver import QueryContextResolver
from services.rag_service import RAGService
import agent.workflow as workflow_module
import routes.api as api_module


class FakeRedis:
    def __init__(self):
        self.data = {}

    def hset(self, key, mapping):
        self.data.setdefault(key, {}).update(mapping)

    def hgetall(self, key):
        return self.data.get(key, {})

    def lpush(self, key, value):
        self.data.setdefault(key, []).insert(0, value)

    def ltrim(self, key, start, end):
        self.data[key] = self.data[key][start:end + 1]

    def pipeline(self):
        return self

    def execute(self):
        return None

    def lrange(self, key, start, end):
        return self.data.get(key, [])[start:] if end == -1 else self.data.get(key, [])[start:end + 1]

    def smembers(self, key):
        return self.data.get(key, set())

    def sadd(self, key, *values):
        s = self.data.setdefault(key, set())
        for v in values:
            s.add(v)

    def srem(self, key, *values):
        s = self.data.get(key, set())
        for v in values:
            s.discard(v)

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value


class FakeStore:
    def __init__(self):
        self.client = FakeRedis()

    def hset_json(self, key, value):
        import json
        self.client.hset(key, {name: json.dumps(item) for name, item in value.items()})

    def hgetall_json(self, key):
        import json
        return {name: json.loads(value) for name, value in self.client.hgetall(key).items()}

    def lpush_json(self, key, value, max_length=None):
        import json
        self.client.lpush(key, json.dumps(value))

    def lrange_json(self, key, start=0, end=-1):
        import json
        return [json.loads(item) for item in self.client.lrange(key, start, end)]


def test_session_memory_round_trip():
    service = SessionService(FakeStore())
    session = service.create("session-test")
    service.save_message(session["id"], "user", "I uploaded my CV")
    service.save_message(session["id"], "assistant", "Your CV is indexed")
    assert service.get("session-test")["id"] == "session-test"
    assert [item["role"] for item in service.recent_messages("session-test")] == ["user", "assistant"]


def test_planner_places_retrieval_after_ingestion():
    plan = Planner.create_plan(["pdf_parser", "rag_search"])
    layers = topological_layers(plan)
    assert [node["tool"] for node in layers[0]] == ["pdf_parser"]
    assert [node["tool"] for node in layers[1]] == ["rag_search"]


def test_previous_document_context_reaches_workflow(monkeypatch):
    calls = {}

    class FakeRAG:
        def __init__(self, api_key):
            calls["api_key"] = api_key

        def search_results(self, query, top_k, document_ids, session_id, user_id=None):
            calls["retrieval"] = (query, top_k, document_ids, session_id)
            return [{"id": "chunk-1", "document_id": "resume-test", "filename": "resume.pdf", "text": "Project Atlas uses AWS Lambda and S3."}]

    monkeypatch.setattr(workflow_module, "RAGService", FakeRAG)
    monkeypatch.setattr(workflow_module.IntentDetector, "detect", lambda *args: SimpleNamespace(
        required_tools=[], is_ambiguous=False, model_dump=lambda: {"primary_intent": "question"}
    ))
    monkeypatch.setattr(workflow_module, "_generate_text", lambda **kwargs: "Project Atlas is the strongest project. [S1]")

    result = asyncio.run(workflow_module.AgentWorkflow.execute(
        "What are my strongest projects?",
        [],
        "test-key",
        session_id="session-test",
        active_document_ids=["resume-test"],
        recent_messages=[{"role": "user", "content": "I uploaded my CV"}],
    ))

    assert calls["retrieval"] == ("What are my strongest projects?", 8, ["resume-test"], "session-test")
    assert "Project Atlas" in result["final_response"]


def test_query_context_resolver_skips_unrelated_questions():
    documents = [{"id": "resume-test", "status": "READY", "filename": "resume.pdf"}]
    assert QueryContextResolver.resolve("Who is the president of India?", documents).use_retrieval is False
    context = QueryContextResolver.resolve("What AWS services did I mention in my resume?", documents)
    assert context.use_retrieval is True
    assert context.document_ids == ["resume-test"]


def test_rag_parser_handles_variable_search_shapes():
    fields = {"id": "chunk-1", "text": "evidence", "document_id": "doc-1"}
    assert RAGService._parse_search_results({"total_results": 1, "results": [fields]}) == [fields]
    assert RAGService._parse_search_results([1, "chunk:chunk-1", ["id", "chunk-1", "text", "evidence"]]) == [{"id": "chunk-1", "text": "evidence"}]
    assert RAGService._parse_search_results([]) == []


def test_agent_persists_authenticated_uuid_not_default_user(monkeypatch):
    calls = []
    real_user_id = "11111111-1111-1111-1111-111111111111"

    class FakeSessionService:
        def create(self, *args, **kwargs):
            calls.append(("create", kwargs.get("user_id")))
            return {"id": "agent-auth-session"}

        def get(self, *args, **kwargs):
            return None

        def save_message(self, *args, **kwargs):
            calls.append(("save_message", kwargs.get("user_id")))

        def recent_messages(self, *args, **kwargs):
            return []

    async def fake_user(*args, **kwargs):
        return {"id": real_user_id}

    async def fake_execute(*args, **kwargs):
        return {"plan": [], "tool_results": {}, "final_response": "HI", "provider": "local", "citations": []}

    monkeypatch.setattr(api_module, "session_service", FakeSessionService())
    monkeypatch.setattr(api_module, "get_current_user_optional", fake_user)
    monkeypatch.setattr(api_module.AgentWorkflow, "execute", fake_execute)

    from starlette.requests import Request
    request = Request({"type": "http", "method": "POST", "path": "/api/agent", "headers": [], "query_string": b""})
    response = asyncio.run(api_module.run_agent(
        request=request,
        session_id="",
        query="HI",
        model="models/gemini-2.5-flash",
        files=[],
        current_user={"id": real_user_id},
    ))
    asyncio.run(response.body_iterator.__anext__())

    assert calls
    assert all(user_id == real_user_id for _, user_id in calls)
    assert all(user_id != "default_user" for _, user_id in calls)
