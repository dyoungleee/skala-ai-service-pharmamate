from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"평가 데이터 {line_number}행 JSON 오류: {exc.msg}") from exc
            if not case.get("case_id") or not case.get("question"):
                raise ValueError(f"평가 데이터 {line_number}행에 case_id 또는 question이 없습니다.")
            cases.append(case)
    return cases


def resolve_ref(ref: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.PIPE,
        ).strip()
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip()
        raise ValueError(f"기준선 Git ref를 확인하지 못했습니다 ({ref}): {detail}") from exc


def load_runner(spec: str) -> Callable[..., dict[str, Any]]:
    try:
        module_name, function_name = spec.split(":", 1)
    except ValueError as exc:
        raise ValueError("runner 형식은 package.module:function_name 이어야 합니다.") from exc
    module = importlib.import_module(module_name)
    runner = getattr(module, function_name)
    if not callable(runner):
        raise TypeError(f"runner가 호출 가능한 함수가 아닙니다: {spec}")
    return runner


def render_result(label: str, result: dict[str, Any]) -> None:
    sources = result.get("sources") or []
    print(f"\n[{label}]")
    print(f"경로: {result.get('route') or '미제공'}")
    print(f"Validator: {result.get('validator') or '미제공'}")
    elapsed = result.get("latency_seconds")
    print(f"응답 시간: {f'{elapsed:.2f}초' if isinstance(elapsed, (int, float)) else '미측정'}")
    tokens, cost = result.get("tokens"), result.get("cost")
    print(f"토큰 / 비용: {tokens if tokens is not None else '미제공'} / {cost if cost is not None else '미제공'}")
    print("출처:")
    if sources:
        for source in sources:
            if isinstance(source, dict):
                title = source.get("title") or source.get("url") or str(source)
                url = source.get("url", "")
                print(f"- {title}{f' ({url})' if url and url != title else ''}")
            else:
                print(f"- {source}")
    else:
        print("- 없음")
    print("답변:")
    print(result.get("answer") or "(답변 없음)")
    recommendations = result.get("recommendations") or []
    if recommendations:
        print("추천 후속 질문:")
        for item in recommendations:
            if isinstance(item, dict):
                category = item.get("category", "학습")
                goal = item.get("learning_goal", "")
                question = item.get("question", "")
                print(f"- [{category}] {question}{f' — 학습 목표: {goal}' if goal else ''}")


