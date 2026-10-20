"""Local FastAPI interface for PharmaMate."""
from __future__ import annotations

import asyncio

from fastapi import Depends, FastAPI, Header, HTTPException
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
    CreateSessionResponse,
    IndustryIssueSummary,
    MarkSessionArticleReadRequest,
    MarkSessionArticleReadResponse,
    SaveSessionStudyRecordRequest,
    SaveStudyRecordRequest,
    SaveStudyRecordResponse,
    SessionArticleUpdateRequest,
    SessionArticleSummary,
    SessionSnapshot,
    SessionStudyRecordSummary,
    StudyRecordSummary,
)
from backend.app.services.article_analysis import analyze_article
from backend.app.services.article_extraction import article_id_for, load_article
from backend.app.services.session_service import can_access_session, create_anonymous_session


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


def require_session_access(session_id: str, authorization: str | None) -> None:
    try:
        allowed = can_access_session(session_id, authorization)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="세션 저장소를 사용할 수 없습니다.") from exc
    if not allowed:
        # Missing, unknown, and invalid credentials share the same response.
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")


def session_snapshot(session_id: str) -> SessionSnapshot:
    session = repository.get_study_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    article = session.get("active_article") or None
    return SessionSnapshot(
        session_id=session_id,
        article=article,
        selected_term_key=session.get("selected_term_key", ""),
        turns=repository.get_session_turns(session_id),
        created_at=session["created_at"],
        updated_at=session["updated_at"],
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "pharmamate-api"}


@app.post("/api/sessions", response_model=CreateSessionResponse)
def create_session_endpoint(
    runtime: PharmaMateRuntime = Depends(runtime_dependency),
) -> CreateSessionResponse:
    del runtime
    session_id, access_token, created_at = create_anonymous_session()
    return CreateSessionResponse(
        session_id=session_id, access_token=access_token, created_at=created_at
    )


@app.get("/api/sessions/{session_id}", response_model=SessionSnapshot)
def get_session_endpoint(
    session_id: str,
    authorization: str | None = Header(default=None),
    runtime: PharmaMateRuntime = Depends(runtime_dependency),
) -> SessionSnapshot:
    del runtime
    require_session_access(session_id, authorization)
    return session_snapshot(session_id)


@app.put("/api/sessions/{session_id}/article", response_model=SessionSnapshot)
def save_session_article_endpoint(
    session_id: str,
    request: SessionArticleUpdateRequest,
    authorization: str | None = Header(default=None),
    runtime: PharmaMateRuntime = Depends(runtime_dependency),
) -> SessionSnapshot:
    del runtime
    require_session_access(session_id, authorization)
    article = request.article.model_dump()
    selected_term_key = repository.normalize_term(request.selected_term_key)
    try:
        repository.save_session_article(session_id, article, selected_term_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.") from exc
    return session_snapshot(session_id)


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
        related_to_selected=bool(result.get("related_to_selected", False)),
        sources=result.get("sources") or [],
        validation_status=str(result.get("validation_status") or ""),
        validation_retries=int(result.get("validation_retries") or 0),
        recommendations=result.get("recommendations") or [],
    )


@app.post("/api/study-records", response_model=SaveStudyRecordResponse)
def save_study_record_endpoint(
    request: SaveStudyRecordRequest,
    runtime: PharmaMateRuntime = Depends(runtime_dependency),
) -> SaveStudyRecordResponse:
    del runtime  # Runtime dependency configures the selected local SQLite database.
    term_key = repository.normalize_term(request.term.term)
    state = {
        "article_id": request.article_id,
        "url": request.article_url,
        "history": [
            {
                "question": item.question,
                "answer": item.answer,
                "linked_term_key": term_key if item.linked_to_selected else "",
                "article_id": request.article_id,
            }
            for item in request.history
        ],
    }
    try:
        _was_known, saved_key, new_count, matched_count, _note = repository.save_learning_bundle(
            request.term.model_dump(), state, request.note
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"학습 기록을 저장하지 못했습니다 ({type(exc).__name__}).",
        ) from exc
    return SaveStudyRecordResponse(
        term_key=saved_key,
        new_questions=new_count,
        matched_questions=matched_count,
        message=f"학습 메모 자동 저장 완료: 신규 관련 Q&A {new_count}건",
    )


