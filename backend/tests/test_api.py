from __future__ import annotations

import unittest
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk

from backend.app.main import app, runtime_dependency
from backend.app.db import repository
from backend.app.schemas.article import ArticleAnalysis, PharmaTerm
from backend.app.services.recommendations import fallback_recommendations
from backend.app.retrieval.service import search_study_memory


class FakeArticleChain:
    def invoke(self, payload):
        self.article = payload["article"]
        return ArticleAnalysis(
            article_type="임상",
            one_line_summary="가상 후보물질의 초기 평가 계획을 설명합니다.",
            key_issue="평가 목적과 결과를 구분합니다.",
            key_entities=["가상 후보물질"],
            key_terms=[PharmaTerm(
                term="임상 1상", category="Clinical Trial", reason="개발 단계를 이해합니다.",
                simple_definition="사람에게 처음 투여해 주로 안전성을 살피는 단계입니다.",
                article_context="가상 후보물질의 초기 시험입니다.", aliases=["Phase 1"],
            )],
            confusing_points=[],
        )


class FakeGraph:
    def invoke(self, payload):
        self.payload = payload
        return {
            "answer": "가상 자료에는 결과가 아직 보고되지 않았습니다.",
            "route": "article",
            "related_to_selected": True,
            "sources": [],
            "validation_status": "pass",
            "validation_retries": 0,
            "recommendations": fallback_recommendations("임상 1상"),
        }

    async def astream_events(self, payload, version):
        self.payload = payload
        self.version = version
        yield {"event": "on_chain_start", "metadata": {"langgraph_node": "answer"}}
        yield {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "answer"},
            "data": {"chunk": AIMessageChunk(content='{"answer":"DRAFT_UNVALIDATED')},
        }
        yield {"event": "on_chain_start", "metadata": {"langgraph_node": "validator"}}
        yield {
            "event": "on_chain_end",
            "metadata": {},
            "data": {"output": {
                "answer": "검증된 답변을 조각으로 전달합니다.",
                "route": "article",
                "related_to_selected": True,
                "sources": [],
                "validation_status": "pass",
                "validation_retries": 0,
                "recommendations": fallback_recommendations("임상 1상"),
            }},
        }


class FakeRuntime:
    def __init__(self):
        self.article_chain = FakeArticleChain()
        self.agent_graph = FakeGraph()


class FixedEmbeddings:
    model_name = "fixed-test-embeddings"

    def embed_documents(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.0]


