from __future__ import annotations

import json
import math
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    if not os.getenv("OPENAI_API_KEY", "").strip():
        print("OPENAI_API_KEY가 없습니다. 프로젝트 .env 또는 환경 변수에 설정하세요.", file=sys.stderr)
        return 2

    from langchain_openai import ChatOpenAI
    from backend.app.agents.validator import build_answer_validator, validate_answer

    model_name = os.getenv("PHARMAMATE_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    model = ChatOpenAI(model=model_name, temperature=0.2, timeout=90, max_retries=2)
    judge = build_answer_validator(model)
    cases = [
        json.loads(line)
        for line in (ROOT / "eval" / "validator_cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    output: list[dict[str, Any]] = []
    for case in cases:
        started = time.perf_counter()
        try:
            verdict = validate_answer(
                judge,
                question=case["question"],
                answer=case["answer"],
                evidence=case["evidence"],
            )
            status = verdict["status"]
            error = None
        except Exception as exc:
            status = "unavailable"
            verdict = {"unsupported_claims": [], "feedback": ""}
            error = type(exc).__name__
        elapsed = time.perf_counter() - started
        expected_safe = case["expected"] == "pass"
        predicted_safe = status == "pass"
        output.append({
            "case_id": case["case_id"],
            "expected": case["expected"],
            "status": status,
            "correct": expected_safe == predicted_safe,
            "latency_seconds": elapsed,
            "unsupported_claims": verdict.get("unsupported_claims", []),
            "error": error,
        })

    supported = [row for row in output if row["expected"] == "pass"]
    unsupported = [row for row in output if row["expected"] == "flag"]
    accuracy = sum(row["correct"] for row in output) / max(len(output), 1)
    unsupported_acceptance = sum(row["status"] == "pass" for row in unsupported) / max(len(unsupported), 1)
    supported_block_rate = sum(row["status"] != "pass" for row in supported) / max(len(supported), 1)
    latencies = [row["latency_seconds"] for row in output]
    result_path = ROOT / "eval" / "results" / "validator_latest.jsonl"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in output), encoding="utf-8"
    )

    print(f"답변 근거 검증 평가 | 합성 사례 {len(output)}개 | 모델 {model_name}")
    print(f"일치율: {accuracy:.3f} ({sum(row['correct'] for row in output)}/{len(output)})")
    print(f"근거 없는 답변 통과율: {unsupported_acceptance:.3f}")
    print(f"근거 있는 답변 차단율: {supported_block_rate:.3f}")
    print(f"검증 지연 p50/p95: {percentile(latencies, .50):.3f}s / {percentile(latencies, .95):.3f}s")
    print(f"상세 합성 결과: {result_path}")
    for row in output:
        if not row["correct"] or row["error"]:
            print(f"검토 필요: {row['case_id']} expected={row['expected']} actual={row['status']} error={row['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
