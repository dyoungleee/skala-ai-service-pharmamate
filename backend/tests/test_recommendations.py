from __future__ import annotations

import unittest

from backend.app.services.recommendations import (
    LEARNING_CATEGORIES,
    fallback_recommendations,
    recommend_learning_questions,
    render_recommendations,
)


def valid_result(_payload):
    return {
        "recommendations": [
            {"category": "한계·응용 탐구", "question": "임상 적용에서 어떤 한계를 살펴봐야 해?", "learning_goal": "적용 범위와 한계를 파악합니다."},
            {"category": "원리 심화", "question": "표적 항원에 결합한 뒤 약물은 어떻게 방출돼?", "learning_goal": "전달 원리를 단계별로 이해합니다."},
            {"category": "다른 개념과 연결", "question": "ADC와 항체 치료제는 어떤 관계야?", "learning_goal": "관련 치료 방식의 공통점과 차이를 비교합니다."},
        ]
    }


class RecommendationTests(unittest.TestCase):
    def test_returns_one_grounded_question_for_each_learning_goal(self):
        result = recommend_learning_questions(
            valid_result,
            term="ADC",
            question="ADC에서 항체는 무슨 역할을 해?",
            answer="항체가 표적 항원에 결합해 payload 전달을 돕습니다.",
            history=[{"question": "ADC가 뭐야?", "answer": "항체와 약물을 연결한 치료 방식입니다."}],
        )
        self.assertEqual([item["category"] for item in result], list(LEARNING_CATEGORIES))
        self.assertEqual(len({item["question"] for item in result}), 3)

    def test_generator_receives_recent_context_and_saved_note(self):
        captured = {}

        def generator(payload):
            captured.update(payload)
            return valid_result(payload)

        recommend_learning_questions(
            generator,
            term="ADC",
            question="왜 항체를 사용해?",
            answer="표적에 약물을 전달합니다.",
            history=[{"question": "payload가 뭐야?", "answer": "연결된 세포독성 약물입니다."}],
            saved_note="정상 세포 독성도 주의한다.",
        )
        self.assertEqual(captured["term"], "ADC")
        self.assertEqual(captured["history"][0]["question"], "payload가 뭐야?")
        self.assertIn("독성", captured["saved_note"])

    def test_duplicate_or_previously_asked_question_falls_back(self):
        result = recommend_learning_questions(
            lambda _payload: {
                "recommendations": [
                    {"category": category, "question": "ADC가 뭐야?", "learning_goal": "개념을 배웁니다."}
                    for category in LEARNING_CATEGORIES
                ]
            },
            term="ADC",
            question="ADC가 뭐야?",
        )
        self.assertEqual(result, fallback_recommendations("ADC"))
        self.assertEqual(len({item["category"] for item in result}), 3)

    def test_model_failure_keeps_three_distinct_learning_goals(self):
        def fail(_payload):
            raise TimeoutError("offline")

        result = recommend_learning_questions(fail, term="ADC")
        self.assertEqual(result, fallback_recommendations("ADC"))
        self.assertEqual(len({item["question"] for item in result}), 3)

    def test_markdown_exposes_category_question_and_goal(self):
        text = render_recommendations(fallback_recommendations("ADC"))
        self.assertIn("원리 심화", text)
        self.assertIn("핵심 작동 원리", text)
        self.assertIn("ADC의 핵심 작동 원리", text)


if __name__ == "__main__":
    unittest.main()
