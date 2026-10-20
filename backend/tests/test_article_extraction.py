from __future__ import annotations

import unittest

from bs4 import BeautifulSoup

from backend.app.services.article_extraction import extract_article_text, load_article


class ArticleExtractionTests(unittest.TestCase):
    def test_extracts_article_region_and_removes_related_article_copy(self):
        article_body = "제약 기업은 가상 후보물질의 임상 1상에서 안전성과 내약성을 살펴볼 계획입니다. " * 12
        related_body = "다른 기사 목록에 있는 별개의 기업과 후보물질 소식입니다. " * 12
        html = f"""
        <html><body>
          <nav>홈 뉴스 검색 메뉴</nav>
          <main>
            <div id="articleBody"><p>{article_body}</p>
              <div class="related-news"><h2>관련 기사</h2><p>{related_body}</p></div>
              <div class="share">공유하기 인쇄</div>
            </div>
          </main>
          <aside><p>{related_body}</p></aside>
        </body></html>
        """

        article, method = extract_article_text(BeautifulSoup(html, "html.parser"))

        self.assertEqual(method, "article_selector")
        self.assertIn("안전성과 내약성", article)
        self.assertNotIn("다른 기사 목록", article)
        self.assertNotIn("공유하기", article)
        self.assertNotIn("홈 뉴스 검색", article)

    def test_does_not_use_generic_page_text_when_article_region_is_missing(self):
        unrelated_page_text = "추천 기사와 사이트 메뉴의 문장입니다. " * 20
        html = f"<html><body><nav>{unrelated_page_text}</nav><div class='layout'>{unrelated_page_text}</div></body></html>"

        with self.assertRaisesRegex(ValueError, "기사 본문 영역을 찾지 못했습니다"):
            extract_article_text(BeautifulSoup(html, "html.parser"))

    def test_trims_plain_text_tags_reporter_and_recommendation_tail(self):
        article_body = "개발 단계 준비와 후보물질의 임상 연구 확대를 이어갈 것이라고 밝혔다. " * 12
        html = f"""
        <html><body>
          <div id="articleBody">
            <p>{article_body}</p>
            <p>관련태그</p>
            <p>#에이비엘바이오</p><p>#ESMO 2026</p><p>#이중항체</p>
            <p>뉴스웨이</p><p>임주희 기자</p><p>ljh@newsway.co.kr</p>
            <p>+</p><p>기자채널</p><p>다른기사</p>
            <p>남태훈 국제약품 대표 "흔들림 없는 실행으로 100년 기업 만들자"</p>
            <p>저작권자 © 온라인 경제미디어 뉴스웨이 · 무단 전재 및 재배포 금지</p>
          </div>
        </body></html>
        """

        article, method = extract_article_text(BeautifulSoup(html, "html.parser"))

        self.assertEqual(method, "article_selector")
        self.assertIn("임상 연구 확대", article)
        self.assertNotIn("관련태그", article)
        self.assertNotIn("#ESMO", article)
        self.assertNotIn("ljh@newsway.co.kr", article)
        self.assertNotIn("기자채널", article)
        self.assertNotIn("흔들림 없는 실행", article)
        self.assertNotIn("무단 전재", article)

    def test_removes_image_credits_and_copyright_lines_without_losing_article_text(self):
        article_body = "연구진은 후보물질의 작동 원리와 다음 개발 단계를 설명했습니다. " * 12
        html = f"""
        <html><body><div id="articleBody">
          <p>{article_body}</p>
          <p>사진=뉴스웨이</p>
          <p>이후 연구진은 추가 연구를 이어갈 계획이라고 밝혔습니다.</p>
          <p>후속 연구를 준비합니다. 사진=뉴스웨이</p>
          <p>이미지 출처: Getty Images</p>
          <p>Copyright © 2026 Newsway. All rights reserved.</p>
        </div></body></html>
        """

        article, _method = extract_article_text(BeautifulSoup(html, "html.parser"))

        self.assertIn("작동 원리", article)
        self.assertIn("추가 연구를 이어갈 계획", article)
        self.assertIn("후속 연구를 준비합니다.", article)
        self.assertNotIn("사진=뉴스웨이", article)
        self.assertNotIn("Getty Images", article)
        self.assertNotIn("Copyright", article)

    def test_removes_image_credit_from_pasted_article_text(self):
        article_body = "가상 기사 본문은 후보물질 연구 계획과 업계 흐름을 설명합니다. " * 8
        pasted = (
            f"{article_body}\n사진 제공=연합뉴스\n"
            "이 내용은 본문입니다. Copyright © 2026 Newsway. All rights reserved."
        )

        article, metadata = load_article(pasted_text=pasted)

        self.assertEqual(metadata["load_method"], "manual")
        self.assertIn("업계 흐름", article)
        self.assertNotIn("사진 제공", article)
        self.assertNotIn("Copyright", article)
        self.assertIn("이 내용은 본문입니다.", article)


if __name__ == "__main__":
    unittest.main()
