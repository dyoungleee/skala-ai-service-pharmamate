"""Structured article analysis shared by Gradio and FastAPI."""
from __future__ import annotations

from typing import Any

from langchain_core.prompts import ChatPromptTemplate

from backend.app.schemas.article import ArticleAnalysis


ARTICLE_ANALYSIS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """당신은 비전공자를 위한 제약·바이오 뉴스 읽기 튜터입니다.
목표는 기사를 대신 읽어주는 것이 아니라 사용자가 기사 원문을 빠르게 읽게 돕는 것입니다.
규칙:
1. 기사를 장황하게 요약하지 말고 업계에서 실제로 일어난 일을 쉽고 정확하게 정리합니다.
2. 회사명·제품명 등 고유명사와 재사용 가치가 있는 일반 전문용어를 구분합니다.
3. 재사용 가치가 높은 핵심 용어 3~5개만 골라 쉬운 정의와 기사 맥락을 짧게 씁니다.
4. 본문에 없는 사실, 확인되지 않은 승인·임상 결과를 만들지 않습니다.
5. 회사 주장, 전망, 검증된 결과를 구분합니다.
6. 탐색 메뉴·광고·관련 기사 목록은 핵심 근거로 사용하지 않습니다.
7. 약어의 뜻은 본문에 나오거나 명확할 때만 기록하고 추측하지 않습니다."""),
    ("human", "[기사 본문]\n{article}"),
])


def build_article_analysis_chain(model: Any) -> Any:
    return ARTICLE_ANALYSIS_PROMPT | model.with_structured_output(ArticleAnalysis)


def analyze_article(chain: Any, article: str) -> ArticleAnalysis:
    if not article or not article.strip():
        raise ValueError("분석할 기사 본문이 없습니다.")
    return chain.invoke({"article": article[:14000]})
