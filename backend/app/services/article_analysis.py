"""Structured article analysis shared by Gradio and FastAPI."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from langchain_core.prompts import ChatPromptTemplate

from backend.app.schemas.article import ArticleAnalysis


ARTICLE_ANALYSIS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """당신은 비전공자를 위한 제약·바이오 뉴스 읽기 튜터입니다.
목표는 기사를 대신 읽어주는 것이 아니라 사용자가 기사 원문을 빠르게 읽게 돕는 것입니다.
규칙:
1. 기사를 장황하게 요약하지 말고 업계에서 실제로 일어난 일을 쉽고 정확하게 정리합니다.
2. 회사명·제품명 등 고유명사와 재사용 가치가 있는 일반 전문용어를 구분합니다.
3. 재사용 가치가 높은 일반 핵심 용어를 3~5개 목표로 골라 쉬운 정의와 기사 맥락을 짧게 씁니다. 적합한 개념이 적으면 더 적게 제시하고 기관명으로 개수를 채우지 않습니다.
4. 본문에 없는 사실, 확인되지 않은 승인·임상 결과를 만들지 않습니다.
5. 회사 주장, 전망, 검증된 결과를 구분합니다.
6. 탐색 메뉴·광고·관련 기사 목록은 핵심 근거로 사용하지 않습니다.
7. 약어의 뜻은 본문에 나오거나 명확할 때만 기록하고 추측하지 않습니다.
8. 사진·이미지의 캡션과 이미지 설명문은 기사 주제와 관련되어도 기사 본문 근거나 분석 결과에 포함하지 않습니다.
9. 실제 기사 본문에 쓰인 문장과 문단은 이미지 설명으로 오인해 제외하지 말고 그대로 분석 근거로 사용합니다.
10. 정부부처, 규제기관·의약품청, 병원, 대학, 연구기관 등의 기관명과 약칭·현지어 정식 명칭은 학습 용어에서 제외하고 주요 엔티티로만 기록합니다. 기사와 밀접하게 관련되어도 key_terms에는 넣지 않습니다.
11. 기관 이름과 기관이 다루는 개념은 구분합니다. 기관명은 제외하되 임상 단계, 허가 절차, 의약품 후보, 표적, 작용 기전 같은 일반 개념은 용어로 남깁니다."""),
    ("human", "[기사 본문]\n{article}"),
])


def build_article_analysis_chain(model: Any) -> Any:
    return ARTICLE_ANALYSIS_PROMPT | model.with_structured_output(ArticleAnalysis)


_KOREAN_ORGANIZATION_MARKERS = (
    "보건부", "복지부", "식품의약품안전처", "식약처", "의약품청", "의약품안전청",
    "질병관리청", "보건당국", "규제당국", "규제기관", "정부부처", "위원회",
    "연구기관", "연구소", "연구원", "대학교", "대학병원", "병원", "의료원",
    "센터", "협회", "재단", "공단", "공사", "관리국",
)
_INTERNATIONAL_ORGANIZATION_MARKER = re.compile(
    r"\b(?:agency|agencia|authority|autoridade|administration|ministry|ministerio|"
    r"department|institute|instituto|institution|organization|organisation|organizacao|"
    r"university|universidade|hospital|medical center|medical centre|center|centre|"
    r"committee|commission|comissao|council|conselho|foundation|fundacao|association|"
    r"associacao|society|regulator)\b",
    re.IGNORECASE,
)
_PARENTHESES = re.compile(r"[\(（\[【]([^\)）\]】]+)[\)）\]】]")


def _organization_text(value: str) -> str:
    text = unicodedata.normalize("NFC", str(value or "")).casefold()
    for accented, plain in (
        ("á", "a"), ("à", "a"), ("â", "a"), ("ã", "a"), ("ä", "a"),
        ("é", "e"), ("è", "e"), ("ê", "e"), ("ë", "e"),
        ("í", "i"), ("ì", "i"), ("î", "i"), ("ï", "i"),
        ("ó", "o"), ("ò", "o"), ("ô", "o"), ("õ", "o"), ("ö", "o"),
        ("ú", "u"), ("ù", "u"), ("û", "u"), ("ü", "u"), ("ç", "c"),
    ):
        text = text.replace(accented, plain)
    return text


def _normalized_name(value: str) -> str:
    return re.sub(r"[^\w]+", "", _organization_text(value), flags=re.UNICODE)


def _looks_like_organization_name(value: str) -> bool:
    text = _organization_text(value)
    compact = _normalized_name(text)
    return (
        any(marker in text for marker in _KOREAN_ORGANIZATION_MARKERS)
        or bool(_INTERNATIONAL_ORGANIZATION_MARKER.search(text))
        or any(marker in compact for marker in _KOREAN_ORGANIZATION_MARKERS)
    )


def _organization_name_variants(value: str) -> set[str]:
    text = str(value or "").strip()
    variants = {_normalized_name(text)} - {""}
    matches = list(_PARENTHESES.finditer(text))
    if matches and not text[matches[-1].end():].strip(" .;:·"):
        prefix = text[:matches[0].start()].strip()
        if prefix:
            variants.add(_normalized_name(prefix))
        for match in matches:
            for alias in re.split(r"[,，;；|/]", match.group(1)):
                normalized_alias = _normalized_name(alias)
                if normalized_alias:
                    variants.add(normalized_alias)
    return variants


def _filter_organization_terms(analysis: ArticleAnalysis) -> ArticleAnalysis:
    organization_aliases: set[str] = set()
    for entity in analysis.key_entities:
        if _looks_like_organization_name(entity):
            organization_aliases.update(_organization_name_variants(entity))

    key_terms = [
        term for term in analysis.key_terms
        if not _looks_like_organization_name(term.term)
        and not (_organization_name_variants(term.term) & organization_aliases)
    ]
    if len(key_terms) == len(analysis.key_terms):
        return analysis
    return analysis.model_copy(update={"key_terms": key_terms})


def analyze_article(chain: Any, article: str) -> ArticleAnalysis:
    if not article or not article.strip():
        raise ValueError("분석할 기사 본문이 없습니다.")
    analysis = chain.invoke({"article": article[:14000]})
    return _filter_organization_terms(analysis)
