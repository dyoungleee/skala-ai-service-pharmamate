"""Structured article analysis shared by Gradio and FastAPI."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from langchain_core.prompts import ChatPromptTemplate

from backend.app.schemas.article import (
    ArticleAnalysis,
    ManualTermClassification,
    ManualTermClassificationModelOutput,
    PharmaTerm,
)


ARTICLE_ANALYSIS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """당신은 비전공자를 위한 제약·바이오 뉴스 읽기 튜터입니다.
목표는 기사를 대신 읽어주는 것이 아니라 사용자가 기사 원문을 빠르게 읽게 돕는 것입니다.
규칙:
1. 기사를 장황하게 요약하지 말고 업계에서 실제로 일어난 일을 쉽고 정확하게 정리합니다.
2. 회사명·제품명 등 고유명사와 재사용 가치가 있는 일반 전문용어를 구분합니다.
3. 일반 독자가 기사 내용을 이해하기 위해 알아야 할 전문 개념만 최대 5개 고릅니다. 3~5개를 억지로 채우지 말고 적합한 개념이 없으면 0개도 허용합니다.
4. 본문에 없는 사실, 확인되지 않은 승인·임상 결과를 만들지 않습니다.
5. 회사 주장, 전망, 검증된 결과를 구분합니다.
6. 탐색 메뉴·광고·관련 기사 목록은 핵심 근거로 사용하지 않습니다.
7. 약어의 뜻은 본문에 나오거나 명확할 때만 기록하고 추측하지 않습니다.
8. 사진·이미지의 캡션과 이미지 설명문은 기사 주제와 관련되어도 기사 본문 근거나 분석 결과에 포함하지 않습니다.
9. 실제 기사 본문에 쓰인 문장과 문단은 이미지 설명으로 오인해 제외하지 말고 그대로 분석 근거로 사용합니다.
10. 정부부처, 규제기관·의약품청, 병원, 대학, 연구기관 등의 기관명과 약칭·현지어 정식 명칭은 학습 용어에서 제외하고 주요 엔티티로만 기록합니다. 기사와 밀접하게 관련되어도 key_terms에는 넣지 않습니다.
11. 사람 이름, 회사명, 제품·브랜드명, 국가·도시 이름, 해시태그는 학습 용어가 아니라 고유명사·엔티티로 분류합니다. 일반 개념과 혼동하지 않습니다.
12. 일상에서 흔히 쓰고 일반 독자가 바로 이해할 수 있는 표현은 추출하지 않습니다. 예를 들어 가슴 쓰림·속쓰림, 두통, 기침, 발열, 피로, 메스꺼움, 복통 같은 흔한 증상은 용어 목록에서 제외합니다.
13. 질환·증상·검사·치료 표현은 이름만 전문적으로 보인다는 이유로 선택하지 않습니다. 일반 독자에게 낯설고, 이 기사의 핵심 사건이나 연구 결과를 이해하는 데 필요한 경우에만 선택합니다.
14. 우선순위는 작용 기전, 치료 방식, 표적, 바이오마커, 임상 단계·평가변수, 허가 절차, 기술이전·사업 구조처럼 재사용 가치가 있는 개념입니다. 해당 개념이 기사에서 실제로 중요하게 다뤄졌는지도 확인합니다.
15. 기관 이름과 기관이 다루는 개념은 구분합니다. 기관명은 제외하되 임상 단계, 허가 절차, 의약품 후보, 표적, 작용 기전 같은 일반 개념은 용어로 남깁니다.
16. 기사 제목과 부제목은 주제·기업·의약품·키워드를 파악하는 보조 정보입니다. 요약과 분석은 실제 본문을 주요 근거로 사용합니다.
17. 부제목에만 있고 본문에서 확인되지 않는 내용은 검증된 사실처럼 단정하지 않습니다. 부제목을 본문에 복사하거나 본문 문장으로 재구성하지 않습니다.
18. article_questions에는 일반 질문 모드에서 처음 보여줄 기사 맥락 기반 질문을 정확히 2개 작성합니다. 두 질문은 서로 다른 관점(핵심 사건의 의미, 기사 속 기업·기술·전문용어 간 연결 또는 업계 영향)을 다루고, 일반적인 용어 정의 질문은 피합니다.
19. 각 질문에는 실제 본문에서 확인되는 기업명·제품명·전문용어 등 구체적인 단서를 그대로 포함합니다. 부제목에만 나온 정보는 검증된 사실처럼 전제하지 말고, 자연스러운 한국어 질문으로 물음표까지 작성합니다.
"""),
    ("human", "[기사 제목]\n{title}\n\n[부제목 — 주제 파악용 보조 정보, 없으면 비어 있음]\n{subtitle}\n\n[기사 본문 — 요약과 분석의 주요 근거]\n{article}"),
])


def build_article_analysis_chain(model: Any) -> Any:
    return ARTICLE_ANALYSIS_PROMPT | model.with_structured_output(ArticleAnalysis)


MANUAL_TERM_CLASSIFICATION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """사용자가 기사 본문에서 직접 선택한 제약·바이오 용어를 분류하는 튜터입니다.
용어 자체를 분류 대상으로 삼고, 기사 문맥은 의미를 구분하는 근거로 사용합니다. 문맥에 우연히 같이 나온 다른 개념을 분류 근거로 삼지 않습니다.
분류 기준:
- Modality: 치료가 작동하는 큰 방식·형태(예: 세포치료, 유전자치료, 항체약물접합체). 특정 후보약 자체는 Drug입니다.
- Drug: 특정 의약품, 성분, 신약 후보물질 또는 약물 제품.
- Target: 약물이 결합·조절하는 분자 표적, 단백질, 유전자, 수용체, 항원.
- Biomarker: 환자 선별, 질병 상태 또는 치료 반응을 측정·예측하는 생체 지표.
- Disease: 질환이나 질환 아형. 흔한 증상 표현은 전문용어로 분류하지 않습니다.
- Clinical Trial: 임상시험 단계·설계·대상자군·시험 운영 방식.
- Clinical Metric: 평가변수, 반응률, 생존기간, 위험비 등 임상 결과를 측정하는 지표.
- Regulatory: 허가 신청·심사·승인 절차나 규제 경로. 규제기관의 이름만 있으면 기관 엔티티이므로 Other를 사용합니다.
- Business: 기술이전, 라이선스, 판권, 계약금, 마일스톤, 로열티, 제휴·인수 등 사업 거래.
- Manufacturing: 의약품 생산·제조·품질관리·공정·생산 규모 확대.
- Platform: 여러 후보나 연구에 반복 사용하는 신약 발굴·개발 플랫폼.
- Diagnostic: 질환이나 바이오마커를 확인하는 검사·진단법·동반진단.
- Mechanism: 약물·기술이 생물학적 효과를 내는 작용 원리와 경로.
- Technology: 치료 방식·작용 기전·플랫폼에 속하지 않는 구체적 기술·공학 방법.
- Other: 고유명사, 일반 표현, 여러 범주가 가능하지만 문맥 근거가 부족한 용어.
우선순위와 구분:
1. 임상 결과의 수치·평가변수는 Clinical Metric, 시험 단계·설계는 Clinical Trial로 분류합니다.
2. 작용 원리를 나타내면 Mechanism, 그 작용 대상 분자만 가리키면 Target입니다.
3. 치료 방식의 종류는 Modality, 그 방식으로 개발된 특정 약물은 Drug입니다.
4. 거래·허가·생산·진단 용어는 각각 Business·Regulatory·Manufacturing·Diagnostic을 우선합니다.
5. 회사·기관·사람 이름은 Other입니다. 제품 브랜드는 기사에서 의약품·후보물질임이 확인될 때만 Drug로 분류하고, 확인되지 않으면 Other입니다.
분류 근거 evidence는 반드시 제공된 기사 문맥에서 그대로 복사한 짧은 구절이어야 합니다. confidence가 high 또는 medium이면 그 구절이 분류와 용어 의미를 직접 뒷받침해야 합니다. 뒷받침이 부족하면 low로 표시합니다.
정의는 용어와 문맥으로 확인되는 범위에서 한 문장으로 설명합니다. 근거가 불충분하면 추측하지 말고 확인이 어렵다고 씁니다. 별칭은 기사 문맥에서 실제 확인되는 것만 반환합니다."""),
    ("human", "[용어]\n{term}\n\n[기사 유형]\n{article_type}\n\n[용어가 선택된 기사 문맥]\n{article_context}"),
])


def build_manual_term_classification_chain(model: Any) -> Any:
    return MANUAL_TERM_CLASSIFICATION_PROMPT | model.with_structured_output(ManualTermClassificationModelOutput)


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
    text = unicodedata.normalize("NFKC", _organization_text(value))
    return re.sub(r"[^\w]+", "", text, flags=re.UNICODE)


_COMMON_EVERYDAY_TERM_KEYS = {
    _normalized_name(value)
    for value in (
        "가슴 쓰림", "속쓰림", "가슴앓이", "heartburn",
        "두통", "기침", "발열", "열", "피로", "메스꺼움",
        "복통", "구토", "설사", "변비", "콧물", "근육통", "인후통",
    )
}


def _is_common_everyday_term(value: str) -> bool:
    text = str(value or "").strip()
    base_name = re.split(r"[（(\[【]", text, maxsplit=1)[0].strip()
    return any(
        _normalized_name(candidate) in _COMMON_EVERYDAY_TERM_KEYS
        for candidate in (text, base_name)
        if candidate
    )


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


def _filter_key_terms(analysis: ArticleAnalysis) -> ArticleAnalysis:
    organization_aliases: set[str] = set()
    for entity in analysis.key_entities:
        if _looks_like_organization_name(entity):
            organization_aliases.update(_organization_name_variants(entity))

    key_terms = []
    seen_terms = set()
    for term in analysis.key_terms:
        normalized_term = _normalized_name(term.term)
        if (
            not normalized_term
            or _looks_like_organization_name(term.term)
            or _is_common_everyday_term(term.term)
            or (_organization_name_variants(term.term) & organization_aliases)
            or normalized_term in seen_terms
        ):
            continue
        seen_terms.add(normalized_term)
        key_terms.append(term)
    if len(key_terms) == len(analysis.key_terms):
        return analysis
    return analysis.model_copy(update={"key_terms": key_terms})


def _article_question_anchors(analysis: ArticleAnalysis, source: str) -> list[str]:
    source_key = _normalized_name(source)
    candidates = [*analysis.key_entities]
    for term in analysis.key_terms:
        candidates.extend([term.term, *term.aliases])

    anchors: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        anchor = re.sub(r"\s+", " ", str(candidate or "")).strip()
        key = _normalized_name(anchor)
        if len(key) < 2 or key not in source_key or key in seen:
            continue
        seen.add(key)
        anchors.append(anchor)
    return sorted(anchors, key=len, reverse=True)


def _fallback_article_questions(analysis: ArticleAnalysis, source: str) -> list[str]:
    anchors = _article_question_anchors(analysis, source)
    if len(anchors) >= 2:
        return [
            f"기사에서 다룬 ‘{anchors[0]}’의 의미와 중요한 이유는 무엇인가요?",
            f"기사의 핵심 이슈와 ‘{anchors[1]}’의 연결은 무엇인가요?",
        ]
    if anchors:
        return [
            f"기사에서 다룬 ‘{anchors[0]}’의 의미와 중요한 이유는 무엇인가요?",
            f"기사의 핵심 이슈와 ‘{anchors[0]}’의 연결은 무엇인가요?",
        ]
    return [
        "기사에서 다룬 핵심 변화의 배경은 무엇인가요?",
        "이 기사의 핵심 이슈가 업계에 주는 의미는 무엇인가요?",
    ]


def validate_article_questions(analysis: ArticleAnalysis, source: str) -> list[str]:
    """질문 수·형식·중복·기사 내 단서를 확인하고 실패 시 근거 기반 질문을 만듭니다."""
    anchors = _article_question_anchors(analysis, source)
    questions = analysis.article_questions
    if len(questions) != 2 or not anchors:
        return _fallback_article_questions(analysis, source)

    cleaned: list[str] = []
    seen: set[str] = set()
    anchor_keys = [_normalized_name(anchor) for anchor in anchors]
    for raw_question in questions:
        question = re.sub(r"\s+", " ", str(raw_question or "")).strip()
        question = re.sub(r"^(?:[-*•]\s*|\d+[.)]\s*)", "", question)
        if not 8 <= len(question) <= 160 or not question.endswith(("?", "？")):
            return _fallback_article_questions(analysis, source)
        key = _normalized_name(question)
        if not key or key in seen or not any(anchor in key for anchor in anchor_keys):
            return _fallback_article_questions(analysis, source)
        seen.add(key)
        cleaned.append(question)
    return cleaned


_MANUAL_TERM_CATEGORY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Clinical Metric", re.compile(
        r"(?<![A-Za-z])(?:PFS|OS|ORR|EFS|DFS|DOR|mOS|HR|CI)(?![A-Za-z])|"
        r"평가변수|반응률|생존기간|위험비|유효성 지표|객관적 반응", re.IGNORECASE,
    )),
    ("Clinical Trial", re.compile(
        r"임상\s*(?:시험\s*)?[1-4]\s*상?|(?:^|\s)[1-4]\s*상(?:$|\s)|phase\s*[1-4]|임상시험|무작위\s*대조|"
        r"코호트|용량.?증량|대조군", re.IGNORECASE,
    )),
    ("Regulatory", re.compile(
        r"(?<![A-Za-z])(?:IND|NDA|BLA)(?![A-Za-z])|품목.?허가|시판.?허가|"
        r"허가.?신청|허가.?심사|규제.?경로|신속.?심사|승인 절차", re.IGNORECASE,
    )),
    ("Business", re.compile(
        r"기술.?이전|라이선스|계약금|마일스톤|로열티|판권|제휴|인수.?합병|상업화|사업.?개발|공동.?개발",
        re.IGNORECASE,
    )),
    ("Manufacturing", re.compile(
        r"(?<![A-Za-z])(?:GMP|CMO|CDMO)(?![A-Za-z])|생산|제조|배양.?공정|품질.?관리|스케일.?업",
        re.IGNORECASE,
    )),
    ("Diagnostic", re.compile(
        r"동반.?진단|진단.?키트|진단법|진단.?검사|검사법|진단.?기술", re.IGNORECASE,
    )),
    ("Biomarker", re.compile(
        r"바이오.?마커|biomarker|발현.?량|돌연변이|유전자.?변이|PD-L1|HER2|MSI-H|TMB",
        re.IGNORECASE,
    )),
    ("Mechanism", re.compile(
        r"작용.?기전|기전|분해.?유도|억제.?작용|활성화.?경로|신호.?전달|분해.?경로",
        re.IGNORECASE,
    )),
    ("Modality", re.compile(
        r"CAR.?T|항체.?약물.?접합체|ADC|mRNA|siRNA|ASO|세포.?치료|유전자.?치료|"
        r"방사성.?의약품|단일.?클론.?항체", re.IGNORECASE,
    )),
    ("Platform", re.compile(r"플랫폼|platform|발굴.?플랫폼|개발.?플랫폼", re.IGNORECASE)),
    ("Target", re.compile(
        r"표적|타깃|target|수용체|항원|단백질|유전자|EGFR|PD-1|KRAS|BRAF", re.IGNORECASE,
    )),
    ("Disease", re.compile(
        r"(?:폐|유방|위|간|췌장|대장|직장|전립선|난소|혈액|식도|두경부|소세포|비소세포)암|암종|"
        r"질환|증후군|폐섬유증|신경퇴행|자가면역|백혈병|림프종|흑색종|당뇨병|비만",
        re.IGNORECASE,
    )),
    ("Drug", re.compile(
        r"후보물질|신약|치료제|의약품|약물|약제|억제제|저해제|바이오시밀러|유효성분|화합물|성분|"
        r"antagonist|inhibitor|agonist", re.IGNORECASE,
    )),
    ("Technology", re.compile(
        r"기술|알고리즘|시퀀싱|인공지능|CRISPR|나노입자|전달체|유전자.?편집", re.IGNORECASE,
    )),
)

_MANUAL_TERM_FALLBACK_DEFINITIONS = {
    "Modality": "치료에 사용하는 방식이나 형태를 설명하는 용어입니다.",
    "Drug": "특정 의약품이나 개발 중인 약물 후보를 가리키는 용어입니다.",
    "Target": "약물이나 치료 기술이 작용하도록 겨냥하는 분자입니다.",
    "Biomarker": "질병 상태나 치료 반응을 측정·예측하는 생체 지표입니다.",
    "Disease": "기사에서 다루는 질환 또는 질환의 하위 유형입니다.",
    "Clinical Trial": "임상시험의 단계, 설계, 대상자 또는 진행 방식을 설명합니다.",
    "Clinical Metric": "임상시험에서 효과나 안전성 결과를 측정하는 지표입니다.",
    "Regulatory": "의약품의 허가 신청, 심사, 승인과 관련된 절차나 기준입니다.",
    "Business": "의약품 개발·판매와 관련된 계약이나 사업 거래를 뜻합니다.",
    "Manufacturing": "의약품의 생산, 제조 공정 또는 품질 관리와 관련된 용어입니다.",
    "Platform": "여러 후보나 연구에 반복해서 활용하는 기술 기반 체계입니다.",
    "Diagnostic": "질환이나 생체 지표를 확인하는 검사 또는 진단 방법입니다.",
    "Mechanism": "약물이나 기술이 생물학적 효과를 내는 작동 원리입니다.",
    "Technology": "치료 방식·작용 기전·플랫폼 외의 구체적인 기술 방법입니다.",
    "Other": "기사 문맥만으로 전문 범주를 확정하기 어려워 추가 확인이 필요한 용어입니다.",
}


def _fallback_manual_term_classification(term: str) -> tuple[str, str, str]:
    for category, pattern in _MANUAL_TERM_CATEGORY_RULES:
        match = pattern.search(term)
        if match:
            evidence = match.group(0)
            reason = f"선택한 용어의 ‘{evidence}’ 표현을 기준으로 {category}로 분류했습니다."
            return category, reason, _MANUAL_TERM_FALLBACK_DEFINITIONS[category]

    reason = "용어는 목록에 추가하되, 기사 문맥만으로 전문 범주를 확인하기 어려워 기타로 분류했습니다."
    return "Other", reason, _MANUAL_TERM_FALLBACK_DEFINITIONS["Other"]


def analyze_article(
    chain: Any,
    article: str,
    title: str = "",
    subtitle: str = "",
) -> ArticleAnalysis:
    if not article or not article.strip():
        raise ValueError("분석할 기사 본문이 없습니다.")
    source = article[:14000]
    analysis = chain.invoke({
        "article": source,
        "title": title.strip()[:500],
        "subtitle": subtitle.strip()[:1000],
    })
    analysis = _filter_key_terms(analysis)
    questions = validate_article_questions(analysis, source)
    return analysis.model_copy(update={"article_questions": questions})


def classify_manual_term(chain: Any, term: str, article_context: str, article_type: str) -> PharmaTerm:
    clean_term = term.strip()
    clean_context = article_context.strip()[:1000]
    result = chain.invoke({
        "term": clean_term,
        "article_context": clean_context,
        "article_type": article_type.strip()[:80],
    })
    normalized_evidence = _normalized_name(result.evidence)
    normalized_context = _normalized_name(clean_context)
    evidence_supported = bool(normalized_evidence and normalized_evidence in normalized_context)
    if result.confidence == "low" or not evidence_supported:
        category, reason, definition = _fallback_manual_term_classification(clean_term)
        aliases = []
    else:
        category = result.category
        reason = result.reason
        definition = result.simple_definition
        context_keys = {_normalized_name(clean_term), normalized_context}
        aliases = [
            alias for alias in result.aliases
            if _normalized_name(alias) and any(_normalized_name(alias) in key for key in context_keys)
        ]
    return PharmaTerm(
        term=clean_term,
        category=category,
        reason=reason,
        simple_definition=definition,
        article_context=clean_context,
        aliases=aliases,
    )
