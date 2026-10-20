from __future__ import annotations

import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langchain_community.callbacks.manager import get_openai_callback
from langchain_openai import ChatOpenAI

from backend.app.core.config import load_settings
from backend.app.services.recommendations import (
    build_recommendation_generator,
    fallback_recommendations,
    recommend_learning_questions,
)


def load_cases() -> list[dict[str, Any]]:
    with (ROOT / "eval" / "recommendation_cases.jsonl").open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def static_baseline(term: str) -> list[str]:
    if not term:
        return [
            "이 기사에서 중요한 개념을 쉬운 말로 설명해줘.",
            "제약·바이오 산업에서 자주 쓰이는 용어를 알려줘.",
            "최근 제약·바이오 분야에서 어떤 이슈를 봐야 해?",
        ]
    return [
        f"{term}라는 개념을 일상생활 비유로 아주 쉽게 설명해줘.",
        f"지금 읽는 기사에서 {term}가 중요한 이유가 뭐야?",
        f"{term}와 혼동하기 쉬운 다른 개념은 무엇이고 차이는 뭐야?",
    ]


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
    generator = build_recommendation_generator(model)
    rows: list[dict[str, Any]] = []
    candidate_latencies: list[float] = []
    baseline_latencies: list[float] = []
    total_tokens = 0
    total_cost = 0.0

    print(f"질문 추천 실험 | model={settings.model_name} | temperature=0.2 | synthetic_cases=4")
    for case in load_cases():
        start = time.perf_counter()
        baseline = static_baseline(case["term"])
        baseline_seconds = time.perf_counter() - start

        with get_openai_callback() as callback:
            start = time.perf_counter()
            candidate = recommend_learning_questions(
                generator,
                term=case["term"],
                question=case["question"],
                answer=case["answer"],
                history=case.get("history", []),
                saved_note=case.get("saved_note", ""),
            )
            candidate_seconds = time.perf_counter() - start

        total_tokens += callback.total_tokens
        total_cost += callback.total_cost
        baseline_latencies.append(baseline_seconds)
        candidate_latencies.append(candidate_seconds)
        row = {
            "case_id": case["case_id"],
            "term": case["term"],
            "question": case["question"],
            "baseline": baseline,
            "candidate": candidate,
            "candidate_latency_seconds": round(candidate_seconds, 4),
            "baseline_latency_seconds": round(baseline_seconds, 6),
            "candidate_tokens": callback.total_tokens,
            "candidate_cost_usd": callback.total_cost,
            "used_fallback": candidate == fallback_recommendations(case["term"]),
        }
        rows.append(row)
        print(f"\n[{case['case_id']}] 기준선: " + " | ".join(baseline))
        for item in candidate:
            print(f"  {item['category']} · {item['learning_goal']}\n    {item['question']}")
        print(f"  지연: {candidate_seconds:.2f}s | 토큰: {callback.total_tokens} | 비용(USD): {callback.total_cost:.6f}")

    result_path = ROOT / "eval" / "results" / "recommendations_latest.jsonl"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    with result_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print("\n요약")
    print(f"  기준선 계산 p50/p95: {statistics.median(baseline_latencies):.6f}s / {percentile(baseline_latencies, 0.95):.6f}s")
    print(f"  후보 추천 p50/p95: {statistics.median(candidate_latencies):.2f}s / {percentile(candidate_latencies, 0.95):.2f}s")
    print(f"  후보 총 토큰 / 비용(USD): {total_tokens} / {total_cost:.6f}")
    print(f"  원자료(로컬 전용): {result_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
