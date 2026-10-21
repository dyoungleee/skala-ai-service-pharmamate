"""Small, attributed reference set and source selection for tutor answers."""
from __future__ import annotations

import re
from urllib.parse import urlparse


TRUSTED_HOSTS = (
    "clinicaltrials.gov", "cancer.gov", "fda.gov", "nih.gov",
    "who.int", "ema.europa.eu", "mfds.go.kr", "cris.nih.go.kr",
)

_CARE_TERMS = re.compile(r"(?:(?<![A-Za-z])(?:BSC|SoC)(?![A-Za-z])|best supportive care|standard of care|지지\s*요법|표준\s*(?:요법|치료))", re.I)
_TRIAL_DETAIL = re.compile(r"(?:구체적|실제로|정확히|프로토콜|대조군|시험군).{0,30}(?:구성|약물|치료|투여|환자|영향)|(?:구성|약물|치료|투여).{0,30}(?:구체적|프로토콜|대조군|시험군)")


def needs_care_reference(question: str) -> bool:
    return bool(_CARE_TERMS.search(question))


def asks_trial_detail(question: str) -> bool:
    return bool(_TRIAL_DETAIL.search(question))


def care_references(question: str) -> list[dict[str, str]]:
    """NCI definitions are general background, never a trial's exact regimen."""
    if not needs_care_reference(question):
        return []
    return [
        {
            "title": "NCI Dictionary: supportive care",
            "url": "https://www.cancer.gov/publications/dictionaries/cancer-terms/def/supportive-care",
            "content": "질병의 증상과 치료 부작용을 예방·완화하여 삶의 질을 돕는 돌봄. 통증 관리, 영양 지원, 상담 등이 예시다. 이는 일반적인 supportive care의 정의이며 특정 임상시험의 BSC 구성이나 환자별 처치 내역을 뜻하지 않는다.",
        },
        {
            "title": "NCI Dictionary: standard of care",
            "url": "https://www.cancer.gov/publications/dictionaries/cancer-terms/def/standard-of-care",
            "content": "해당 질환에 적절하다고 의료 전문가들이 받아들이고 널리 사용하는 치료. 이는 일반적인 SoC 정의이며 특정 시험의 대조군 약물·용량·치료 조합을 뜻하지 않는다.",
        },
    ]


def is_trusted_source(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host == domain or host.endswith("." + domain) for domain in TRUSTED_HOSTS)
