"""Article analysis response models shared across application entry points."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


CATEGORIES = [
    "Modality", "Drug", "Target", "Biomarker", "Disease", "Clinical Trial",
    "Clinical Metric", "Regulatory", "Business", "Manufacturing", "Platform",
    "Diagnostic", "Mechanism", "Technology",
]


class PharmaTerm(BaseModel):
    term: str = Field(description="핵심 전문용어. 약어가 있으면 정식 명칭과 함께 표기합니다.")
    category: Literal[
        "Modality", "Drug", "Target", "Biomarker", "Disease", "Clinical Trial",
        "Clinical Metric", "Regulatory", "Business", "Manufacturing", "Platform",
        "Diagnostic", "Mechanism", "Technology",
    ]
    reason: str = Field(description="이 용어를 배워야 하는 이유 한 문장")
    simple_definition: str = Field(description="비전공자가 이해할 수 있는 쉬운 한 문장 정의")
    article_context: str = Field(description="이 기사에서 용어가 사용된 맥락 한 문장")
    aliases: list[str] = Field(description="본문에서 확인한 약어·전체 이름·한국어 동의어")


class ArticleAnalysis(BaseModel):
    article_type: Literal[
        "임상", "규제", "기술/플랫폼", "투자", "기술이전", "파트너십",
        "사업/전략", "연구/학술", "산업동향", "기타",
    ]
    one_line_summary: str = Field(description="기사를 쉽게 이해할 수 있게 핵심만 1~2문장")
    key_issue: str = Field(description="기업·기술·사건과 연결되는 업계 핵심 이슈 1~2문장")
    key_entities: list[str] = Field(description="기사 속 주요 기업, 신약 후보, 연구기관 등")
    key_terms: list[PharmaTerm] = Field(description="재사용 가치가 높은 핵심 개념 3~5개")
    confusing_points: list[str] = Field(description="읽을 때 혼동하기 쉬운 지점 최대 2개")