def run_demo(case: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """네트워크/API 없이 비교 화면만 점검합니다. 아래 답변은 평가 결과가 아닌 고정 예시입니다."""
    examples = {
        "RAG-01": (
            "ADC는 항체와 약물을 결합해 약물을 암세포에 전달하는 치료 방식입니다.",
            "ADC(항체-약물 접합체)는 항체에 항암 약물을 붙인 치료제입니다. "
            "항체가 암세포의 표적을 찾아가 약물이 그 세포에 더 많이 전달되도록 돕습니다.",
        ),
        "RAG-SEM-01": (
            "관련 용어를 찾지 못했습니다.",
            "이전 학습 기록의 항체-약물 접합체(ADC)를 찾았습니다. 항체가 표적 세포에 약물을 전달하는 방식입니다.",
        ),
        "EVIDENCE-01": (
            "이 가상 기사에서 임상 결과를 확인했습니다.",
            "평가 자료에는 초기 임상시험의 안전성과 내약성을 평가한다는 내용만 있습니다. "
            "유효성 결과나 성공률은 확인할 수 없습니다.",
        ),
        "GENERAL-01": (
            "두 의약품 유형은 다릅니다.",
            "단클론 항체는 표적에 선택적으로 결합하는 단백질 의약품이고, "
            "화학 합성 의약품은 화학 반응으로 만든 작은 분자 약물인 경우가 많습니다.",
        ),
    }
    old_answer, improved_answer = examples.get(
        case["case_id"],
        ("기준선 답변 예시입니다.", "개선 후보 답변 예시입니다."),
    )
    old = {
        "answer": f"[DEMO — 실제 응답 아님] {old_answer}",
        "sources": [], "route": "예시", "validator": "미측정",
        "latency_seconds": None, "tokens": None, "cost": None,
    }
    improved = {
        "answer": f"[DEMO — 실제 응답 아님] {improved_answer}",
        "sources": [{"title": "샘플 평가 fixture", "url": "fixture://sample"}],
        "route": "예시", "validator": "미측정",
        "latency_seconds": None, "tokens": None, "cost": None,
    }
    return old, improved


def write_results(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="동일한 평가 입력을 기준선과 개선 후보에 실행해 답변을 터미널에서 비교합니다."
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--case-id", help="실행할 평가 사례 ID")
    selection.add_argument("--all", action="store_true", help="평가 사례 전체 실행")
    parser.add_argument(
        "--cases", type=Path, default=ROOT / "eval" / "cases.jsonl",
        help="JSONL 평가 데이터 경로 (기본값: eval/cases.jsonl)",
    )
    parser.add_argument(
        "--baseline-runner", default="eval.runners.pharmamate_notebook:run_baseline",
        help="기준선 실행기 package.module:function",
    )
    parser.add_argument(
        "--candidate-runner", default="eval.runners.pharmamate_notebook:run_candidate",
        help="개선 후보 실행기 package.module:function",
    )
    parser.add_argument(
        "--baseline-ref", default="HEAD",
        help="기준선 코드의 Git ref. 현재 기능 개발 직전 커밋을 기본으로 사용합니다.",
    )
    parser.add_argument(
        "--results", type=Path, default=ROOT / "eval" / "results" / "latest.jsonl",
        help="실행 기록 경로 (로컬 전용, 기본값: eval/results/latest.jsonl)",
    )
    parser.add_argument("--demo", action="store_true", help="고정 샘플로 비교 화면만 점검하고 LLM은 호출하지 않음")
    args = parser.parse_args()

    try:
        cases = load_cases(args.cases)
        selected = cases if args.all else [case for case in cases if case["case_id"] == args.case_id]
        if not selected:
            available = ", ".join(case["case_id"] for case in cases) or "(없음)"
            raise ValueError(f"사례를 찾지 못했습니다: {args.case_id}. 사용 가능: {available}")
        if not args.demo:
            baseline_commit = resolve_ref(args.baseline_ref)
            baseline_runner = load_runner(args.baseline_runner)
            candidate_runner = load_runner(args.candidate_runner)
    except Exception as exc:
        print(f"실행 준비 오류: {exc}", file=sys.stderr)
        return 2

    output_rows: list[dict[str, Any]] = []
    print("PharmaMate 답변 비교" + (" — DEMO (고정 예시, LLM 미호출)" if args.demo else ""))
    if not args.demo:
        print(f"기준선 ref: {args.baseline_ref} ({baseline_commit[:12]})")
    else:
        print(f"기준선 ref: {args.baseline_ref}")
    print(f"평가 사례: {len(selected)}개")

    for case in selected:
        print("\n" + "=" * 78)
        print(f"사례 {case['case_id']} | {case.get('category', '기타')}")
        print(f"질문: {case['question']}")
        if args.demo:
            baseline, candidate = run_demo(case)
        else:
            try:
                baseline = baseline_runner(case, revision=baseline_commit)
                candidate = candidate_runner(case, revision=None)
            except Exception as exc:
                print(f"\n비교 실행 오류: {type(exc).__name__}: {exc}", file=sys.stderr)
                return 1
        render_result("기준선", baseline)
        render_result("개선 후보", candidate)
        output_rows.append({
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "case_id": case["case_id"],
            "baseline_ref": args.baseline_ref if args.demo else baseline_commit,
            "question": case["question"],
            "baseline": baseline,
            "candidate": candidate,
            "demo": bool(args.demo),
        })

    if not args.demo:
        try:
            write_results(args.results, output_rows)
            print(f"\n로컬 실행 기록: {args.results}")
        except OSError as exc:
            print(f"\n실행 기록 저장 실패: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
