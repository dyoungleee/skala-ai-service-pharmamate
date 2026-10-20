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


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def legacy_lexical_search(query: str, records: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    """Replicate the 2.2 term-name/alias and definition token search."""
    import re

    question_low = query.casefold()
    query_tokens = [token for token in re.findall(r"[A-Za-z0-9가-힣]+", question_low) if len(token) > 1]
    ranked = []
    for record in records:
        if record.get("source_type") != "term":
            continue
        names = list(record.get("aliases") or []) + [record.get("term_name", "")]
        score = sum(4 for name in names if len(str(name).strip()) >= 2 and str(name).casefold() in question_low)
        definition = str(record.get("simple_definition", "")).casefold()
        score += sum(1 for token in query_tokens if token in definition)
        if score:
            ranked.append((score, record))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [record for _, record in ranked[:limit]]


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percent * len(ordered)) - 1)
    return ordered[index]


def evaluate_rank(rows: list[dict[str, Any]], expected: set[str]) -> tuple[bool, float | None]:
    for rank, row in enumerate(rows, 1):
        if row.get("term_key") in expected:
            return True, 1.0 / rank
    return False, None


def summarize(rows: list[dict[str, Any]], key: str) -> dict[str, float]:
    hits = [row for row in rows if row[f"{key}_hit"]]
    reciprocal_ranks = [row[f"{key}_rr"] or 0.0 for row in rows]
    latencies = [row[f"{key}_latency_seconds"] for row in rows]
    return {
        "recall_at_3": len(hits) / max(len(rows), 1),
        "mrr": statistics.mean(reciprocal_ranks) if reciprocal_ranks else 0.0,
        "p50_seconds": percentile(latencies, 0.50),
        "p95_seconds": percentile(latencies, 0.95),
    }


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    if not os.getenv("OPENAI_API_KEY", "").strip():
        print("OPENAI_API_KEY가 없습니다. 프로젝트 .env 또는 환경 변수에 설정하세요.", file=sys.stderr)
        return 2

    from backend.app.retrieval.embeddings import get_embedding_provider
    from backend.app.retrieval.service import SemanticDocumentSearch

    documents = read_jsonl(ROOT / "eval" / "rag_memory_fixture.jsonl")
    cases = read_jsonl(ROOT / "eval" / "rag_retrieval_cases.jsonl")
    provider = get_embedding_provider()
    started = time.perf_counter()
    semantic_index = SemanticDocumentSearch(documents, provider, owner_id="local")
    index_build_seconds = time.perf_counter() - started

    output = []
    for case in cases:
        query = case["query"]
        expected = set(case["expected_term_keys"])

        lexical_started = time.perf_counter()
        lexical_rows = legacy_lexical_search(query, documents)
        lexical_elapsed = time.perf_counter() - lexical_started

        semantic_started = time.perf_counter()
        semantic_rows = semantic_index.search(query, limit=3)
        semantic_elapsed = time.perf_counter() - semantic_started
        lexical_hit, lexical_rr = evaluate_rank(lexical_rows, expected)
        semantic_hit, semantic_rr = evaluate_rank(semantic_rows, expected)
        output.append({
            "case_id": case["case_id"],
            "query": query,
            "expected_term_keys": sorted(expected),
            "lexical_hit": lexical_hit,
            "lexical_rr": lexical_rr,
            "lexical_latency_seconds": lexical_elapsed,
            "lexical_top3": [row.get("term_key") for row in lexical_rows],
            "semantic_hit": semantic_hit,
            "semantic_rr": semantic_rr,
            "semantic_latency_seconds": semantic_elapsed,
            "semantic_top3": [row.get("term_key") for row in semantic_rows],
            "semantic_top3_scores": [round(row.get("score", 0.0), 4) for row in semantic_rows],
            "semantic_sources": [row.get("record_id") for row in semantic_rows],
        })

    baseline = summarize(output, "lexical")
    candidate = summarize(output, "semantic")
    result_path = ROOT / "eval" / "results" / "rag_retrieval_latest.jsonl"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in output), encoding="utf-8")

    print(f"개인 학습 RAG 검색 평가 | 합성 기록 {len(documents)}개 / 질의 {len(cases)}개")
    print(f"임베딩 모델: {provider.model_name}")
    print(f"임베딩 인덱스 생성: {index_build_seconds:.2f}초 (최초 생성 비용 포함)")
    print("방식       Recall@3   MRR      p50       p95")
    print(f"2.2 단어   {baseline['recall_at_3']:.3f}     {baseline['mrr']:.3f}   {baseline['p50_seconds']:.3f}s   {baseline['p95_seconds']:.3f}s")
    print(f"의미 검색  {candidate['recall_at_3']:.3f}     {candidate['mrr']:.3f}   {candidate['p50_seconds']:.3f}s   {candidate['p95_seconds']:.3f}s")
    print(f"상세 합성 결과: {result_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
