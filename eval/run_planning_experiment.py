"""Compare the current composite route with adding a separate LLM planner."""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from backend.app.agents.graph import RouteDecision
from backend.app.core.config import load_settings


CASES = ROOT / "eval" / "planning_cases.jsonl"
ROUTER_SYSTEM = """당신은 제약·바이오 학습 요청의 검색 경로만 고르는 라우터입니다. 질문에 필요한 출처를 최소한으로 선택하세요.
article: 사용자가 현재 제공한 기사나 일반 개념만으로 답할 수 있는 질문.
memory: 질문이 사용자의 과거 노트, 저장 기록, 이전 Q&A를 명시적으로 요구하지만 최신 사실은 요구하지 않는 경우.
web: 최신/현재/오늘/최근 사실, 승인·규제·임상 결과를 검색해야 하고 과거 개인 기록 비교는 요구하지 않는 경우.
memory_web: 과거에 저장된 학습 내용과 최신 외부 사실을 둘 다 명시적으로 찾아 비교하거나 연결해야 하는 경우.
우선순위: 과거 기록+최신 사실 모두 필요하면 memory_web; 최신 사실만 필요하면 web; 과거 저장 기록만 필요하면 memory; 나머지는 article.
최신성이 명시되지 않은 일반 개념 질문에 web을 선택하지 마세요. 선택 용어는 질문 범위를 제한하지 않습니다.
related_to_selected는 질문이 현재 선택 용어에 실제로 관련된 경우에만 True입니다.
검색어를 작성할 때 자료에 없는 약물명·회사명·날짜를 추측하지 마세요."""


class PlanStep(BaseModel):
    task: Literal["memory", "web"]
    goal: str = Field(description="이 작업이 답변에 필요한 이유")


class CompositePlan(BaseModel):
    steps: list[PlanStep] = Field(description="질문을 해결하기 위한 필요한 검색 작업")


def read_cases() -> list[dict]:
    return [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]


def summarize(label: str, rows: list[dict], call_counts: list[int]) -> dict:
    latencies = [row["latency_ms"] for row in rows]
    return {
        "condition": label,
        "cases": len(rows),
        "exact_task_coverage": sum(row["correct"] for row in rows),
        "accuracy": round(sum(row["correct"] for row in rows) / max(1, len(rows)), 4),
        "p50_latency_ms": round(statistics.median(latencies), 2),
        "total_calls": sum(call_counts),
        "total_input_tokens": sum(row["input_tokens"] for row in rows),
        "total_output_tokens": sum(row["output_tokens"] for row in rows),
        "errors": [row for row in rows if not row["correct"]],
        "outcomes": rows,
    }


def main() -> None:
    settings = load_settings(ROOT)
    model = ChatOpenAI(api_key=settings.openai_api_key, model=settings.model_name, temperature=0, max_retries=2)
    route_chain = ChatPromptTemplate.from_messages([
        ("system", ROUTER_SYSTEM), ("human", "[선택한 용어] {term}\n[이전 대화] {history}\n[질문] {question}"),
    ]) | model.with_structured_output(RouteDecision, include_raw=True)
    plan_chain = ChatPromptTemplate.from_messages([
        ("system", """당신은 복합 질문을 풀 검색 작업으로 나누는 Planner입니다.
질문에 과거 학습 기록과 최신 외부 사실이 모두 명시되어 있으면 memory 작업과 web 작업을 각각 하나씩 계획합니다.
과거 기록은 사용자의 저장 노트·이전 Q&A에서 검색하고, 최신 정보는 외부 웹에서 검색합니다.
두 작업은 서로 독립적이므로 필요한 두 작업만 포함하세요. 기사나 일반 설명만 필요한 불필요한 작업을 추가하지 마세요.
질문에 없는 후보물질·회사·날짜는 가정하지 마세요."""),
        ("human", "복합 질문: {question}"),
    ]) | model.with_structured_output(CompositePlan, include_raw=True)
    baseline_rows, candidate_rows, call_counts = [], [], []
    for case in read_cases():
        start = time.perf_counter()
        base = route_chain.invoke({"question": case["question"], "term": "", "history": ""})
        baseline_ms = (time.perf_counter() - start) * 1000
        base_route = base["parsed"].route if base.get("parsed") else "parse_error"
        expected = {"memory", "web"}
        base_tasks = expected if base_route == "memory_web" else ({base_route} if base_route in expected else set())
        base_usage = getattr(base.get("raw"), "usage_metadata", None) or {}
        baseline_rows.append({
            "id": case["id"], "expected": sorted(expected), "actual": sorted(base_tasks),
            "correct": base_tasks == expected, "latency_ms": round(baseline_ms, 2),
            "input_tokens": int(base_usage.get("input_tokens", 0)),
            "output_tokens": int(base_usage.get("output_tokens", 0)),
        })

        start = time.perf_counter()
        route = route_chain.invoke({"question": case["question"], "term": "", "history": ""})
        plan = plan_chain.invoke({"question": case["question"]}) if route.get("parsed") and route["parsed"].route == "memory_web" else None
        candidate_ms = (time.perf_counter() - start) * 1000
        candidate_tasks = {step.task for step in plan["parsed"].steps} if plan and plan.get("parsed") else set()
        route_usage = getattr(route.get("raw"), "usage_metadata", None) or {}
        plan_usage = getattr(plan.get("raw"), "usage_metadata", None) or {} if plan else {}
        candidate_rows.append({
            "id": case["id"], "expected": sorted(expected), "actual": sorted(candidate_tasks),
            "correct": candidate_tasks == expected, "latency_ms": round(candidate_ms, 2),
            "input_tokens": int(route_usage.get("input_tokens", 0)) + int(plan_usage.get("input_tokens", 0)),
            "output_tokens": int(route_usage.get("output_tokens", 0)) + int(plan_usage.get("output_tokens", 0)),
        })
        call_counts.append(1 + int(plan is not None))

    results = {
        "model": settings.model_name,
        "temperature": 0,
        "repeat_count": 1,
        "case_count": len(baseline_rows),
        "baseline": summarize("current_memory_web_route", baseline_rows, [1] * len(baseline_rows)),
        "candidate": summarize("router_plus_dynamic_planner", candidate_rows, call_counts),
    }
    output = ROOT / "eval" / "results" / "planning_latest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name in ("baseline", "candidate"):
        item = results[name]
        print(
            f"{item['condition']}: exact task coverage={item['exact_task_coverage']}/{item['cases']}, "
            f"p50={item['p50_latency_ms']:.0f}ms, calls={item['total_calls']}, "
            f"tokens={item['total_input_tokens']}+{item['total_output_tokens']}"
        )
        if item["errors"]:
            print("  errors=" + ", ".join(f"{row['id']}:{row['actual']}" for row in item["errors"]))
    print("Raw fixture results: eval/results/planning_latest.json")


if __name__ == "__main__":
    main()
