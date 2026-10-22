from __future__ import annotations

import unittest
import threading
import time

from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable, RunnableLambda

from backend.app.agents.graph import RouteDecision, build_agent_graph
from backend.app.agents.validator import AnswerValidation
from backend.app.services.recommendations import LearningTurnResponse, fallback_recommendations


class FakeModel(Runnable):
    def __init__(self, answers: list[str], route: str = "article"):
        self.answers = list(answers)
        self.route = route

    def invoke(self, input, config=None, **kwargs):
        answer = self.answers.pop(0) if self.answers else "초안 답변"
        return AIMessage(content=answer)

    def with_structured_output(self, schema):
        def output(_prompt):
            if schema is RouteDecision:
                return RouteDecision(
                    route=self.route, memory_query="ADC", search_query="latest ADC results",
                    reason="fixture", related_to_selected=False
                )
            if schema is AnswerValidation:
                return AnswerValidation(status="pass")
            if schema is LearningTurnResponse:
                answer = self.answers.pop(0) if self.answers else "초안 답변"
                return LearningTurnResponse(answer=answer, recommendations=fallback_recommendations("ADC"))
            raise AssertionError(f"unexpected schema: {schema}")
        return RunnableLambda(output)


def build_graph(answers: list[str], answer_validator=None, *, route="article", search_client=None, search_study_memory=None):
    return build_agent_graph(
        model=FakeModel(answers, route=route),
        search_client=search_client,
        search_study_memory=search_study_memory or (lambda *_args, **_kwargs: []),
        get_term_examples=lambda *_args, **_kwargs: [],
        get_saved_note=lambda *_args, **_kwargs: "",
        answer_validator=answer_validator or RunnableLambda(lambda _payload: AnswerValidation(status="pass")),
    )


