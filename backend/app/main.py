"""Local FastAPI interface for PharmaMate."""
from __future__ import annotations

import asyncio

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from backend.app.api.streaming import sse_event
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


@app.post("/api/chat/stream")
async def chat_stream_endpoint(
    request: ChatRequest,
    runtime: PharmaMateRuntime = Depends(runtime_dependency),
) -> StreamingResponse:
    history = "\n".join(
        f"사용자: {item.question}\nAI: {item.answer[:800]}"
        for item in request.history[-6:]
    )
    agent_input = {
        "question": request.question.strip(),
        "article": request.article,
        "term": request.term,
        "history": history,
    }

    async def events():
        yield sse_event("status", {"stage": "started", "message": "질문을 확인합니다."})
        final_state: dict = {}
        sent_stages: set[str] = set()
        stage_labels = {
            "router": "질문 처리 경로를 고릅니다.",
            "memory": "학습 기록을 찾습니다.",
            "web": "최신 웹 정보를 확인합니다.",
            "answer": "답변과 후속 질문을 만듭니다.",
            "validator": "답변의 근거를 검증합니다.",
            "insufficient": "근거가 부족해 답변을 제한합니다.",
        }
        try:
            async for graph_event in runtime.agent_graph.astream_events(agent_input, version="v2"):
                metadata = graph_event.get("metadata") or {}
                node = metadata.get("langgraph_node")
                if graph_event.get("event") == "on_chain_start" and node in stage_labels and node not in sent_stages:
                    sent_stages.add(node)
                    yield sse_event("status", {"stage": node, "message": stage_labels[node]})
                if graph_event.get("event") == "on_chain_end":
                    output = (graph_event.get("data") or {}).get("output")
                    if isinstance(output, dict) and "answer" in output:
                        final_state.update(output)

            answer = str(final_state.get("answer") or "")
            if not answer:
                yield sse_event("error", {"message": "Agent가 답변을 반환하지 않았습니다."})
                return
            # 검증 전 초안은 내보내지 않습니다. 검증이 끝난 답변만 짧은 조각으로 전달합니다.
            for offset in range(0, len(answer), 48):
                yield sse_event("token", {"text": answer[offset:offset + 48]})
                await asyncio.sleep(0)
            yield sse_event("sources", {"items": final_state.get("sources") or []})
            yield sse_event("recommendations", {"items": final_state.get("recommendations") or []})
            yield sse_event("done", {
                "route": final_state.get("route", ""),
                "validation_status": final_state.get("validation_status", ""),
                "validation_retries": int(final_state.get("validation_retries", 0)),
            })
        except Exception as exc:
            yield sse_event("error", {"message": f"스트리밍 답변 생성 실패 ({type(exc).__name__})."})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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
