from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend.app.services.recommendations import fallback_recommendations


ROOT = Path(__file__).resolve().parents[2]


class FakeGradio:
    @staticmethod
    def update(**kwargs):
        return kwargs


class FakeGraph:
    @staticmethod
    def invoke(_payload):
        return {
            "answer": "ADC는 항체가 payload를 표적 세포로 전달하도록 돕는 방식입니다.",
            "recommendations": fallback_recommendations("ADC"),
            "sources": [],
            "route": "article",
            "related_to_selected": False,
        }


class NotebookRecommendationFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        notebook = json.loads((ROOT / "PharmaMate_2_0.ipynb").read_text(encoding="utf-8"))
        namespace = {"gr": FakeGradio(), "agent_graph": FakeGraph()}
        exec("".join(notebook["cells"][18]["source"]), namespace)
        cls.namespace = namespace

    def test_answer_refreshes_three_questions_and_button_uses_latest_state(self):
        state = self.namespace["new_app_state"]()
        result = self.namespace["ui_ask"](
            "ADC에서 항체는 무슨 역할을 해?", [], state, True, "자동 판단"
        )
        self.assertEqual(len(result), 7)
        self.assertEqual(len(result[2]["recommendations"]), 3)
        self.assertIn("원리 심화", result[3])
        self.assertEqual(result[4], {"value": "1 · 원리 심화"})
        self.assertEqual(
            self.namespace["ui_pick_suggested_question"](result[2], 0),
            result[2]["recommendations"][0]["question"],
        )


if __name__ == "__main__":
    unittest.main()
