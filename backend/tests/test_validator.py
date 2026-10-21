from __future__ import annotations

import unittest

from backend.app.agents.validator import (
    AnswerValidation,
    unsupported_numeric_markers,
    validate_answer,
    validation_next_step,
)


class FakeJudge:
    def __init__(self, result: AnswerValidation):
        self.result = result

    def invoke(self, _payload):
        return self.result


class ValidatorTests(unittest.TestCase):
    def test_unsupported_numbers_and_dates_override_judge_pass(self):
        answer = "임상 2상에서 성공률 87%였고 2025년 3월에 승인됐습니다."
        evidence = "가상 자료는 임상 1상 안전성 평가를 설명합니다."
        result = validate_answer(
            FakeJudge(AnswerValidation(status="pass")),
            question="임상 결과는?", answer=answer, evidence=evidence,
        )
        self.assertEqual(result["status"], "revise")
        self.assertTrue(any("87%" in claim for claim in result["unsupported_claims"]))
        self.assertTrue(any("2025년 3월" in claim for claim in result["unsupported_claims"]))

    def test_supported_numeric_markers_do_not_trigger_override(self):
        evidence = "2024년 4월 임상 1상에서 42명을 대상으로 안전성을 평가했다."
        answer = "2024년 4월 임상 1상에서 42명을 대상으로 안전성을 평가했습니다."
        result = validate_answer(
            FakeJudge(AnswerValidation(status="pass")),
            question="무엇을 평가했나요?", answer=answer, evidence=evidence,
        )
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["unsupported_claims"], [])

    def test_planned_safety_assessment_is_not_treated_as_a_result(self):
        evidence = "시험은 안전성과 내약성을 평가하기 위해 시작되었고 실제 결과는 아직 보고되지 않았다."
        answer = "시험에서 안전성과 내약성이 입증되었고 중대한 부작용은 없었습니다."
        result = validate_answer(
            FakeJudge(AnswerValidation(status="pass")),
            question="안전성 결과가 어땠나요?", answer=answer, evidence=evidence,
        )
        self.assertEqual(result["status"], "revise")
        self.assertTrue(any("실제 임상 결과" in claim for claim in result["unsupported_claims"]))

    def test_careful_statement_of_unreported_results_is_not_flagged(self):
        evidence = "시험은 안전성과 내약성을 평가하기 위해 시작되었고 실제 결과는 아직 보고되지 않았다."
        answer = "이 자료는 평가 목적만 설명하며 실제 결과는 아직 보고되지 않았습니다."
        result = validate_answer(
            FakeJudge(AnswerValidation(status="pass")),
            question="안전성 결과가 어땠나요?", answer=answer, evidence=evidence,
        )
        self.assertEqual(result["status"], "pass")

    def test_one_rewrite_is_the_maximum(self):
        self.assertEqual(validation_next_step("revise", 1), "answer")
        self.assertEqual(validation_next_step("insufficient_evidence", 1), "answer")
        self.assertEqual(validation_next_step("revise", 2), "fallback")
        self.assertEqual(validation_next_step("unavailable", 1), "fallback")
        self.assertEqual(validation_next_step("pass", 2), "end")

    def test_confirmed_trial_start_is_not_confused_with_confirmed_outcome(self):
        evidence = "초기 임상시험을 시작했다. 유효성 결과는 보고되지 않았다."
        answer = "확인된 것은 초기 임상시험이 시작됐다는 점이며, 유효성 결과는 보고되지 않았습니다."
        result = validate_answer(
            FakeJudge(AnswerValidation(status="pass")),
            question="무엇이 확인됐나요?", answer=answer, evidence=evidence,
        )
        self.assertEqual(result["status"], "pass")

    def test_general_background_without_numeric_claims_is_not_blocked_by_marker_guard(self):
        answer = "ADC는 항체와 약물을 연결해 표적에 전달하는 방식입니다."
        self.assertEqual(unsupported_numeric_markers(answer, ""), [])

    def test_stable_general_definition_without_sources_can_pass(self):
        answer = "단클론 항체는 특정 표적에 결합하는 단백질 의약품입니다. 화학 합성 의약품은 화학 반응으로 만든 분자 약물입니다."
        result = validate_answer(
            FakeJudge(AnswerValidation(status="insufficient_evidence")),
            question="단클론 항체와 화학 합성 의약품은 어떻게 달라?",
            answer=answer, evidence="",
        )
        self.assertEqual(result["status"], "pass")

    def test_labeled_mechanism_background_can_pass_when_article_omits_mechanism(self):
        answer = (
            "일반 배경지식: ADC는 항체가 표적 항원에 붙은 뒤 세포 안으로 들어가고, "
            "연결된 약물이 방출되어 세포에 작용하는 방식입니다."
        )
        result = validate_answer(
            FakeJudge(AnswerValidation(status="insufficient_evidence")),
            question="ADC의 작동 기전은 뭐야?",
            answer=answer,
            evidence="기사는 특정 ADC 후보의 연구 계획을 소개하지만 세부 작동 기전은 설명하지 않습니다.",
        )
        self.assertEqual(result["status"], "pass")

    def test_labeled_analogy_can_pass_when_article_does_not_explain_the_term(self):
        answer = (
            "일반 배경지식 비유: 이 용어는 열쇠와 자물쇠처럼 필요한 대상에 맞춰 작동하는 것으로 생각할 수 있습니다. "
            "실제 생물학적 과정은 비유보다 복잡합니다."
        )
        result = validate_answer(
            FakeJudge(AnswerValidation(status="insufficient_evidence")),
            question="이 용어를 일상적인 예로 쉽게 비유해줘.",
            answer=answer,
            evidence="기사는 이 용어를 언급하지만 개념 설명은 제공하지 않습니다.",
        )
        self.assertEqual(result["status"], "pass")

    def test_analogy_request_still_rejects_unsupported_numeric_claims(self):
        result = validate_answer(
            FakeJudge(AnswerValidation(status="pass")),
            question="이 용어를 일상적인 예로 쉽게 비유해줘.",
            answer="일반 배경지식 비유: 이 치료는 성공률 87%인 자물쇠 열쇠와 같습니다.",
            evidence="",
        )
        self.assertEqual(result["status"], "revise")

    def test_general_question_does_not_allow_numeric_claim_without_evidence(self):
        result = validate_answer(
            FakeJudge(AnswerValidation(status="pass")),
            question="이 약의 효과는 무엇인가요?",
            answer="임상 성공률은 87%입니다.", evidence="",
        )
        self.assertEqual(result["status"], "revise")

    def test_partial_answer_with_unsupported_number_is_not_reused(self):
        result = validate_answer(
            FakeJudge(AnswerValidation(
                status="insufficient_evidence",
                supported_answer="표준 치료의 성공률은 87%입니다.",
            )),
            question="표준 치료 결과는?", answer="결과는 확인되지 않습니다.", evidence="표준 치료를 계획했다.",
        )
        self.assertEqual(result["supported_answer"], "")


if __name__ == "__main__":
    unittest.main()
