from __future__ import annotations

import unittest

from bs4 import BeautifulSoup

from backend.app.services.article_extraction import extract_article_text


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


if __name__ == "__main__":
    unittest.main()
