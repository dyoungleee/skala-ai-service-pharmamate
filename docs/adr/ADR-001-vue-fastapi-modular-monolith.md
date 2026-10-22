# ADR-001: Vue와 FastAPI를 모듈형 단일 서비스로 연결

- 상태: 채택
- 결정일: 2026-10-20

## Context

PharmaMate 2.2의 주요 인터페이스는 Jupyter Notebook과 Gradio였다. 평가용 확장에는 SSE, 세션 복원, 분리된 사용자 화면이 필요하지만, 서비스 규모와 팀 크기는 단일 프로젝트 수준이다.

## Alternatives

1. Gradio 화면을 유지하고 Notebook 기능만 보강한다.
2. Vue 화면과 FastAPI를 연결하고 Agent, DB, 검색 코드는 같은 Python 서비스에서 모듈로 유지한다.
3. API, 기사 분석, 검색, 대화 기능을 여러 마이크로서비스로 분리한다.

## Decision

2번을 선택한다. Vue/Vite는 화면과 브라우저 상태를 맡고 FastAPI는 API 키, Agent 그래프, SQLite 저장소, SSE를 맡는다. Vite 개발 서버는 `/api`를 FastAPI로 전달한다. Python 내부 코드는 `agents`, `services`, `retrieval`, `db`, `schemas`, `core` 모듈로 분리하며 같은 프로세스에서 실행한다.

## Consequences

- 기존 Agent와 SQLite 코드를 재사용하면서 화면과 API를 독립적으로 점검할 수 있다.
- 브라우저에 LLM API 키를 전달하지 않는다.
- 단일 프로세스·SQLite 구성은 로컬 실행과 발표 시연이 단순하다.
- API와 데이터베이스를 독립 배포·확장해야 하는 부하에는 적합하지 않다. 운영 규모가 생기면 인증, HTTPS, 영속 데이터베이스, 작업 큐를 별도 검토한다.
- 사용자 인증을 대신하지 않는 로컬 익명 세션 토큰을 사용한다. 외부 공개에는 이 토큰만으로 충분하지 않다.

## Evidence

- FastAPI API와 SSE 기능별 테스트는 `docs/experiments/F6_1_fastapi_api.md`, `F6_2_sse_streaming.md`에 기록한다.
- Vue 기능 빌드는 `docs/experiments/F6_3_vue_frontend.md`에서 확인한다.
- 세션 소유권과 복원은 `docs/experiments/F7_1_sessions.md`의 격리 테스트로 검증한다.
