from __future__ import annotations

import unittest

from backend.app.schemas.article import ArticleAnalysis, PharmaTerm
from backend.app.services.article_analysis import ARTICLE_ANALYSIS_PROMPT, analyze_article


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
            def invoke(self, _payload):
                return analysis

        result = analyze_article(FakeChain(), "기사 본문")

        self.assertEqual([term.term for term in result.key_terms], ["의약품 품목 허가", "임상 3상"])
        self.assertEqual(result.key_entities, [institution])

    def test_manual_term_can_use_other_category(self):
        term = PharmaTerm(
            term="사용자가 추가한 용어", category="Other", reason="직접 선택했습니다.",
            simple_definition="", article_context="기사 문단에서 선택했습니다.", aliases=[],
        )

        self.assertEqual(term.category, "Other")


if __name__ == "__main__":
    unittest.main()
