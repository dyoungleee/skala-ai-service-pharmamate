from __future__ import annotations

import unittest

from backend.app.schemas.article import (
    ArticleAnalysis,
    ManualTermClassification,
    ManualTermClassificationModelOutput,
    PharmaTerm,
)
from backend.app.services.article_analysis import (
    ARTICLE_ANALYSIS_PROMPT,
    MANUAL_TERM_CLASSIFICATION_PROMPT,
    analyze_article,
    classify_manual_term,
    validate_article_questions,
)


class ArticleAnalysisPromptTests(unittest.TestCase):
    def test_prompt_excludes_related_image_captions_but_keeps_real_body_text(self):
        system_prompt = ARTICLE_ANALYSIS_PROMPT.messages[0].prompt.template

        self.assertIn("사진·이미지의 캡션과 이미지 설명문", system_prompt)
        self.assertIn("기사 주제와 관련되어도", system_prompt)
        self.assertIn("실제 기사 본문에 쓰인 문장과 문단", system_prompt)

    def test_prompt_excludes_institution_names_and_acronyms_from_key_terms(self):
        system_prompt = ARTICLE_ANALYSIS_PROMPT.messages[0].prompt.template

        self.assertIn("기관명과 약칭·현지어 정식 명칭은 학습 용어에서 제외", system_prompt)
        self.assertIn("0개도 허용", system_prompt)
        self.assertIn("임상 단계, 허가 절차", system_prompt)

    def test_prompt_prioritizes_unfamiliar_specialized_terms_and_excludes_common_symptoms(self):
        system_prompt = ARTICLE_ANALYSIS_PROMPT.messages[0].prompt.template

        self.assertIn("일상에서 흔히 쓰고 일반 독자가 바로 이해할 수 있는 표현은 추출하지 않습니다", system_prompt)
        self.assertIn("가슴 쓰림·속쓰림", system_prompt)
        self.assertIn("재사용 가치가 있는 개념", system_prompt)

    def test_prompt_uses_title_subtitle_and_body_as_separate_inputs(self):
        system_prompt = ARTICLE_ANALYSIS_PROMPT.messages[0].prompt.template
        human_prompt = ARTICLE_ANALYSIS_PROMPT.messages[1].prompt.template

        self.assertIn("기사 제목과 부제목은 주제·기업·의약품·키워드를 파악하는 보조 정보", system_prompt)
        self.assertIn("부제목에만 있고 본문에서 확인되지 않는 내용은 검증된 사실처럼 단정하지 않습니다", system_prompt)
        self.assertIn("본문을 주요 근거", system_prompt)
        self.assertIn("{title}", human_prompt)
        self.assertIn("{subtitle}", human_prompt)
        self.assertIn("{article}", human_prompt)

    def test_article_question_prompt_requests_two_distinct_grounded_questions(self):
        system_prompt = ARTICLE_ANALYSIS_PROMPT.messages[0].prompt.template

        self.assertIn("article_questions에는 일반 질문 모드", system_prompt)
        self.assertIn("정확히 2개", system_prompt)
        self.assertIn("구체적인 단서를 그대로 포함", system_prompt)

    def test_article_question_validator_keeps_two_distinct_questions_with_article_anchors(self):
        analysis = ArticleAnalysis(
            article_type="제약·바이오",
            one_line_summary="Aster Bio의 ADC 후보물질 개발 소식입니다.",
            key_issue="후보물질의 임상 진입이 업계 관심을 받고 있습니다.",
            key_entities=["Aster Bio"],
            key_terms=[PharmaTerm(
                term="ADC 후보물질", category="Modality", reason="개발 방식을 이해합니다.",
                simple_definition="항체에 약물을 연결한 치료 후보입니다.",
                article_context="Aster Bio의 후보물질입니다.", aliases=["ADC"],
            )],
            confusing_points=[],
            article_questions=[
                "Aster Bio의 ADC 후보물질 개발이 기사에서 중요한 이유는 무엇인가요?",
                "ADC 후보물질의 임상 진입은 업계 이슈와 어떻게 연결되나요?",
            ],
        )

        result = validate_article_questions(
            analysis,
            "Aster Bio는 ADC 후보물질의 임상 진입을 발표했다.",
        )

        self.assertEqual(result, analysis.article_questions)

    def test_article_question_validator_falls_back_for_ungrounded_questions(self):
        analysis = ArticleAnalysis(
            article_type="제약·바이오",
            one_line_summary="Aster Bio가 ADC 후보물질을 개발합니다.",
            key_issue="Aster Bio의 후보물질 개발 소식입니다.",
            key_entities=["Aster Bio"],
            key_terms=[PharmaTerm(
                term="ADC", category="Modality", reason="치료 방식을 이해합니다.",
                simple_definition="항체와 약물을 연결한 방식입니다.",
                article_context="후보물질 개발에 활용됩니다.", aliases=[],
            )],
            confusing_points=[],
            article_questions=["FDA 승인이 이미 확정된 이유는 무엇인가요?", "임상 성공률은 얼마인가요?"],
        )

        result = validate_article_questions(analysis, "Aster Bio는 ADC 후보물질을 개발한다.")

        self.assertEqual(len(result), 2)
        self.assertIn("Aster Bio", result[0])
        self.assertIn("ADC", result[1])
        self.assertTrue(all(item.endswith("?") for item in result))

    def test_analysis_filter_removes_institution_name_and_alias_but_keeps_concepts(self):
        institution = (
            "브라질 보건부 산하 의약품청(ANVISA, "
            "Agência Nacional de Vigilância Sanitária)"
        )
        analysis = ArticleAnalysis(
            article_type="임상",
            one_line_summary="가상 임상 결과를 다룹니다.",
            key_issue="허가 절차가 검토 중입니다.",
            key_entities=[institution],
            key_terms=[
                PharmaTerm(
                    term=institution, category="Regulatory", reason="기관입니다.",
                    simple_definition="브라질의 의약품 규제 기관입니다.",
                    article_context="기사에 언급됩니다.", aliases=["ANVISA"],
                ),
                PharmaTerm(
                    term="ANVISA", category="Regulatory", reason="기관 약칭입니다.",
                    simple_definition="브라질의 의약품 규제 기관입니다.",
                    article_context="기사에 언급됩니다.", aliases=["Agência Nacional de Vigilância Sanitária"],
                ),
                PharmaTerm(
                    term="의약품 품목 허가", category="Regulatory", reason="개념입니다.",
                    simple_definition="의약품을 판매하도록 승인하는 절차입니다.",
                    article_context="허가 절차를 다룹니다.", aliases=["품목 허가"],
                ),
                PharmaTerm(
                    term="임상 3상", category="Clinical Trial", reason="개발 단계를 이해합니다.",
                    simple_definition="환자에게 약의 효과와 안전성을 넓게 확인하는 단계입니다.",
                    article_context="후기 임상시험입니다.", aliases=["Phase 3"],
                ),
                PharmaTerm(
                    term="가슴 쓰림", category="Disease", reason="일상적인 증상입니다.",
                    simple_definition="가슴이 타는 듯한 느낌입니다.",
                    article_context="부작용으로 언급됩니다.", aliases=["heartburn"],
                ),
            ],
            confusing_points=[],
        )

        class FakeChain:
            def invoke(self, payload):
                self.payload = payload
                return analysis

        chain = FakeChain()
        result = analyze_article(chain, "기사 본문", title="기사 제목", subtitle="기사 부제목")

        self.assertEqual(chain.payload, {
            "article": "기사 본문", "title": "기사 제목", "subtitle": "기사 부제목",
        })
        self.assertEqual([term.term for term in result.key_terms], ["의약품 품목 허가", "임상 3상"])
        self.assertEqual(result.key_entities, [institution])

    def test_directly_added_term_gets_ai_category_and_keeps_source_context(self):
        source_context = "후보물질은 단백질 분해 유도, 즉 표적 단백질 분해 기술을 활용한다."

        class FakeChain:
            def invoke(self, payload):
                self.payload = payload
                return ManualTermClassification(
                    category="Mechanism",
                    reason="약물이 작동하는 원리를 설명하는 개념입니다.",
                    simple_definition="표적 단백질이 분해되도록 유도하는 방식입니다.",
                    article_context="재구성하지 않은 모델 문맥",
                    aliases=["표적 단백질 분해"],
                    evidence=source_context,
                    confidence="high",
                )

        chain = FakeChain()
        result = classify_manual_term(chain, "단백질 분해 유도", source_context, "기술/플랫폼")

        self.assertEqual(chain.payload["article_context"], source_context)
        self.assertEqual(result.category, "Mechanism")
        self.assertEqual(result.article_context, source_context)
        self.assertEqual(result.aliases, ["표적 단백질 분해"])

    def test_manual_term_prompt_requires_evidence_for_category_and_definition(self):
        system_prompt = MANUAL_TERM_CLASSIFICATION_PROMPT.messages[0].prompt.template

        self.assertIn("Clinical Metric", system_prompt)
        self.assertIn("Modality", system_prompt)
        self.assertIn("근거가 불충분하면 추측하지 말고", system_prompt)
        self.assertIn("evidence는 반드시 제공된 기사 문맥에서 그대로 복사", system_prompt)
        self.assertTrue(ManualTermClassificationModelOutput.model_fields["evidence"].is_required())
        self.assertTrue(ManualTermClassificationModelOutput.model_fields["confidence"].is_required())

    def test_low_confidence_manual_classification_uses_context_rules(self):
        class FakeChain:
            def invoke(self, _payload):
                return ManualTermClassification(
                    category="Drug", reason="불확실", simple_definition="불확실",
                    article_context="", aliases=[], confidence="low",
                )

        result = classify_manual_term(
            FakeChain(), "임상 3상", "임상 3상 시험에서 안전성과 유효성을 평가한다.", "임상"
        )

        self.assertEqual(result.category, "Clinical Trial")
        self.assertIn("임상시험", result.simple_definition)

    def test_unsupported_manual_evidence_falls_back_without_inventing_definition(self):
        class FakeChain:
            def invoke(self, _payload):
                return ManualTermClassification(
                    category="Drug", reason="모델 추측", simple_definition="모델이 추측한 뜻입니다.",
                    article_context="", aliases=[], evidence="없는 근거", confidence="high",
                )

        result = classify_manual_term(FakeChain(), "미확인 표현", "기사에서 해당 표현을 소개했다.", "기타")

        self.assertEqual(result.category, "Other")
        self.assertNotEqual(result.simple_definition, "모델이 추측한 뜻입니다.")

    def test_regulatory_agency_name_is_not_mistaken_for_regulatory_process(self):
        class FakeChain:
            def invoke(self, _payload):
                return ManualTermClassification(
                    category="Regulatory", reason="기관", simple_definition="기관입니다.",
                    article_context="", aliases=[], confidence="low",
                )

        result = classify_manual_term(FakeChain(), "FDA", "FDA가 의약품 허가를 심사한다.", "규제")

        self.assertEqual(result.category, "Other")

    def test_manual_term_can_use_other_category(self):
        term = PharmaTerm(
            term="사용자가 추가한 용어", category="Other", reason="직접 선택했습니다.",
            simple_definition="", article_context="기사 문단에서 선택했습니다.", aliases=[],
        )

        self.assertEqual(term.category, "Other")


if __name__ == "__main__":
    unittest.main()
