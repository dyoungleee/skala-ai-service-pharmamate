"""Local FastAPI interface for PharmaMate."""
from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.app.core.runtime import PharmaMateRuntime, get_runtime
from backend.app.db import repository
from backend.app.schemas.api import (
    ArticleAnalyzeRequest,
    ArticleAnalyzeResponse,
    ChatRequest,
    ChatResponse,
    StudyRecordSummary,
)
from backend.app.services.article_analysis import analyze_article
from backend.app.services.article_extraction import article_id_for, load_article


app = FastAPI(
    title="PharmaMate 3.0 API",
    version="3.0.0",
    description="Local article learning and evidence-aware chat API",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def runtime_dependency() -> PharmaMateRuntime:
    try:
        return get_runtime()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "pharmamate-api"}


@app.post("/api/articles/analyze", response_model=ArticleAnalyzeResponse)
def analyze_article_endpoint(
    request: ArticleAnalyzeRequest,
    runtime: PharmaMateRuntime = Depends(runtime_dependency),
) -> ArticleAnalyzeResponse:
    try:
        article, metadata = load_article(request.url, request.pasted_text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        analysis = analyze_article(runtime.article_chain, article)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"기사 분석을 완료하지 못했습니다 ({type(exc).__name__}).",
        ) from exc
    title = (request.title or "").strip() or metadata.get("title") or "기사 원문"
    return ArticleAnalyzeResponse(
        article_id=article_id_for(article, metadata.get("source", "")),
        article=article,
        url=metadata.get("source", ""),
        title=title,
        load_method=metadata.get("load_method", ""),
        analysis=analysis.model_copy(update={"key_terms": analysis.key_terms[:5]}),
    )


@app.post("/api/chat", response_model=ChatResponse)
def chat_endpoint(
    request: ChatRequest,
    runtime: PharmaMateRuntime = Depends(runtime_dependency),
) -> ChatResponse:
    history = "\n".join(
        f"사용자: {item.question}\nAI: {item.answer[:800]}"
        for item in request.history[-6:]
    )
    try:
        result = runtime.agent_graph.invoke({
            "question": request.question.strip(),
            "article": request.article,
            "term": request.term,
            "history": history,
        })
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Agent 답변 생성에 실패했습니다 ({type(exc).__name__}).",
        ) from exc
    return ChatResponse(
        answer=str(result.get("answer") or "답변을 생성하지 못했습니다."),
        route=str(result.get("route") or ""),
        sources=result.get("sources") or [],
        validation_status=str(result.get("validation_status") or ""),
        validation_retries=int(result.get("validation_retries") or 0),
        recommendations=result.get("recommendations") or [],
    )


@app.get("/api/study-records", response_model=list[StudyRecordSummary])
def study_records_endpoint(
    runtime: PharmaMateRuntime = Depends(runtime_dependency),
) -> list[StudyRecordSummary]:
    del runtime  # Runtime dependency configures the selected local SQLite database.
    return [
        StudyRecordSummary(
            term_key=row["term_key"],
            term_name=row["term_name"],
            category=row["category"],
            simple_definition=row["simple_definition"],
            review_count=row["review_count"],
            first_learned_at=row["first_learned_at"],
        )
        for row in repository.get_learned_rows()
    ]
