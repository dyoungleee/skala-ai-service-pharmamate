"""Check local Ollama compatibility with PharmaMate's structured model schemas."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langchain_openai import ChatOpenAI

from backend.app.agents.graph import RouteDecision
from backend.app.agents.validator import AnswerValidation
from backend.app.services.recommendations import LearningTurnResponse


SCHEMAS = {
    "route": (RouteDecision, "Compare my saved ADC learning note with the recent clinical results. Choose memory_web."),
    "recommendations": (
        LearningTurnResponse,
        "Explain ADC briefly. Return three beginner learning questions with categories and one-sentence goals.",
    ),
    "validator": (
        AnswerValidation,
        "Question: What does the source say? Answer: The source describes an early safety study. "
        "Evidence: an early safety study was described. Return pass.",
    ),
}


def run(model_name: str, selected: list[str], disable_thinking: bool, timeout: float) -> dict:
    extra_body = {"think": False} if disable_thinking else None
    model = ChatOpenAI(
        model=model_name,
        base_url=os.getenv("PHARMAMATE_OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
        api_key="ollama",
        temperature=0,
        timeout=timeout,
        max_retries=0,
        extra_body=extra_body,
    )
    outcomes = []
    for name in selected:
        schema, prompt = SCHEMAS[name]
        started = time.perf_counter()
        try:
            response = model.with_structured_output(schema).invoke(prompt)
            parsed = isinstance(response, schema)
            error = "" if parsed else "unparsed_output"
        except Exception as exc:
            parsed, error = False, type(exc).__name__
        outcomes.append({
            "schema": name,
            "parsed": parsed,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error_type": error,
        })
    latencies = [row["latency_ms"] for row in outcomes]
    return {
        "provider": "ollama_openai_compatible_endpoint",
        "model": model_name,
        "base_url": os.getenv("PHARMAMATE_OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
        "think_disabled": disable_thinking,
        "schema_count": len(outcomes),
        "parsed_count": sum(row["parsed"] for row in outcomes),
        "p50_latency_ms": round(statistics.median(latencies), 2) if latencies else 0,
        "outcomes": outcomes,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--only", choices=sorted(SCHEMAS), action="append")
    parser.add_argument("--disable-thinking", action="store_true")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "eval" / "results" / "ollama_smoke_latest.json"
    )
    args = parser.parse_args()
    result = run(args.model, args.only or list(SCHEMAS), args.disable_thinking, args.timeout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"{result['model']}: structured outputs {result['parsed_count']}/{result['schema_count']}, "
        f"p50={result['p50_latency_ms']:.0f}ms, think_disabled={result['think_disabled']}"
    )
    for outcome in result["outcomes"]:
        print(f"  {outcome['schema']}: parsed={outcome['parsed']}, latency={outcome['latency_ms']:.0f}ms")
    print(f"Raw fixture results: {args.output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