async def build_chat_stream(
    request: ChatRequest,
    runtime: PharmaMateRuntime,
    session_id: str = "",
) -> StreamingResponse:
    session = repository.get_study_session(session_id) if session_id else None
    selected_term_name = request.term.splitlines()[0].strip() if request.term.strip() else ""
    selected_term_key = repository.normalize_term(selected_term_name)
    turns = repository.get_session_turns(
        session_id, limit=6, term_key=selected_term_key
    ) if session_id else []
    history_items = (
        [(turn["question"], turn["answer"]) for turn in turns[-6:]]
        if session_id else [(item.question, item.answer) for item in request.history[-6:]]
    )
    history = "\n".join(f"사용자: {question}\nAI: {answer[:800]}" for question, answer in history_items)
    article = (session or {}).get("active_article") or {}
    agent_input = {
        "question": request.question.strip(),
        "article": article.get("article", "") if session_id else request.article,
        "term": request.term,
        "history": history,
    }
    if session_id:
        agent_input["owner_id"] = session_id

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
            if session_id:
                repository.append_session_turn(session_id, {
                    "question": request.question.strip(),
                    "answer": answer,
                    "term_key": repository.normalize_term(selected_term_name),
                    "term_name": selected_term_name,
                    "article_id": str(article.get("article_id") or ""),
                    "related_to_selected": bool(final_state.get("related_to_selected", False)),
                    "route": str(final_state.get("route") or ""),
                    "sources": final_state.get("sources") or [],
                    "recommendations": final_state.get("recommendations") or [],
                    "validation_status": str(final_state.get("validation_status") or ""),
                    "validation_retries": int(final_state.get("validation_retries") or 0),
                })
            # 검증 전 초안은 내보내지 않습니다. 검증이 끝난 답변만 짧은 조각으로 전달합니다.
            for offset in range(0, len(answer), 48):
                yield sse_event("token", {"text": answer[offset:offset + 48]})
                await asyncio.sleep(0)
            yield sse_event("sources", {"items": final_state.get("sources") or []})
            yield sse_event("recommendations", {"items": final_state.get("recommendations") or []})
            yield sse_event("done", {
                "route": final_state.get("route", ""),
                "related_to_selected": bool(final_state.get("related_to_selected", False)),
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


@app.post("/api/chat/stream")
async def chat_stream_endpoint(
    request: ChatRequest,
    runtime: PharmaMateRuntime = Depends(runtime_dependency),
) -> StreamingResponse:
    return await build_chat_stream(request, runtime)


@app.post("/api/sessions/{session_id}/chat/stream")
async def session_chat_stream_endpoint(
    session_id: str,
    request: ChatRequest,
    authorization: str | None = Header(default=None),
    runtime: PharmaMateRuntime = Depends(runtime_dependency),
) -> StreamingResponse:
    require_session_access(session_id, authorization)
    return await build_chat_stream(request, runtime, session_id)


@app.get(
    "/api/sessions/{session_id}/study-records",
    response_model=list[SessionStudyRecordSummary],
)
def session_study_records_endpoint(
    session_id: str,
    authorization: str | None = Header(default=None),
    runtime: PharmaMateRuntime = Depends(runtime_dependency),
) -> list[SessionStudyRecordSummary]:
    del runtime
    require_session_access(session_id, authorization)
    return [SessionStudyRecordSummary(**row) for row in repository.get_session_study_records(session_id)]


@app.post(
    "/api/sessions/{session_id}/study-records",
    response_model=SaveStudyRecordResponse,
)
def save_session_study_record_endpoint(
    session_id: str,
    request: SaveSessionStudyRecordRequest,
    authorization: str | None = Header(default=None),
    runtime: PharmaMateRuntime = Depends(runtime_dependency),
) -> SaveStudyRecordResponse:
    del runtime
    require_session_access(session_id, authorization)
    try:
        saved_key, new_count, matched_count = repository.save_session_study_record(
            session_id, request.term.model_dump(), request.note
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.") from exc
    return SaveStudyRecordResponse(
        term_key=saved_key,
        new_questions=new_count,
        matched_questions=matched_count,
        message=f"학습 메모 자동 저장 완료: 신규 관련 Q&A {new_count}건",
    )


@app.post(
    "/api/sessions/{session_id}/articles/mark-read",
    response_model=MarkSessionArticleReadResponse,
)
def mark_session_article_read_endpoint(
    session_id: str,
    request: MarkSessionArticleReadRequest,
    authorization: str | None = Header(default=None),
    runtime: PharmaMateRuntime = Depends(runtime_dependency),
) -> MarkSessionArticleReadResponse:
    del runtime
    require_session_access(session_id, authorization)
    try:
        result = repository.mark_session_article_read(
            session_id, request.article.model_dump(), request.issue_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.") from exc
    return MarkSessionArticleReadResponse(**result)


@app.get(
    "/api/sessions/{session_id}/articles",
    response_model=list[SessionArticleSummary],
)
def session_articles_endpoint(
    session_id: str,
    authorization: str | None = Header(default=None),
    runtime: PharmaMateRuntime = Depends(runtime_dependency),
) -> list[SessionArticleSummary]:
    del runtime
    require_session_access(session_id, authorization)
    return [SessionArticleSummary(**row) for row in repository.get_session_articles(session_id)]


@app.get(
    "/api/sessions/{session_id}/industry-issues",
    response_model=list[IndustryIssueSummary],
)
def session_industry_issues_endpoint(
    session_id: str,
    authorization: str | None = Header(default=None),
    runtime: PharmaMateRuntime = Depends(runtime_dependency),
) -> list[IndustryIssueSummary]:
    del runtime
    require_session_access(session_id, authorization)
    return [IndustryIssueSummary(**row) for row in repository.get_session_industry_issues(session_id)]


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