class BrokenEmbeddings(FixedEmbeddings):
    def embed_documents(self, texts):
        raise RuntimeError("synthetic embedding outage")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.previous_db_path = repository.DB_PATH
        self.temp_dir = tempfile.TemporaryDirectory(prefix="pharmamate-api-test-")
        repository.configure_database(self.temp_dir.name)
        self.runtime = FakeRuntime()
        app.dependency_overrides[runtime_dependency] = lambda: self.runtime
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        repository.DB_PATH = self.previous_db_path
        self.temp_dir.cleanup()

    def test_health_does_not_load_keys_or_database(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_article_analysis_uses_pasted_fixture_and_returns_id(self):
        body = "가상 임상 자료입니다. 안전성과 내약성을 평가하기 위한 초기 시험을 시작했습니다. " * 10
        response = self.client.post("/api/articles/analyze", json={"pasted_text": body})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["analysis"]["article_type"], "임상")
        self.assertEqual(payload["load_method"], "manual")
        self.assertTrue(payload["article_id"])
        self.assertEqual(self.runtime.article_chain.article, body.strip())

    def test_empty_article_request_returns_validation_error(self):
        response = self.client.post("/api/articles/analyze", json={})
        self.assertEqual(response.status_code, 422)

    def test_chat_returns_validator_and_recommendation_fields(self):
        response = self.client.post("/api/chat", json={
            "question": "임상 1상에서 무엇을 살펴봐?",
            "article": "가상 시험 계획 자료",
            "term": "임상 1상",
            "history": [{"question": "임상시험은 뭐야?", "answer": "사람을 대상으로 평가합니다."}],
        })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["validation_status"], "pass")
        self.assertTrue(payload["related_to_selected"])
        self.assertEqual(len(payload["recommendations"]), 3)
        self.assertIn("임상시험은 뭐야?", self.runtime.agent_graph.payload["history"])

    def test_sse_stream_sends_only_the_validated_answer(self):
        with self.client.stream("POST", "/api/chat/stream", json={"question": "임상 1상은 뭐야?"}) as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["content-type"].split(";")[0], "text/event-stream")
            body = "".join(response.iter_text())
        self.assertIn("event: status", body)
        self.assertIn("event: token", body)
        self.assertIn("검증된 답변", body)
        self.assertNotIn("DRAFT_UNVALIDATED", body)
        self.assertIn("event: sources", body)
        self.assertIn("event: recommendations", body)
        self.assertIn("event: done", body)
        self.assertIn('"related_to_selected":true', body)

    def test_study_record_save_only_links_questions_marked_relevant(self):
        request = {
            "term": {
                "term": "항체-약물 접합체 (ADC)",
                "category": "Modality",
                "reason": "기사 이해에 필요합니다.",
                "simple_definition": "항체가 약물을 표적 세포에 전달하도록 돕습니다.",
                "article_context": "가상 기사에서 후보 기술로 언급됩니다.",
                "aliases": ["ADC"],
            },
            "article_id": "fixture-article-01",
            "article_url": "https://example.org/article",
            "note": "검토된 합성 학습 메모",
            "history": [
                {"question": "항체는 무슨 역할이야?", "answer": "표적에 결합합니다.", "linked_to_selected": True},
                {"question": "CAR-T는 뭐야?", "answer": "다른 질문입니다.", "linked_to_selected": False},
            ],
        }
        with patch.object(repository, "save_learning_bundle", return_value=(False, "adc", 1, 1, "note")) as save:
            response = self.client.post("/api/study-records", json=request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["new_questions"], 1)
        saved_state = save.call_args.args[1]
        self.assertEqual(saved_state["history"][0]["linked_term_key"], "adc")
        self.assertEqual(saved_state["history"][1]["linked_term_key"], "")

    def test_anonymous_session_restores_article_and_chat_only_with_its_token(self):
        created = self.client.post("/api/sessions")
        self.assertEqual(created.status_code, 200)
        session = created.json()
        session_id = session["session_id"]
        token = session["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        self.assertNotIn(token, repository.get_study_session(session_id)["token_hash"])
        self.assertEqual(self.client.get(f"/api/sessions/{session_id}").status_code, 404)
        self.assertEqual(self.client.get(
            f"/api/sessions/{session_id}", headers={"Authorization": "Bearer wrong-token"}
        ).status_code, 404)

        analyzed = self.client.post("/api/articles/analyze", json={
            "pasted_text": "가상 기사에서 임상 1상 계획을 설명합니다. " * 10,
        }).json()
        saved_article = self.client.put(
            f"/api/sessions/{session_id}/article",
            headers=headers,
            json={"article": analyzed, "selected_term_key": "임상 1상"},
        )
        self.assertEqual(saved_article.status_code, 200)

        with self.client.stream(
            "POST", f"/api/sessions/{session_id}/chat/stream", headers=headers,
            json={"question": "임상 1상에서 무엇을 확인해?", "term": "임상 1상\n안전성을 살핍니다."},
        ) as response:
            body = "".join(response.iter_text())
        self.assertEqual(response.status_code, 200)
        self.assertIn("검증된 답변", body)
        self.assertEqual(self.runtime.agent_graph.payload["owner_id"], session_id)
        self.assertEqual(self.runtime.agent_graph.payload["article"], analyzed["article"])

        restored = self.client.get(f"/api/sessions/{session_id}", headers=headers)
        self.assertEqual(restored.status_code, 200)
        snapshot = restored.json()
        self.assertEqual(snapshot["article"]["article_id"], analyzed["article_id"])
        self.assertEqual(len(snapshot["turns"]), 1)
        self.assertEqual(snapshot["turns"][0]["question"], "임상 1상에서 무엇을 확인해?")

        second = self.client.post("/api/sessions").json()
        other = self.client.get(
            f"/api/sessions/{second['session_id']}",
            headers={"Authorization": f"Bearer {second['access_token']}"},
        ).json()
        self.assertIsNone(other["article"])
        self.assertEqual(other["turns"], [])

    def test_session_learning_memory_is_private_and_saves_only_relevant_turns(self):
        first = self.client.post("/api/sessions").json()
        second = self.client.post("/api/sessions").json()
        headers = {"Authorization": f"Bearer {first['access_token']}"}
        article = self.client.post("/api/articles/analyze", json={
            "pasted_text": "가상 기사에서 임상 1상 계획을 설명합니다. " * 10,
        }).json()
        self.client.put(f"/api/sessions/{first['session_id']}/article", headers=headers,
                        json={"article": article, "selected_term_key": "임상 1상"})
        with self.client.stream(
            "POST", f"/api/sessions/{first['session_id']}/chat/stream", headers=headers,
            json={"question": "임상 1상에서 무엇을 확인해?", "term": "임상 1상"},
        ) as response:
            list(response.iter_text())
        term = article["analysis"]["key_terms"][0]
        saved = self.client.post(
            f"/api/sessions/{first['session_id']}/study-records",
            headers=headers,
            json={"term": term, "note": "안전성과 내약성을 우선 살핍니다."},
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["new_questions"], 1)
        records = self.client.get(
            f"/api/sessions/{first['session_id']}/study-records", headers=headers
        ).json()
        self.assertEqual(records[0]["qa_count"], 1)

        first_memory = search_study_memory(
            "임상 1상 안전성", owner_id=first["session_id"], embedding_provider=FixedEmbeddings()
        )
        second_memory = search_study_memory(
            "임상 1상 안전성", owner_id=second["session_id"], embedding_provider=FixedEmbeddings()
        )
        self.assertTrue(first_memory)
        self.assertEqual(second_memory, [])
        first_fallback = search_study_memory(
            "임상 1상 안전성", owner_id=first["session_id"], embedding_provider=BrokenEmbeddings()
        )
        second_fallback = search_study_memory(
            "임상 1상 안전성", owner_id=second["session_id"], embedding_provider=BrokenEmbeddings()
        )
        self.assertTrue(first_fallback)
        self.assertEqual(second_fallback, [])


if __name__ == "__main__":
    unittest.main()
