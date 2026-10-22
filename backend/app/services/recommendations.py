"""맥락과 학습 목표를 반영한 다음 질문 추천."""
from __future__ import annotations

import re
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field, ValidationError
from langchain_core.prompts import ChatPromptTemplate


LEARNING_CATEGORIES = (
    "원리 심화",
    "다른 개념과 연결",
    "한계·응용 탐구",
)


class LearningQuestion(BaseModel):
    category: Literal["원리 심화", "다른 개념과 연결", "한계·응용 탐구"]
    question: str = Field(min_length=5, max_length=160)
    learning_goal: str = Field(min_length=3, max_length=80)


class LearningQuestionSet(BaseModel):
    recommendations: list[LearningQuestion] = Field(min_length=3, max_length=3)


class LearningTurnResponse(BaseModel):
    answer: str = Field(min_length=1)
    recommendations: list[LearningQuestion] = Field(min_length=3, max_length=3)


def _clean(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _question_key(value: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", "", value.casefold())


def fallback_recommendations(
    term: str = "",
    question: str = "",
    answer: str = "",
) -> list[dict[str, str]]:
    """Keep useful recommendations available when generation fails."""
    topic = _clean(term, 48)
    if question.strip() or answer.strip():
        followup_topic = topic or "개념"
        return [
            {
                "category": "원리 심화",
                "question": f"방금 답변에서 설명한 {followup_topic}의 원인과 결과를 단계별로 다시 정리해줘.",
                "learning_goal": "직전 답변의 인과 흐름을 더 분명히 이해합니다.",
            },
            {
                "category": "다른 개념과 연결",
                "question": f"방금 설명한 {followup_topic}와 가장 비슷한 개념은 무엇이고, 핵심 차이는 뭐야?",
                "learning_goal": "직전 답변의 개념을 유사 개념과 비교합니다.",
            },
            {
                "category": "한계·응용 탐구",
                "question": "방금 설명에서 기사로 확인된 내용과 일반 배경지식은 각각 어디까지야?",
                "learning_goal": "직전 설명의 근거와 적용 범위를 구분합니다.",
            },
        ]
    topic = topic or "방금 답변에서 다룬 내용"
    return [
        {
            "category": "원리 심화",
            "question": f"{topic}의 핵심 작동 원리는 어떤 단계로 진행돼?",
            "learning_goal": "핵심 작동 원리를 이해합니다.",
        },
        {
            "category": "다른 개념과 연결",
            "question": f"{topic}와 관련된 다른 제약·바이오 개념은 무엇이고 어떻게 달라?",
            "learning_goal": "비슷한 개념의 차이와 연결점을 찾습니다.",
        },
        {
            "category": "한계·응용 탐구",
            "question": f"{topic}의 실제 임상이나 산업 적용에서 어떤 한계가 있어?",
            "learning_goal": "실제 적용 맥락과 한계를 살펴봅니다.",
        },
    ]


def insufficient_evidence_recommendations(term: str = "") -> list[dict[str, str]]:
    """Provide next steps that do not assume unsupported facts are true."""
    topic = _clean(term, 48)
    if topic:
        principle_question = (
            f"{topic}의 일반적으로 알려진 원리와 현재 자료에서 확인된 사실을 구분해서 설명해줘."
        )
        source_question = (
            f"질문한 {topic}: 관련 개념과 공식 자료에서 어떤 점을 확인해 볼 수 있어?"
        )
    else:
        principle_question = (
            "이 질문과 관련된 일반 개념과 현재 자료에서 확인된 사실을 구분해서 설명해줘."
        )
        source_question = (
            "이 질문을 이해하거나 검증하는 데 도움이 되는 관련 개념과 공식 자료는 무엇이야?"
        )
    return [
        {
            "category": "원리 심화",
            "question": principle_question,
            "learning_goal": "일반 개념과 이 자료에서 확인된 사실을 구분합니다.",
        },
        {
            "category": "다른 개념과 연결",
            "question": source_question,
            "learning_goal": "주장을 검증할 출처와 확인 항목을 찾습니다.",
        },
        {
            "category": "한계·응용 탐구",
            "question": "현재 기사·학습 기록에서 확인된 내용과 추가 근거가 필요한 부분을 나눠줘.",
            "learning_goal": "확인된 정보와 미확인 정보를 구분합니다.",
        },
    ]


def build_recommendation_generator(model: Any) -> Callable[[dict[str, Any]], Any]:
    """같은 구조화 추천 프롬프트를 Gradio와 실험 CLI에서 사용합니다."""
    prompt = ChatPromptTemplate.from_messages([
        ("system", """당신은 제약·바이오 학습 튜터입니다. 직전 질문과 답변, 저장된 학습 메모를 바탕으로 다음 학습 질문 3개를 만드세요.
규칙:
- 출력은 원리 심화, 다른 개념과 연결, 한계·응용 탐구 각 1개씩 정확히 3개입니다.
- 각 질문은 초보자가 이해하기 쉬운 한국어로 쓰고, 직전 답변에서 다루지 않은 다음 학습 단계로 이어지게 합니다.
- 이미 나온 질문을 반복하지 않습니다. 현재 자료와 저장 메모에 근거해 질문을 만듭니다.
- 최신 승인·임상 결과, 개인 치료 조언이나 근거 없는 수치를 전제하지 않습니다.
- 각 항목에 학습 목표를 한 문장으로 적습니다."""),
        ("human", """선택 용어: {term}
직전 질문: {question}
직전 답변: {answer}
최근 관련 Q&A: {history}
저장 학습 메모: {saved_note}"""),
    ])
    chain = prompt | model.with_structured_output(LearningQuestionSet)
    return chain.invoke


def _validate_generated(raw: Any, prior_questions: list[str]) -> list[dict[str, str]]:
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    result = LearningQuestionSet.model_validate(raw)
    by_category = {item.category: item for item in result.recommendations}
    if len(by_category) != len(LEARNING_CATEGORIES):
        raise ValueError("세 추천 질문의 학습 범주가 서로 달라야 합니다.")

    prior = {_question_key(question) for question in prior_questions if question.strip()}
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for category in LEARNING_CATEGORIES:
        item = by_category[category]
        question = _clean(item.question, 160)
        key = _question_key(question)
        if not key or key in seen or key in prior:
            raise ValueError("이미 나온 질문 또는 중복 질문은 추천할 수 없습니다.")
        seen.add(key)
        normalized.append({
            "category": category,
            "question": question,
            "learning_goal": _clean(item.learning_goal, 80),
        })
    return normalized


def recommend_learning_questions(
    generator: Callable[[dict[str, Any]], Any] | None,
    *,
    term: str = "",
    question: str = "",
    answer: str = "",
    history: list[dict[str, str]] | None = None,
    saved_note: str = "",
) -> list[dict[str, str]]:
    """직전 Q&A와 학습 메모로 질문 3개를 생성하고, 오류 시 안전한 기본값을 씁니다."""
    history = history or []
    prior_questions = [
        _clean(item.get("question"), 300)
        for item in history[-8:]
        if item.get("question")
    ]
    current_question = _clean(question, 500)
    if current_question:
        prior_questions.append(current_question)

    fallback = fallback_recommendations(term, current_question, answer)
    if generator is None:
        return fallback

    payload = {
        "term": _clean(term, 120),
        "question": current_question,
        "answer": _clean(answer, 3000),
        "history": [
            {
                "question": _clean(item.get("question"), 300),
                "answer": _clean(item.get("answer"), 1200),
            }
            for item in history[-5:]
        ],
        "saved_note": _clean(saved_note, 1800),
    }
    try:
        return _validate_generated(generator(payload), prior_questions)
    except (ValidationError, TypeError, ValueError, KeyError, RuntimeError):
        return fallback
    except Exception:
        # 외부 LLM 클라이언트의 장애도 추천 실패로 국소 처리합니다.
        return fallback


def render_recommendations(recommendations: list[dict[str, str]]) -> str:
    lines = ["**다음 학습 방향**"]
    for item in recommendations:
        category = _clean(item.get("category"), 40).replace("|", "\\|")
        goal = _clean(item.get("learning_goal"), 80).replace("|", "\\|")
        question = _clean(item.get("question"), 160).replace("|", "\\|")
        lines.append(f"- **{category}** · {goal}  \n  질문: {question}")
    return "\n".join(lines)
