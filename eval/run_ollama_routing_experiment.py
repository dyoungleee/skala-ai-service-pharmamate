"""Compare a local Ollama router on the F8.1 synthetic routing set."""
from __future__ import annotations

import json
import os
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
from eval.run_routing_experiment import FOCUSED_SYSTEM, HUMAN, load_cases


def run(model_name: str) -> dict:
    model = ChatOpenAI(
        model=model_name,
        base_url=os.getenv("PHARMAMATE_OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
        api_key="ollama",
        temperature=0,
        timeout=180,
        max_retries=0,
    )
    chain = ChatPromptTemplate.from_messages([
        ("system", FOCUSED_SYSTEM), ("human", HUMAN),
    ]) | model.with_structured_output(RouteDecision, include_raw=True)
    cases = load_cases()
    warmup_started = time.perf_counter()
    warmup = chain.invoke({"term": "", "history": "", "question": "ADC가 뭐야?"})
    warmup_ms = round((time.perf_counter() - warmup_started) * 1000, 2)
    outcomes = []
    for case in cases:
        started = time.perf_counter()
        error = ""
        try:
            result = chain.invoke({"term": case["term"], "history": "", "question": case["question"]})
            parsed = result.get("parsed")
            raw = result.get("raw")
            actual = parsed.route if parsed else "parse_error"
            usage = getattr(raw, "usage_metadata", None) or {}
        except Exception as exc:
            actual, usage, error = "error", {}, type(exc).__name__
        latency_ms = (time.perf_counter() - started) * 1000
        outcomes.append({
            "id": case["id"], "expected": case["expected_route"], "actual": actual,
            "correct": actual == case["expected_route"], "latency_ms": round(latency_ms, 2),
            "input_tokens": int(usage.get("input_tokens", 0)),
            "output_tokens": int(usage.get("output_tokens", 0)),
            "error_type": error,
        })
    latencies = [row["latency_ms"] for row in outcomes]
    summary = {
        "model": model_name,
        "base_url": os.getenv("PHARMAMATE_OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
        "temperature": 0,
        "cases": len(outcomes),
        "warmup_latency_ms": warmup_ms,
        "warmup_parsed": isinstance(warmup.get("parsed"), RouteDecision),
        "correct": sum(row["correct"] for row in outcomes),
        "accuracy": round(sum(row["correct"] for row in outcomes) / max(len(outcomes), 1), 4),
        "p50_latency_ms": round(statistics.median(latencies), 2) if latencies else 0,
        "total_input_tokens": sum(row["input_tokens"] for row in outcomes),
        "total_output_tokens": sum(row["output_tokens"] for row in outcomes),
        "errors": [row for row in outcomes if not row["correct"]],
        "outcomes": outcomes,
    }
    reference_path = ROOT / "eval" / "results" / "routing_latest.json"
    if reference_path.exists():
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
        summary["openai_focused_reference"] = {
            key: reference["candidate"][key]
            for key in ("accuracy", "p50_latency_ms", "total_input_tokens", "total_output_tokens")
        }
    return summary


if __name__ == "__main__":
    model_name = sys.argv[1] if len(sys.argv) > 1 else "qwen3:0.6b"
    result = run(model_name)
    output = ROOT / "eval" / "results" / "ollama_routing_latest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"{result['model']}: route accuracy={result['correct']}/{result['cases']} "
        f"({result['accuracy']:.3f}), p50={result['p50_latency_ms']:.0f}ms, "
        f"warmup={result['warmup_latency_ms']:.0f}ms"
    )
    if result.get("openai_focused_reference"):
        reference = result["openai_focused_reference"]
        print(
            f"gpt-4o-mini reference: accuracy={reference['accuracy']:.3f}, "
            f"p50={reference['p50_latency_ms']:.0f}ms"
        )
    if result["errors"]:
        print("errors=" + ", ".join(
            f"{row['id']}:{row['expected']}→{row['actual']}" for row in result["errors"]
        ))
    print("Raw fixture results: eval/results/ollama_routing_latest.json")
