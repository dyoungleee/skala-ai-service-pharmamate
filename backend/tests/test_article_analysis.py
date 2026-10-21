from __future__ import annotations

import unittest

from backend.app.services.article_analysis import ARTICLE_ANALYSIS_PROMPT


class ArticleAnalysisPromptTests(unittest.TestCase):
    def test_prompt_excludes_related_image_captions_but_keeps_real_body_text(self):
        system_prompt = ARTICLE_ANALYSIS_PROMPT.messages[0].prompt.template

        self.assertIn("사진·이미지의 캡션과 이미지 설명문", system_prompt)
        self.assertIn("기사 주제와 관련되어도", system_prompt)
        self.assertIn("실제 기사 본문에 쓰인 문장과 문단", system_prompt)


if __name__ == "__main__":
    unittest.main()
