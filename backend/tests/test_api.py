from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk

from backend.app.main import app, runtime_dependency
from backend.app.db import repository
from backend.app.schemas.article import ArticleAnalysis, ManualTermClassification, PharmaTerm
from backend.app.services.recommendations import fallback_recommendations
from backend.app.retrieval.service import search_study_memory


class FakeArticleChain:
    def invoke(self, payload):
        self.payload = payload
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


class FakeManualTermChain:
    def invoke(self, payload):
        self.payload = payload
        return ManualTermClassification(
            category="Mechanism",
            reason="치료 기술이 작동하는 원리를 설명합니다.",
            simple_definition="표적 단백질이 분해되도록 유도하는 방식입니다.",
            article_context=payload["article_context"],
            aliases=[],
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
            "answer_revisions": 0,
            "evidence_searches": 1,
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
                "answer_revisions": 0,
                "evidence_searches": 1,
                "recommendations": fallback_recommendations("임상 1상"),
            }},
        }


class FakeRuntime:
    def __init__(self):
        self.article_chain = FakeArticleChain()
        self.manual_term_chain = FakeManualTermChain()
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

    def test_article_analysis_returns_title_subtitle_and_body_fields(self):
        body = "가상 임상 자료입니다. 안전성과 내약성을 평가하기 위한 초기 시험을 시작했습니다. " * 10
        response = self.client.post("/api/articles/analyze", json={
            "pasted_text": body,
            "title": "사용자가 입력한 기사 제목",
        })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["analysis"]["article_type"], "임상")
        self.assertEqual(payload["load_method"], "manual")
        self.assertTrue(payload["article_id"])
        self.assertEqual(payload["title"], "사용자가 입력한 기사 제목")
        self.assertEqual(payload["subtitle"], "")
        self.assertEqual(payload["body"], body.strip())
        self.assertNotIn("article", payload)
        self.assertEqual(len(payload["analysis"]["article_questions"]), 2)
        self.assertEqual(self.runtime.article_chain.article, body.strip())
        self.assertEqual(self.runtime.article_chain.payload["title"], "사용자가 입력한 기사 제목")
        self.assertEqual(self.runtime.article_chain.payload["subtitle"], "")

    def test_manual_term_classification_endpoint_returns_category_and_definition(self):
        response = self.client.post("/api/articles/classify-term", json={
            "term": "단백질 분해 유도",
            "article_context": "후보물질은 단백질 분해 유도 기술을 활용한다.",
            "article_type": "기술/플랫폼",
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["category"], "Mechanism")
        self.assertEqual(payload["article_context"], "후보물질은 단백질 분해 유도 기술을 활용한다.")
        self.assertTrue(payload["simple_definition"])

    def test_manual_term_classification_rejects_whitespace_only_term(self):
        response = self.client.post("/api/articles/classify-term", json={
            "term": "   ",
            "article_context": "기사 문맥입니다.",
            "article_type": "임상",
        })

        self.assertEqual(response.status_code, 422)

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
        self.assertEqual(payload["evidence_searches"], 1)
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
        self.assertIn('"evidence_searches":1', body)

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
        self.assertEqual(self.runtime.agent_graph.payload["article"], analyzed["body"])

        restored = self.client.get(f"/api/sessions/{session_id}", headers=headers)
        self.assertEqual(restored.status_code, 200)
        snapshot = restored.json()
        self.assertEqual(snapshot["article"]["article_id"], analyzed["article_id"])
        self.assertEqual(snapshot["article"]["analysis"]["article_questions"], analyzed["analysis"]["article_questions"])
        self.assertEqual(len(snapshot["turns"]), 1)
        self.assertEqual(snapshot["turns"][0]["question"], "임상 1상에서 무엇을 확인해?")
        self.assertEqual(snapshot["turns"][0]["evidence_searches"], 1)

        # A fresh Python process must restore the snapshot from the same SQLite file.
        script = """
import json, os, sys
from fastapi.testclient import TestClient
from backend.app.db import repository
from backend.app.main import app, runtime_dependency
repository.configure_database(sys.argv[1])
token = os.environ['PHARMAMATE_TEST_SESSION_TOKEN']
app.dependency_overrides[runtime_dependency] = lambda: object()
response = TestClient(app).get(
    f\"/api/sessions/{sys.argv[2]}\",
    headers={\"Authorization\": f\"Bearer {token}\"},
)
response.raise_for_status()
print(json.dumps(response.json(), ensure_ascii=False))
"""
        process_env = {**os.environ, "PHARMAMATE_TEST_SESSION_TOKEN": token}
        reopened = subprocess.run(
            [sys.executable, "-c", script, self.temp_dir.name, session_id],
            cwd=Path(__file__).resolve().parents[2],
            env=process_env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(reopened.returncode, 0, reopened.stderr)
        snapshot_after_restart = json.loads(reopened.stdout)
        self.assertEqual(snapshot_after_restart["article"]["article_id"], analyzed["article_id"])
        self.assertEqual(snapshot_after_restart["turns"][0]["question"], "임상 1상에서 무엇을 확인해?")
        self.assertEqual(snapshot_after_restart["turns"][0]["evidence_searches"], 1)

        second = self.client.post("/api/sessions").json()
        other = self.client.get(
            f"/api/sessions/{second['session_id']}",
            headers={"Authorization": f"Bearer {second['access_token']}"},
        ).json()
        self.assertIsNone(other["article"])
        self.assertEqual(other["turns"], [])

    def test_session_article_accepts_and_persists_user_added_other_term(self):
        session = self.client.post("/api/sessions").json()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        analyzed = self.client.post("/api/articles/analyze", json={
            "pasted_text": "가상 기사에서 임상 1상 계획을 설명합니다. " * 10,
        }).json()
        analyzed["analysis"]["key_terms"].append({
            "term": "사용자가 직접 선택한 개념",
            "category": "Other",
            "reason": "기사에서 직접 선택했습니다.",
            "simple_definition": "",
            "article_context": "가상 기사에서 사용자가 직접 고른 개념입니다.",
            "aliases": [],
        })

        response = self.client.put(
            f"/api/sessions/{session['session_id']}/article",
            headers=headers,
            json={"article": analyzed, "selected_term_key": "사용자가 직접 선택한 개념"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["article"]["analysis"]["key_terms"][-1]["category"],
            "Other",
        )

    def test_session_chat_history_is_isolated_by_selected_term(self):
        session = self.client.post("/api/sessions").json()
        session_id = session["session_id"]
        headers = {"Authorization": f"Bearer {session['access_token']}"}

        def ask(question, term):
            with self.client.stream(
                "POST", f"/api/sessions/{session_id}/chat/stream", headers=headers,
                json={"question": question, "term": term},
            ) as response:
                list(response.iter_text())
                self.assertEqual(response.status_code, 200)

        ask("ADC의 표적은 뭐야?", "ADC\n항체 약물 접합체")
        ask("임상 1상은 무엇을 봐?", "임상 1상\n사람 대상 초기 시험")
        ask("ADC는 세포 안에서 어떻게 작용해?", "ADC\n항체 약물 접합체")

        self.assertIn("ADC의 표적은 뭐야?", self.runtime.agent_graph.payload["history"])
        self.assertNotIn("임상 1상은 무엇을 봐?", self.runtime.agent_graph.payload["history"])

        snapshot = self.client.get(
            f"/api/sessions/{session_id}", headers=headers
        ).json()
        self.assertEqual(len(snapshot["turns"]), 3)

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
        self.assertCountEqual(records[0]["aliases"], [term["term"], *term["aliases"]])
        self.assertEqual(records[0]["note"], "안전성과 내약성을 우선 살핍니다.")

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

    def test_session_study_record_auto_drafts_note_from_linked_tutor_chat(self):
        session = self.client.post("/api/sessions").json()
        session_id = session["session_id"]
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        article = self.client.post("/api/articles/analyze", json={
            "pasted_text": "가상 기사에서 임상 1상 계획을 설명합니다. " * 10,
        }).json()
        self.client.put(f"/api/sessions/{session_id}/article", headers=headers,
                        json={"article": article, "selected_term_key": "임상 1상"})
        question = "임상 1상에서 무엇을 확인해?"
        with self.client.stream(
            "POST", f"/api/sessions/{session_id}/chat/stream", headers=headers,
            json={"question": question, "term": "임상 1상"},
        ) as response:
            list(response.iter_text())
        term = article["analysis"]["key_terms"][0]

        saved = self.client.post(
            f"/api/sessions/{session_id}/study-records", headers=headers,
            json={"term": term},
        )
        self.assertEqual(saved.status_code, 200)
        self.assertIn("메모 저장 완료", saved.json()["message"])
        records = self.client.get(
            f"/api/sessions/{session_id}/study-records", headers=headers
        ).json()
        note = records[0]["note"]
        self.assertIn("# 임상 1상 학습 메모\n\n## 한 줄 개념\n", note)
        self.assertIn("## 헷갈렸던 부분 Q&A", note)
        self.assertIn(f"**Q: {question}**", note)
        self.assertIn("A: 검증된 답변을 조각으로 전달합니다.", note)
        self.assertIn("## 기사에서 중요한 이유", note)
        self.assertIn("## 기억할 점", note)
        self.assertLess(note.index("## 기억할 점"), note.index("## 헷갈렸던 부분 Q&A"))

        # Older blank notes are backfilled from their saved Q&A when opened.
        with repository.connect_db() as conn:
            conn.execute("UPDATE session_learning_records SET note='' WHERE session_id=?", (session_id,))
        refreshed = self.client.get(
            f"/api/sessions/{session_id}/study-records", headers=headers
        ).json()
        self.assertIn(question, refreshed[0]["note"])
        with repository.connect_db() as conn:
            stored_note = conn.execute(
                "SELECT note FROM session_learning_records WHERE session_id=?", (session_id,)
            ).fetchone()["note"]
        self.assertTrue(stored_note)

    def test_saving_updated_memo_keeps_previous_and_adds_new_chat_qa(self):
        session = self.client.post("/api/sessions").json()
        session_id = session["session_id"]
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        article = self.client.post("/api/articles/analyze", json={
            "pasted_text": "가상 기사에서 임상 1상 계획을 설명합니다. " * 10,
        }).json()
        self.client.put(
            f"/api/sessions/{session_id}/article", headers=headers,
            json={"article": article, "selected_term_key": "임상 1상"},
        )
        term = article["analysis"]["key_terms"][0]
        first_question = "임상 1상에서는 무엇을 평가하나요?"
        second_question = "임상 1상 결과는 다음 단계에 어떻게 이어지나요?"

        for question in (first_question,):
            with self.client.stream(
                "POST", f"/api/sessions/{session_id}/chat/stream", headers=headers,
                json={"question": question, "term": "임상 1상"},
            ) as response:
                list(response.iter_text())

        initial_note = (
            "한 줄 개념\n사람 대상 초기 평가 단계입니다.\n\n"
            "헷갈렸던 부분 Q&A\n"
            f"Q. {first_question}\nA. 검증된 답변을 조각으로 전달합니다.\n\n"
            "기사에서 중요한 이유\n가상 후보물질의 초기 시험입니다.\n\n"
            "기억할 점\n안전성을 우선 확인합니다."
        )
        self.client.post(
            f"/api/sessions/{session_id}/study-records", headers=headers,
            json={"term": term, "note": initial_note},
        )

        with self.client.stream(
            "POST", f"/api/sessions/{session_id}/chat/stream", headers=headers,
            json={"question": second_question, "term": "임상 1상"},
        ) as response:
            list(response.iter_text())

        updated_note = initial_note.replace(
            "기사에서 중요한 이유",
            f"Q. {second_question}\nA. 검증된 답변을 조각으로 전달합니다.\n\n기사에서 중요한 이유",
        )
        saved = self.client.post(
            f"/api/sessions/{session_id}/study-records", headers=headers,
            json={"term": term, "note": updated_note},
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["new_questions"], 1)
        record = self.client.get(
            f"/api/sessions/{session_id}/study-records", headers=headers,
        ).json()[0]
        self.assertIn(first_question, record["note"])
        self.assertIn(second_question, record["note"])
        self.assertEqual(record["qa_count"], 2)

    def test_session_study_record_without_questions_uses_term_summary_format(self):
        session = self.client.post("/api/sessions").json()
        session_id = session["session_id"]
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        term = {
            "term": "임상 1상", "category": "Clinical Trial",
            "reason": "개발 단계 이해", "simple_definition": "사람 대상 초기 평가 단계입니다.",
            "article_context": "후보물질의 안전성을 살핍니다.", "aliases": ["Phase 1"],
        }

        saved = self.client.post(
            f"/api/sessions/{session_id}/study-records", headers=headers,
            json={"term": term},
        )
        self.assertEqual(saved.status_code, 200)
        record = self.client.get(
            f"/api/sessions/{session_id}/study-records", headers=headers
        ).json()[0]
        self.assertIn("# 임상 1상 학습 메모\n\n## 한 줄 개념\n사람 대상 초기 평가 단계입니다.", record["note"])
        self.assertIn("헷갈렸던 부분 Q&A", record["note"])
        self.assertIn("아직 이 용어에 연결된 질문과 답변이 없습니다.", record["note"])
        self.assertIn("## 기사에서 중요한 이유\n후보물질의 안전성을 살핍니다.", record["note"])
        self.assertIn("## 기억할 점\n- 개발 단계 이해", record["note"])
        self.assertLess(record["note"].index("## 기억할 점"), record["note"].index("## 헷갈렸던 부분 Q&A"))
        self.assertEqual(record["qa_count"], 0)

    def test_read_articles_dedupe_copies_and_group_issues_conservatively(self):
        session = self.client.post("/api/sessions").json()
        session_id = session["session_id"]
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        endpoint = f"/api/sessions/{session_id}/articles/mark-read"

        def article(article_id, title, url, body, key_issue, entities):
            return {
                "article_id": article_id,
                "article": body,
                "url": url,
                "title": title,
                "load_method": "manual",
                "analysis": {
                    "article_type": "임상",
                    "one_line_summary": "합성 실험 기사입니다.",
                    "key_issue": key_issue,
                    "key_entities": entities,
                    "key_terms": [],
                    "confusing_points": [],
                },
            }

        first = self.client.post(endpoint, headers=headers, json={"article": article(
            "a1", "HB-101 임상 2상 주요 결과", "https://news.example.org/story/1?utm_source=feed",
            "synthetic clinical article one", "HB-101 임상 2상 결과 발표", ["한빛바이오", "HB-101"],
        )}).json()
        self.assertTrue(first["saved"])
        self.assertEqual(first["match_type"], "new")
        self.assertEqual(first["message"], "기사와 산업 이슈를 저장했습니다.")

        same_url = self.client.post(endpoint, headers=headers, json={"article": article(
            "a2", "새 제목", "https://www.news.example.org/story/1?utm_source=mail",
            "different body", "HB-101 임상 2상 결과 발표", ["한빛바이오", "HB-101"],
        )}).json()
        self.assertTrue(same_url["duplicate"])
        self.assertEqual(same_url["duplicate_by"], "url")

        same_body = self.client.post(endpoint, headers=headers, json={"article": article(
            "a3", "다른 매체 제목", "https://mirror.example.org/copy",
            "  SYNTHETIC   CLINICAL article one  ", "HB-101 임상 2상 결과 발표", ["한빛바이오", "HB-101"],
        )}).json()
        self.assertTrue(same_body["duplicate"])
        self.assertEqual(same_body["duplicate_by"], "content")

        same_issue = self.client.post(endpoint, headers=headers, json={"article": article(
            "a4", "HB-101 2상 임상 결과", "https://news.example.org/story/2",
            "synthetic follow-up article", "HB-101 2상 임상 결과 공개", ["한빛바이오", "HB-101"],
        )}).json()
        self.assertTrue(same_issue["saved"])
        self.assertEqual(same_issue["match_type"], "automatic")
        self.assertEqual(same_issue["message"], "기사와 산업 이슈를 저장했습니다.")
        self.assertEqual(same_issue["issue_id"], first["issue_id"])

        other_phase = self.client.post(endpoint, headers=headers, json={"article": article(
            "a5", "HB-101 임상 3상", "https://news.example.org/story/3",
            "synthetic phase three article", "HB-101 임상 3상 결과 발표", ["한빛바이오", "HB-101"],
        )}).json()
        self.assertEqual(other_phase["match_type"], "new")
        self.assertNotEqual(other_phase["issue_id"], first["issue_id"])

        manually_linked = self.client.post(endpoint, headers=headers, json={"article": article(
            "a6", "별도 기사", "https://news.example.org/story/4",
            "synthetic manually grouped article", "새로운 회사 발표", ["한빛바이오", "HB-101"],
        ), "issue_id": first["issue_id"]}).json()
        self.assertEqual(manually_linked["match_type"], "manual")
        self.assertEqual(manually_linked["issue_id"], first["issue_id"])

        issue_list = self.client.get(
            f"/api/sessions/{session_id}/industry-issues", headers=headers
        ).json()
        grouped = next(item for item in issue_list if item["issue_id"] == first["issue_id"])
        self.assertEqual(grouped["article_count"], 3)
        self.assertEqual(len(grouped["articles"]), 3)
        article_list = self.client.get(f"/api/sessions/{session_id}/articles", headers=headers).json()
        self.assertEqual(len(article_list), 4)
        other_session = self.client.post("/api/sessions").json()
        other_issues = self.client.get(
            f"/api/sessions/{other_session['session_id']}/industry-issues",
            headers={"Authorization": f"Bearer {other_session['access_token']}"},
        ).json()
        self.assertEqual(other_issues, [])
        session_articles = [
            item for item in repository.get_memory_documents(session_id)
            if item["source_type"] == "session_article"
        ]
        self.assertEqual(len(session_articles), 4)
        self.assertEqual(repository.get_memory_documents(other_session["session_id"]), [])

    def test_additive_session_migration_keeps_legacy_article_records(self):
        state = {
            "article_id": "legacy-article-01",
            "title": "기존 노트북에서 저장한 기사",
            "url": "https://legacy.example.org/article",
            "analysis": {
                "article_type": "산업", "one_line_summary": "기존 기록입니다.",
                "key_issue": "기존 이슈", "key_entities": [], "key_terms": [],
            },
        }
        self.assertTrue(repository.save_read_article(state))
        repository.configure_database(self.temp_dir.name)
        rows = repository.get_recent_articles()
        self.assertEqual([row["article_id"] for row in rows], ["legacy-article-01"])


if __name__ == "__main__":
    unittest.main()
