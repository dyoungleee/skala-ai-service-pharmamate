"""Compare the current query router prompt with a focused routing prompt."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from backend.app.agents.graph import RouteDecision
from backend.app.core.config import load_settings


CASES = ROOT / "eval" / "routing_cases.jsonl"
CURRENT_SYSTEM = """당신은 제약·바이오 학습 Agent의 Tool 라우터입니다.
article: 현재 기사에 대한 질문 또는 일반 개념 설명 (기사가 없는 경우도 포함)
memory: 이전에 공부한 용어나 나의 학습 기록 관련 질문
web: 최근/현재/최신 업계 동향, 최근 승인·임상 정보 검증이 필요한 질문
memory_web: 이전에 학습한 내용과 현재 업계 동향을 함께 비교하는 질문
현재 선택한 용어와 무관한 다른 제약·바이오 용어도 자유롭게 질문할 수 있습니다.
선택 용어는 선택적 참고 맥락이지 질문 범위를 제한하는 명령이 아닙니다.
related_to_selected는 현재 선택한 용어에 대한 질문 또는 그에 대한 명확한 후속 질문일 때만 True로 설정합니다.
질문에 다른 용어만 등장하면 False로 설정합니다. 선택된 용어가 없으면 False입니다.
사용자의 최신성 의도가 명확하지 않으면 불필요하게 웹 검색하지 않습니다.
검색어는 질문을 실제로 해결할 수 있도록 구체적으로 씁니다. 날짜·약물·회사명을 모르면 임의로 만들지 않습니다."""
FOCUSED_SYSTEM = """당신은 제약·바이오 학습 요청의 검색 경로만 고르는 라우터입니다. 질문에 필요한 출처를 최소한으로 선택하세요.
article: 사용자가 현재 제공한 기사나 일반 개념만으로 답할 수 있는 질문.
memory: 질문이 사용자의 과거 노트, 저장 기록, 이전 Q&A를 명시적으로 요구하지만 최신 사실은 요구하지 않는 경우.
web: 최신/현재/오늘/최근 사실, 승인·규제·임상 결과를 검색해야 하고 과거 개인 기록 비교는 요구하지 않는 경우.
memory_web: 과거에 저장된 학습 내용과 최신 외부 사실을 둘 다 명시적으로 찾아 비교하거나 연결해야 하는 경우.
우선순위: 과거 기록+최신 사실 모두 필요하면 memory_web; 최신 사실만 필요하면 web; 과거 저장 기록만 필요하면 memory; 나머지는 article.
최신성이 명시되지 않은 일반 개념 질문에 web을 선택하지 마세요. 선택 용어는 질문 범위를 제한하지 않습니다.
related_to_selected는 질문이 현재 선택 용어에 실제로 관련된 경우에만 True입니다.
검색어를 작성할 때 자료에 없는 약물명·회사명·날짜를 추측하지 마세요."""
HUMAN = "[선택한 용어] {term}\n[이전 대화] {history}\n[질문] {question}"


def load_cases() -> list[dict]:
    return [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_condition(model: ChatOpenAI, cases: list[dict], system: str, label: str) -> dict:
    chain = ChatPromptTemplate.from_messages([("system", system), ("human", HUMAN)]) | model.with_structured_output(
        RouteDecision, include_raw=True
    )
    outcomes = []
    for case in cases:
        started = time.perf_counter()
        result = chain.invoke({"term": case["term"], "history": "", "question": case["question"]})
        elapsed_ms = (time.perf_counter() - started) * 1000
        parsed = result.get("parsed")
        raw = result.get("raw")
        usage = getattr(raw, "usage_metadata", None) or {}
        route = parsed.route if parsed else "parse_error"
        outcomes.append({
            "id": case["id"], "expected": case["expected_route"], "actual": route,
            "correct": route == case["expected_route"], "latency_ms": round(elapsed_ms, 2),
            "input_tokens": int(usage.get("input_tokens", 0)),
            "output_tokens": int(usage.get("output_tokens", 0)),
        })
    latencies = [item["latency_ms"] for item in outcomes]
    return {
        "condition": label,
        "cases": len(outcomes),
        "correct": sum(item["correct"] for item in outcomes),
        "accuracy": round(sum(item["correct"] for item in outcomes) / max(1, len(outcomes)), 4),
        "p50_latency_ms": round(statistics.median(latencies), 2),
        "total_input_tokens": sum(item["input_tokens"] for item in outcomes),
        "total_output_tokens": sum(item["output_tokens"] for item in outcomes),
        "errors": [item for item in outcomes if not item["correct"]],
        "outcomes": outcomes,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "eval" / "results" / "routing_latest.json")
    args = parser.parse_args()
    settings = load_settings(ROOT)
    model = ChatOpenAI(
        api_key=settings.openai_api_key,
        model=settings.model_name,
        temperature=0,
        max_retries=2,
    )
    cases = load_cases()
    results = {
        "model": settings.model_name,
        "temperature": 0,
        "repeat_count": 1,
        "case_count": len(cases),
        "baseline": run_condition(model, cases, CURRENT_SYSTEM, "current_agent_router"),
        "candidate": run_condition(model, cases, FOCUSED_SYSTEM, "focused_routing_prompt"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name in ("baseline", "candidate"):
        item = results[name]
        print(
            f"{item['condition']}: accuracy={item['accuracy']:.3f} "
            f"({item['correct']}/{item['cases']}), p50={item['p50_latency_ms']:.0f}ms, "
            f"tokens={item['total_input_tokens']}+{item['total_output_tokens']}"
        )
        if item["errors"]:
            print("  errors=" + ", ".join(f"{e['id']}:{e['expected']}→{e['actual']}" for e in item["errors"]))
    print(f"Raw fixture results: {args.output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