class AgentValidationFlowTests(unittest.TestCase):
    def test_explicit_selected_term_mention_survives_router_false_label(self):
        graph = build_graph(["PSMA는 세포 표면 표적입니다."])
        result = graph.invoke({
            "question": "PSMA가 전립선암 세포에서 어떤 역할을 하나요?",
            "term": "전립선특이막항원(PSMA)\n전립선 세포 표면 단백질",
            "article": "",
        })
        self.assertTrue(result["related_to_selected"])

    def test_revises_once_then_accepts_supported_answer(self):
        graph = build_graph([
            "임상 성공률은 87%입니다.",
            "제공된 기사에는 임상 성공률이 포함되어 있지 않습니다.",
        ])
        result = graph.invoke({
            "question": "임상 성공률은?",
            "article": "가상 자료: 초기 임상시험에서 안전성을 평가한다. 유효성 결과는 없다.",
        })
        self.assertEqual(result["answer_attempts"], 2)
        self.assertEqual(result["validation_retries"], 1)
        self.assertEqual(result["answer_revisions"], 1)
        self.assertEqual(result["validation_status"], "pass")
        self.assertNotIn("87%", result["answer"])
        self.assertEqual(len(result["recommendations"]), 3)

    def test_validator_error_returns_safe_message_without_retry_loop(self):
        def fail(_payload):
            raise RuntimeError("synthetic validator outage")

        graph = build_graph(["일반적인 개념 답변입니다."], RunnableLambda(fail))
        result = graph.invoke({"question": "이 개념은 무엇인가?", "article": "자료"})
        self.assertEqual(result["answer_attempts"], 1)
        self.assertEqual(result["validation_status"], "unavailable")
        self.assertIn("검증을 완료하지 못해", result["answer"])
        self.assertEqual(len(result["recommendations"]), 3)
        self.assertIn("공식 자료", result["recommendations"][1]["question"])

    def test_unresolved_unsupported_answer_falls_back_after_one_rewrite(self):
        graph = build_graph(["임상 성공률은 87%입니다.", "임상 성공률은 87%입니다."])
        result = graph.invoke({
            "question": "임상 성공률은?",
            "term": "임상 성공률",
            "article": "가상 자료: 유효성 결과는 포함되어 있지 않다.",
        })
        self.assertEqual(result["answer_attempts"], 2)
        self.assertEqual(result["validation_retries"], 1)
        self.assertEqual(result["answer_revisions"], 1)
        self.assertEqual(result["validation_status"], "insufficient_evidence")
        self.assertNotIn("87%", result["answer"])
        self.assertIn("단정하지 않겠습니다", result["answer"])
        self.assertEqual(len(result["recommendations"]), 3)
        self.assertEqual(
            [item["category"] for item in result["recommendations"]],
            ["원리 심화", "다른 개념과 연결", "한계·응용 탐구"],
        )
        self.assertIn("임상 성공률", result["recommendations"][0]["question"])
        self.assertIn("공식 자료", result["recommendations"][1]["question"])
        self.assertIn("확인된 내용", result["recommendations"][2]["question"])

    def test_insufficient_answer_retries_only_after_distinct_official_sources(self):
        class Search:
            def __init__(self):
                self.calls = 0

            def search(self, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    return {"results": [{
                        "title": "공식 시험 등록 자료",
                        "url": "https://clinicaltrials.gov/study/NCT00000001",
                        "content": "시험 등록 자료에는 대상 환자군, 투여 계획, 평가 항목 등 확인에 필요한 정보를 기록합니다. " * 2,
                    }]}
                return {"results": [{
                    "title": "공식 규제기관 자료",
                    "url": "https://www.fda.gov/drugs/example-review",
                    "content": "규제기관 검토 자료에는 해당 치료의 근거와 검토 범위가 설명되며 원문에서 세부 사항을 확인할 수 있습니다. " * 2,
                }]}

        validations = [
            AnswerValidation(status="insufficient_evidence", missing_evidence_query="trial protocol details"),
            AnswerValidation(status="insufficient_evidence", missing_evidence_query="official review scope"),
            AnswerValidation(status="pass"),
        ]
        search = Search()
        graph = build_graph(
            ["초안 답변", "첫 번째 새 근거를 반영한 답변", "두 번째 새 근거까지 반영한 답변"],
            RunnableLambda(lambda _payload: validations.pop(0)),
            search_client=search,
        )

        result = graph.invoke({
            "question": "현재 자료에서 확인할 수 있는 범위는 무엇인가요?",
            "article": "가상 기사에는 질문의 핵심 세부사항이 나오지 않습니다.",
        })

        self.assertEqual(search.calls, 2)
        self.assertEqual(result["answer_attempts"], 3)
        self.assertEqual(result["validation_retries"], 2)
        self.assertEqual(result["answer_revisions"], 0)
        self.assertEqual(result["evidence_searches"], 2)
        self.assertEqual(result["validation_status"], "pass")
        self.assertIn("NCT00000001", result["web"])
        self.assertIn("example-review", result["web"])
        self.assertEqual(len(result["sources"]), 2)

    def test_insufficient_answer_stops_when_search_repeats_the_same_source(self):
        class Search:
            def __init__(self):
                self.calls = 0

            def search(self, **_kwargs):
                self.calls += 1
                return {"results": [{
                    "title": "공식 시험 등록 자료",
                    "url": "https://clinicaltrials.gov/study/NCT00000002",
                    "content": "공식 시험 등록 자료에서 시험 목적과 대상군, 계획된 평가 항목을 확인할 수 있습니다. " * 2,
                }]}

        search = Search()
        graph = build_graph(
            ["시험 구성에 관한 초안입니다."],
            RunnableLambda(lambda _payload: AnswerValidation(
                status="insufficient_evidence", missing_evidence_query="trial treatment details"
            )),
            route="web",
            search_client=search,
        )

        result = graph.invoke({
            "question": "현재 자료에서 확인할 수 있는 범위는 무엇인가요?",
            "article": "가상 기사에는 질문의 핵심 세부사항이 나오지 않습니다.",
        })

        self.assertEqual(search.calls, 2)
        self.assertEqual(result["answer_attempts"], 1)
        self.assertEqual(result["evidence_searches"], 1)
        self.assertEqual(result["validation_status"], "insufficient_evidence")
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(len(result["recommendations"]), 3)

    def test_memory_web_sources_run_concurrently_and_both_reach_answer(self):
        rendezvous = threading.Barrier(2, timeout=2)

        def search_memory(*_args, **_kwargs):
            rendezvous.wait()
            return [{
                "record_id": "session_note:adc", "source_type": "session_note",
                "title": "내 ADC 학습 메모", "content": "합성 메모: ADC는 표적 전달 기술입니다.",
            }]

        class FakeSearchClient:
            def search(self, **_kwargs):
                rendezvous.wait()
                return {"results": [{
                    "title": "가상 최신 ADC 시험", "url": "https://clinicaltrials.gov/study/NCT00000000",
                    "content": "합성 fixture: 최신 시험은 진행 중입니다.",
                }]}

        graph = build_graph(
            ["기록과 검색 자료를 함께 설명합니다."],
            route="memory_web",
            search_client=FakeSearchClient(),
            search_study_memory=search_memory,
        )
        started = time.perf_counter()
        result = graph.invoke({"question": "이전 ADC 기록과 최신 결과를 비교해줘."})
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 1.5)
        self.assertIn("합성 메모", result["memory"])
        self.assertIn("가상 최신 ADC 시험", result["web"])
        self.assertEqual(len(result["sources"]), 2)

    def test_care_question_gets_attributed_reference_even_without_search_client(self):
        graph = build_graph(["일반적으로 SoC는 표준 치료를 뜻합니다. 이 시험의 구체적 구성은 기사만으로 확인할 수 없습니다."])
        result = graph.invoke({"question": "BSC·SoC의 구체적인 구성은 무엇인가요?", "article": "시험은 BSC·SoC를 사용한다."})
        self.assertEqual(result["route"], "web")
        self.assertIn("NCI Dictionary", result["web"])
        self.assertEqual(len(result["sources"]), 2)

    def test_general_care_definition_uses_curated_reference_without_paid_search(self):
        class Search:
            def search(self, **_kwargs):
                raise AssertionError("일반 개념에 외부 검색을 호출하면 안 됩니다")

        graph = build_graph(["SoC는 널리 쓰이는 표준 치료입니다."], search_client=Search())
        result = graph.invoke({"question": "SoC는 무슨 뜻이야?", "article": ""})
        self.assertEqual(result["route"], "web")
        self.assertEqual(result["web_searches"], 0)
        self.assertEqual(len(result["sources"]), 2)

    def test_insufficient_answer_fetches_new_evidence_before_second_answer(self):
        class Search:
            def __init__(self):
                self.queries = []

            def search(self, **kwargs):
                self.queries.append(kwargs["query"])
                return {"results": [{
                    "title": "Trial record",
                    "url": "https://clinicaltrials.gov/study/NCT00000000",
                    "content": "공식 시험 등록 자료에는 시험 대상과 목적, 계획된 평가 항목 등 세부 설계 정보가 기록되어 있습니다.",
                }]}

        search = Search()
        calls = 0

        def judge(_payload):
            nonlocal calls
            calls += 1
            if calls == 1:
                return AnswerValidation(status="insufficient_evidence", missing_evidence_query="trial protocol BSC SoC")
            return AnswerValidation(status="pass")

        graph = build_graph(["초안", "검색 근거를 반영한 답변"], RunnableLambda(judge), search_client=search)
        result = graph.invoke({"question": "현재 자료로 확인할 수 있는 범위는?", "article": "시험을 계획했다."})
        self.assertEqual(search.queries, ["trial protocol BSC SoC"])
        self.assertEqual(result["answer_attempts"], 2)
        self.assertEqual(result["evidence_searches"], 1)
        self.assertEqual(result["answer_revisions"], 0)
        self.assertEqual(result["answer"], "검색 근거를 반영한 답변")

    def test_supported_partial_answer_survives_failed_validation(self):
        judge = RunnableLambda(lambda _payload: AnswerValidation(
            status="insufficient_evidence",
            supported_answer="일반적으로 SoC는 해당 질환에서 널리 쓰이는 치료입니다. 이 시험의 구체적 약물 조합은 확인되지 않았습니다.",
        ))
        graph = build_graph(["시험 약물 조합을 단정한 답변"], judge)
        result = graph.invoke({"question": "이 시험의 SoC 구성은?", "article": "SoC를 사용한다."})
        self.assertEqual(result["answer_attempts"], 1)
        self.assertIn("널리 쓰이는 치료", result["answer"])
        self.assertIn("확인되지 않았습니다", result["answer"])


if __name__ == "__main__":
    unittest.main()
