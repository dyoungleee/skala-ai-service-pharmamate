from __future__ import annotations

import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from langchain_community.callbacks.manager import get_openai_callback
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import load_settings
from backend.app.services.recommendations import (
    LearningQuestion,
    build_recommendation_generator,
    recommend_learning_questions,
)
from eval.run_recommendation_experiment import load_cases


class AnswerOnly(BaseModel):
    answer: str


class CombinedTurn(BaseModel):
    answer: str
    recommendations: list[LearningQuestion] = Field(min_length=3, max_length=3)


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p * len(ordered)) - 1)]


def main() -> int:
    settings = load_settings(ROOT)
    model = ChatOpenAI(
        model=settings.model_name,
        temperature=0.2,
        timeout=45,
        max_retries=1,
        api_key=settings.openai_api_key,
    )
    separate_answer_prompt = ChatPromptTemplate.from_messages([
        ("system", """당신은 제약·바이오 학습 튜터입니다. 제공 근거 안에서 초보자가 이해하기 쉬운 한국어로 질문에 답하세요. 근거 밖 임상 결과·수치·치료 조언은 만들지 마세요."""),
        ("human", """용어: {term}
질문: {question}
제공 근거: {answer}
최근 Q&A: {history}
저장 메모: {saved_note}"""),
    ])
    combined_prompt = ChatPromptTemplate.from_messages([
        ("system", """당신은 제약·바이오 학습 튜터입니다. 제공 근거 안에서 초보자가 이해하기 쉬운 답변과 다음 학습 질문을 함께 작성하세요.
답변에는 근거 밖 임상 결과·수치·치료 조언을 넣지 마세요. 추천은 원리 심화, 다른 개념과 연결, 한계·응용 탐구를 하나씩 만듭니다. 질문은 답변·근거·메모와 관련되어야 하며, 이미 나온 질문과 최신 정보 요청을 만들지 마세요."""),
        ("human", """용어: {term}
질문: {question}
제공 근거: {answer}
최근 Q&A: {history}
저장 메모: {saved_note}"""),
    ])
    separate_answer_chain = separate_answer_prompt | model.with_structured_output(AnswerOnly)
    combined_chain = combined_prompt | model.with_structured_output(CombinedTurn)
    recommendation_generator = build_recommendation_generator(model)
    separate_times: list[float] = []
    combined_times: list[float] = []
    separate_tokens = combined_tokens = 0
    separate_cost = combined_cost = 0.0
    rows: list[dict[str, Any]] = []

    print(f"추천 생성 방식 비교 | model={settings.model_name} | temperature=0.2 | synthetic_cases=4")
    for case in load_cases():
        payload = {
            "term": case["term"],
            "question": case["question"],
            "answer": case["answer"],
            "history": case.get("history", []),
            "saved_note": case.get("saved_note", ""),
        }
        with get_openai_callback() as callback:
            started = time.perf_counter()
            answer = separate_answer_chain.invoke(payload).answer
            recs = recommend_learning_questions(
                recommendation_generator,
                term=case["term"],
                question=case["question"],
                answer=answer,
                history=case.get("history", []),
                saved_note=case.get("saved_note", ""),
            )
            separate_seconds = time.perf_counter() - started
        separate_case_tokens, separate_case_cost = callback.total_tokens, callback.total_cost

        with get_openai_callback() as callback:
            started = time.perf_counter()
            combined = combined_chain.invoke(payload)
            combined_seconds = time.perf_counter() - started
        combined_case_tokens, combined_case_cost = callback.total_tokens, callback.total_cost

        separate_times.append(separate_seconds)
        combined_times.append(combined_seconds)
        separate_tokens += separate_case_tokens
        combined_tokens += combined_case_tokens
        separate_cost += separate_case_cost
        combined_cost += combined_case_cost
        row = {
            "case_id": case["case_id"],
            "separate": {
                "answer": answer,
                "recommendations": recs,
                "latency_seconds": round(separate_seconds, 4),
                "tokens": separate_case_tokens,
                "cost_usd": separate_case_cost,
            },
            "combined": {
                "answer": combined.answer,
                "recommendations": [item.model_dump() for item in combined.recommendations],
                "latency_seconds": round(combined_seconds, 4),
                "tokens": combined_case_tokens,
                "cost_usd": combined_case_cost,
            },
        }
        rows.append(row)
        print(f"\n[{case['case_id']}] 분리: {separate_seconds:.2f}s, {separate_case_tokens} tokens, ${separate_case_cost:.6f}")
        print(f"  답변: {answer}")
        for item in recs:
            print(f"  {item['category']}: {item['question']}")
        print(f"  통합: {combined_seconds:.2f}s, {combined_case_tokens} tokens, ${combined_case_cost:.6f}")
        print(f"  답변: {combined.answer}")
        for item in combined.recommendations:
            print(f"  {item.category}: {item.question}")

    result_path = ROOT / "eval" / "results" / "recommendation_strategy_latest.jsonl"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    with result_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print("\n요약 (4회, p95는 표본 내 최댓값)")
    print(f"  분리 답변+추천 p50/p95: {statistics.median(separate_times):.2f}s / {percentile(separate_times, 0.95):.2f}s")
    print(f"  통합 답변+추천 p50/p95: {statistics.median(combined_times):.2f}s / {percentile(combined_times, 0.95):.2f}s")
    print(f"  분리 총 토큰/비용(USD): {separate_tokens} / {separate_cost:.6f}")
    print(f"  통합 총 토큰/비용(USD): {combined_tokens} / {combined_cost:.6f}")
    print(f"  원자료(로컬 전용): {result_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
