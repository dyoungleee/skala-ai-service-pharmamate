from __future__ import annotations

import unittest

from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable, RunnableLambda

from backend.app.agents.graph import RouteDecision, build_agent_graph
from backend.app.agents.validator import AnswerValidation


class FakeModel(Runnable):
    def __init__(self, answers: list[str]):
        self.answers = list(answers)

    def invoke(self, input, config=None, **kwargs):
        answer = self.answers.pop(0) if self.answers else "초안 답변"
        return AIMessage(content=answer)

    def with_structured_output(self, schema):
        def output(_prompt):
            if schema is RouteDecision:
                return RouteDecision(
                    route="article", memory_query="", search_query="", reason="fixture", related_to_selected=False
                )
            if schema is AnswerValidation:
                return AnswerValidation(status="pass")
            raise AssertionError(f"unexpected schema: {schema}")
        return RunnableLambda(output)


def build_graph(answers: list[str], answer_validator=None):
    return build_agent_graph(
        model=FakeModel(answers),
        search_study_memory=lambda *_args, **_kwargs: [],
        get_term_examples=lambda *_args, **_kwargs: [],
        get_saved_note=lambda *_args, **_kwargs: "",
        answer_validator=answer_validator or RunnableLambda(lambda _payload: AnswerValidation(status="pass")),
    )


class AgentValidationFlowTests(unittest.TestCase):
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
        self.assertEqual(result["validation_status"], "pass")
        self.assertNotIn("87%", result["answer"])

    def test_validator_error_returns_safe_message_without_retry_loop(self):
        def fail(_payload):
            raise RuntimeError("synthetic validator outage")

        graph = build_graph(["일반적인 개념 답변입니다."], RunnableLambda(fail))
        result = graph.invoke({"question": "이 개념은 무엇인가?", "article": "자료"})
        self.assertEqual(result["answer_attempts"], 1)
        self.assertEqual(result["validation_status"], "unavailable")
        self.assertIn("검증을 완료하지 못해", result["answer"])

    def test_unresolved_unsupported_answer_falls_back_after_one_rewrite(self):
        graph = build_graph(["임상 성공률은 87%입니다.", "임상 성공률은 87%입니다."])
        result = graph.invoke({
            "question": "임상 성공률은?",
            "article": "가상 자료: 유효성 결과는 포함되어 있지 않다.",
        })
        self.assertEqual(result["answer_attempts"], 2)
        self.assertEqual(result["validation_retries"], 1)
        self.assertEqual(result["validation_status"], "insufficient_evidence")
        self.assertNotIn("87%", result["answer"])
        self.assertIn("단정하지 않겠습니다", result["answer"])


if __name__ == "__main__":
    unittest.main()
