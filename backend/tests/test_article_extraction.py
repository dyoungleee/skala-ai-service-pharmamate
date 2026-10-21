from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup

from backend.app.services.article_extraction import (
    extract_article_document,
    extract_article_text,
    load_article,
)


class ArticleExtractionTests(unittest.TestCase):
    def test_newsis_article_body_excludes_header_deck_caption_and_footer(self):
        title = '셀비온 "전립선암 치료제, 국내 3상 IND 승인"'
        subtitle = "전이성 거세저항성 전립선암 환자 대상"
        lead = (
            "[서울=뉴시스] 기자 = 전이성 거세저항성 전립선암 환자 대상 연구를 시작한다. "
            "이 문장은 기사 본문의 실제 리드문으로 남아야 한다. "
        ) * 4
        followup = "회사는 임상시험 계획과 다음 개발 단계를 구체적으로 설명했다. " * 6
        html = f"""
        <html><head><meta property="og:title" content='{title}'></head><body>
          <div itemprop="articleBody">
            <div class="top"><h1>{title}</h1></div>
            <div class="infoLine"><span>등록 2026.09.29 09:33:40</span>
              <a>구글에서 선호하는 매체로 추가</a></div>
            <div class="viewer"><article>
              <div class="summury"><h2>{subtitle}</h2></div>
              <div class="plain-headline">{title}</div>
              <div class="thumCont"><img alt="기사 사진">
                <p class="photojournal">사진 설명: 기사 본문이 아닌 이미지 설명입니다.
                  <a>[email protected]</a></p></div>
              <p>{lead}</p><p>{followup}</p>
              <div class="box-listNews">이시간 핫 뉴스 추천 문구</div>
              <p>◎공감언론 뉴시스</p><p>[email protected]</p>
            </article></div>
          </div>
        </body></html>
        """

        document = extract_article_document(BeautifulSoup(html, "html.parser"))

        self.assertEqual(document["title"], title)
        self.assertEqual(document["subtitle"], subtitle)
        self.assertTrue(document["body"].startswith("[서울=뉴시스] 기자 ="))
        self.assertIn("이 문장은 기사 본문의 실제 리드문", document["body"])
        self.assertIn("다음 개발 단계", document["body"])
        for noise in (title, "등록 2026", "구글에서", "사진 설명", "[email protected]", "핫 뉴스", "공감언론"):
            self.assertNotIn(noise, document["body"])

    def test_newsis_article_cont_keeps_real_paragraphs_after_photo(self):
        body = "실제 본문 문장에는 후보물질의 연구 계획과 후속 절차가 서술되어 있다. " * 8
        html = f"""
        <html><body><article class="article-wrap">
          <header class="article-header"><h1>기사 제목</h1><p>수정 2026/09/29 10:14:24</p></header>
          <div class="article-cont">
            <div class="box-summury"><h2>이 기사의 부제목입니다</h2></div>
            <div class="box-figure"><figure><img src="photo.jpg">
              <figcaption><p>기사와 관련된 사진 설명입니다.</p></figcaption></figure></div>
            <p>{body}</p><p>이 문단은 기사 본문 끝까지 보존되어야 합니다.</p>
            <div class="box-listNews">기사와 무관한 추천 기사</div>
            <p>◎공감언론 뉴시스</p>
          </div>
        </article></body></html>
        """

        document = extract_article_document(BeautifulSoup(html, "html.parser"))

        self.assertEqual(document["subtitle"], "이 기사의 부제목입니다")
        self.assertTrue(document["body"].startswith("실제 본문 문장"))
        self.assertIn("본문 끝까지 보존", document["body"])
        self.assertNotIn("사진 설명", document["body"])
        self.assertNotIn("추천 기사", document["body"])
        self.assertNotIn("공감언론", document["body"])

    def test_preserves_visible_spacing_between_article_paragraphs(self):
        first = "첫 번째 문단은 후보물질의 개발 배경을 설명합니다. " * 8
        second = "두 번째 문단은 임상시험의 다음 단계를 설명합니다. " * 8
        html = f"""
        <html><body><div id="articleBody">
          <p>{first}</p><p>{second}</p>
        </div></body></html>
        """

        article, method = extract_article_text(BeautifulSoup(html, "html.parser"))

        self.assertEqual(method, "article_selector")
        self.assertIn(
            f"{' '.join(first.split())}\n\n{' '.join(second.split())}",
            article,
        )

    def test_extracts_subtitle_separately_and_keeps_matching_lead_in_body(self):
        subtitle = "신약 후보물질의 임상 3상에서 주요 평가 지표를 충족했다"
        repeated_body = (subtitle + ". 실제 본문 문장입니다. ") * 8
        html = f"""
        <html><head><meta property="og:title" content="가상 신약 임상 결과" /></head><body>
          <header><h1>가상 신약 임상 결과</h1>
            <p class="article-deck">{subtitle}</p><div class="byline">홍길동 기자</div>
          </header>
          <div id="articleBody"><p>{repeated_body}</p>
            <p>후속 문단은 실제 기사 본문이며 그대로 보존합니다. {repeated_body}</p>
          </div>
        </body></html>
        """

        document = extract_article_document(BeautifulSoup(html, "html.parser"))

        self.assertEqual(document["title"], "가상 신약 임상 결과")
        self.assertEqual(document["subtitle"], subtitle)
        self.assertIn("body", document)
        self.assertNotIn("가상 신약 임상 결과", document["body"])
        self.assertGreaterEqual(document["body"].count(subtitle), 8)
        self.assertIn("후속 문단은 실제 기사 본문", document["body"])

    def test_title_adjacent_h2_is_subtitle_but_unmarked_first_paragraph_is_lead(self):
        body_text = "실제 첫 문단 리드문입니다. " * 12
        html_with_deck = f"""
        <html><body><div class="headline"><h1>기사 제목</h1><h2>기업 핵심 요약 부제목입니다</h2></div>
          <div id="articleBody"><p>{body_text}</p><p>후속 본문 설명입니다. {body_text}</p></div>
        </body></html>
        """
        html_with_lead = f"""
        <html><body><h1>기사 제목</h1><div class="byline">홍길동 기자</div>
          <div class="article-body"><p>{body_text}</p><p>후속 본문 설명입니다. {body_text}</p></div>
        </body></html>
        """

        deck_document = extract_article_document(BeautifulSoup(html_with_deck, "html.parser"))
        lead_document = extract_article_document(BeautifulSoup(html_with_lead, "html.parser"))

        self.assertEqual(deck_document["subtitle"], "기업 핵심 요약 부제목입니다")
        self.assertNotIn("기업 핵심 요약 부제목입니다", deck_document["body"])
        self.assertEqual(lead_document["subtitle"], "")
        self.assertIn("실제 첫 문단 리드문입니다.", lead_document["body"])

    def test_multiple_prebody_decks_and_headings_are_excluded_from_body(self):
        body_text = "실제 기사 본문 첫 문단으로 보존되어야 하는 문장입니다. " * 12
        html = f"""
        <html><body><h1>복수 부제목이 있는 기사</h1>
          <div id="articleBody">
            <div class="article-sub-tit">임상 3상 주요 지표 충족</div>
            <h3>후속 허가 절차를 준비할 예정</h3>
            <p>{body_text}</p>
            <p>두 번째 본문 문단입니다. {body_text}</p>
          </div>
        </body></html>
        """

        document = extract_article_document(BeautifulSoup(html, "html.parser"))

        self.assertEqual(
            document["subtitle"],
            "임상 3상 주요 지표 충족\n후속 허가 절차를 준비할 예정",
        )
        self.assertTrue(document["body"].startswith("실제 기사 본문 첫 문단"))
        self.assertNotIn("임상 3상 주요 지표 충족", document["body"])
        self.assertNotIn("후속 허가 절차를 준비할 예정", document["body"])
        self.assertIn("두 번째 본문 문단", document["body"])

    def test_url_loading_returns_subtitle_in_metadata_and_body_separately(self):
        subtitle = "기업은 신약 후보물질의 임상 개발을 이어간다"
        body_text = "본문에서 실제로 확인되는 개발 계획과 임상 내용입니다. " * 12
        html = f"""
        <html><body><h1>기사 제목</h1><p class="subtitle">{subtitle}</p>
          <div id="articleBody"><p>{body_text}</p></div>
        </body></html>
        """
        response = Mock()
        response.content = html.encode("utf-8")
        response.url = "https://example.com/article"
        response.raise_for_status.return_value = None

        with patch("backend.app.services.article_extraction.requests.get", return_value=response):
            body, metadata = load_article(url="https://example.com/article")

        self.assertEqual(metadata["title"], "기사 제목")
        self.assertEqual(metadata["subtitle"], subtitle)
        self.assertIn("본문에서 실제로 확인되는 개발 계획", body)
        self.assertNotIn(subtitle, body)

    def test_image_caption_marked_like_subtitle_is_not_extracted(self):
        body_text = "기사 본문에서 확인된 실제 임상 결과와 개발 계획입니다. " * 12
        html = f"""
        <html><body><h1>기사 제목</h1>
          <figure><figcaption class="article-subtitle">이미지 캡션은 부제목이 아닙니다.</figcaption></figure>
          <div id="articleBody"><p>{body_text}</p></div>
        </body></html>
        """

        document = extract_article_document(BeautifulSoup(html, "html.parser"))

        self.assertEqual(document["subtitle"], "")
        self.assertNotIn("이미지 캡션은 부제목이 아닙니다.", document["body"])

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

    def test_removes_image_captions_but_preserves_article_paragraphs(self):
        first_paragraph = "실제 본문 첫 문단 표식: 연구진은 후보물질의 개발 계획을 설명했습니다. " * 7
        final_paragraph = "실제 본문 마지막 문단 표식: 다음 단계에서는 안전성과 효과를 확인합니다. " * 7
        wrapped_article_paragraph = "figure 영역 안에 있어도 보존해야 하는 실제 기사 문단입니다. " * 7
        html = f"""
        <html><body><div id="articleBody">
          <p>{first_paragraph}</p>
          <figure>
            <img src="/candidate.png" alt="캡션보다 우선하지 않는 대체 텍스트">
            <figcaption>이 이미지는 후보물질이 암세포를 찾아가는 과정을 보여준다.</figcaption>
          </figure>
          <p class="article-image-description">이미지 설명 전용 문구: 후보물질의 작동 장면.</p>
          <div class="photo_desc">사진 설명 전용 문구: 실험 장면.</div>
          <div class="figure-wrapper"><p>{wrapped_article_paragraph}</p></div>
          <p class="image-caption">속성에 caption이 표시된 이미지 캡션입니다.</p>
          <p class="figcaption">태그가 아닌 속성에 표시된 figcaption 문구입니다.</p>
          <span class="photo-credit">사진 설명 크레딧 전용 문구.</span>
          <p class="configuration-summary">설정 관련 실제 문단은 보존합니다.</p>
          <p>{final_paragraph}</p>
        </div></body></html>
        """

        article, method = extract_article_text(BeautifulSoup(html, "html.parser"))

        self.assertEqual(method, "article_selector")
        self.assertIn(" ".join(first_paragraph.split()), article)
        self.assertIn(" ".join(wrapped_article_paragraph.split()), article)
        self.assertIn(" ".join(final_paragraph.split()), article)
        self.assertLess(article.index("실제 본문 첫 문단 표식"), article.index("실제 본문 마지막 문단 표식"))
        self.assertNotIn("암세포를 찾아가는 과정", article)
        self.assertNotIn("이미지 설명 전용 문구", article)
        self.assertNotIn("사진 설명 전용 문구", article)
        self.assertNotIn("속성에 caption이 표시된 이미지 캡션", article)
        self.assertNotIn("속성에 표시된 figcaption 문구", article)
        self.assertNotIn("사진 설명 크레딧 전용 문구", article)
        self.assertIn("설정 관련 실제 문단은 보존합니다.", article)
        self.assertNotIn("캡션보다 우선하지 않는 대체 텍스트", article)

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
