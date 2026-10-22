"""Run the PharmaMate 3.0 backend graph against isolated evaluation fixtures."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from eval.runners.pharmamate_notebook import lexical_fixture_search

ROOT = Path(__file__).resolve().parents[2]


def run_candidate(case: dict[str, Any], *, revision: str | None = None) -> dict[str, Any]:
    """Execute the current 3.0 graph without the web client or production database."""
    from dotenv import load_dotenv
    from langchain_openai import ChatOpenAI
    from backend.app.agents.graph import build_agent_graph
    from backend.app.retrieval.embeddings import get_embedding_provider
    from backend.app.retrieval.service import SemanticDocumentSearch

    load_dotenv(ROOT / ".env", override=False)
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY가 없습니다. 프로젝트 .env 또는 환경 변수에 설정하세요.")

    model_name = os.getenv("PHARMAMATE_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    model = ChatOpenAI(
        model=model_name,
        temperature=0.2,
        timeout=90,
        max_retries=2,
        streaming=True,
        api_key=api_key,
    )
    records = case.get("memory_records", [])
    searcher = None
    if records:
        try:
            searcher = SemanticDocumentSearch(
                records, get_embedding_provider(), owner_id="local"
            )
        except Exception:
            # Match the product's semantic-search fallback when embeddings fail.
            searcher = None

    def fixture_memory_search(question: str, limit: int = 3, owner_id: str = "local"):
        if searcher is not None:
            try:
                return searcher.search(question, limit=limit)
            except Exception:
                pass
        return lexical_fixture_search(question, records, limit)

    graph = build_agent_graph(
        model=model,
        search_client=None,
        search_study_memory=fixture_memory_search,
        get_term_examples=lambda _term_key, limit=8: [],
        get_saved_note=lambda _term_key: "",
    )
    request = {
        "question": case["question"],
        "article": case.get("article", ""),
        "term": case.get("term", ""),
        "history": case.get("history", ""),
        "owner_id": "local",
    }
    started = time.perf_counter()
    result = graph.invoke(request)
    elapsed = time.perf_counter() - started
    status = result.get("validation_status", "미제공")
    retries = int(result.get("validation_retries", 0))
    return {
        "answer": result.get("answer", ""),
        "recommendations": result.get("recommendations", []),
        "sources": result.get("sources", []),
        "route": result.get("route", ""),
        "validator": f"{status} (수정 {retries}회)",
        "validation_status": status,
        "validation_retries": retries,
        "unsupported_claims": result.get("unsupported_claims", []),
        "validation_feedback": result.get("validation_feedback", ""),
        "latency_seconds": elapsed,
        "tokens": None,
        "cost": None,
    }
