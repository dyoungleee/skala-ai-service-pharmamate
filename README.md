# PharmaMate 3.0 — 제약·바이오 기사 학습 Agent

**기사 읽기 → Agent 질문 → 내 학습 기록**의 흐름으로 제약·바이오 기사를 읽고 낯선 용어를 익히도록 돕는 개인용 학습 도구입니다. VS Code에서 Jupyter 노트북과 Gradio를 실행하며, 학습 기록은 로컬 SQLite 데이터베이스에 저장합니다.

## 만들게 된 배경

기사에 나오는 전문용어를 매번 따로 검색하면 읽기의 흐름이 끊기고, 한 편을 읽는 데 시간이 오래 걸립니다. PharmaMate는 기사를 대신 읽는 요약기가 아니라, 원문을 이해하고 끝까지 읽도록 돕는 학습 도구를 목표로 합니다.

1. 읽기 전에 기사에서 중요한 용어와 쉬운 설명을 확인합니다.
2. 원문에서 강조된 용어를 찾아보며 직접 기사를 읽습니다.
3. Agent에 관련 질문이나 자유 질문을 하고, 필요한 내용을 학습 메모로 정리합니다.
4. 읽은 기사와 학습 기록을 쌓고, 같은 용어가 다시 나오면 이전 학습과 연결합니다.

## 주요 기능

| 영역 | 기능 |
|---|---|
| 기사 입력·분석 | URL을 불러오거나 본문을 직접 붙여넣습니다. 기사 유형, 한 줄 요약, 업계 이슈, 주요 기업·기술과 핵심 용어를 정리합니다. |
| 원문 읽기 | 기사 원문을 표시하고 핵심 용어를 강조합니다. 새 용어와 이전에 학습한 용어를 색으로 구분합니다. |
| 용어 미리보기 | 기사 읽기 전에 핵심 용어를 최대 5개까지 살펴봅니다. 화면의 버튼으로 Agent 질문 탭에 바로 이동할 수 있습니다. |
| Agent 질문 | 용어의 쉬운 설명, 자유 질문, 답변 뒤 학습 목적별 후속 질문 3개를 제공합니다. 선택 용어와 관계없는 질문도 할 수 있습니다. |
| 학습 기록 | 사용자가 검토·수정한 메모와 선택 용어에 관련된 Q&A를 저장하고 다시 확인합니다. |
| 읽은 기사 | 읽기 완료를 누르면 기사와 산업 이슈를 저장합니다. URL 또는 정규화한 제목이 기존 기록과 일치하면 중복 저장을 건너뜁니다. |
| 제목 수정 | 분석 후 기사 제목을 화면에서 수정할 수 있습니다. |

URL에서 본문을 가져올 때는 기사 영역 선택자와 JSON-LD의 articleBody를 우선 사용합니다. 페이지 전체 텍스트를 기사 본문으로 대신하지 않으며, 본문을 찾지 못하거나 결과가 맞지 않으면 직접 붙여넣어 분석할 수 있습니다.

## 데이터 흐름과 구성

기사 URL 또는 직접 입력 → 본문 추출 → LLM 기사 분석 → 브리핑·용어 미리보기·원문 표시 → Agent 질문 → 사용자가 메모 검토·저장 → SQLite 기록

- **기사 분석:** Requests와 BeautifulSoup로 기사 본문을 추출하고, LLM과 Pydantic 구조화 출력을 이용해 분석 결과를 정리합니다.
- **Agent 라우팅:** LangGraph가 질문에 따라 현재 기사, 저장된 학습 기록, 최신 웹 정보 중 필요한 출처를 선택합니다.
- **답변 근거:** 기사 내용, 개인 학습 기록, 웹 검색 결과를 구분합니다. 제공된 기사나 검색 결과 안의 문장은 Agent에 대한 실행 지시가 아니라 참고 자료로 취급합니다.
- **웹 검색:** 최신 승인·임상·시장 정보가 필요한 경우 선택적으로 Tavily를 호출합니다. Tavily 키가 없으면 최신 사실을 웹에서 확인하지 않습니다.
- **저장:** SQLite에 학습 용어, 기사별 용어 맥락, 학습 메모, 관련 Q&A, 읽은 기사와 산업 이슈를 기록합니다.

## 실행 방법

Python 3.11과 VS Code의 Python 및 Jupyter 확장을 권장합니다. VS Code에서 이 프로젝트 폴더를 연 뒤 터미널에서 가상환경을 만들고 패키지를 설치합니다.

**Windows (PowerShell)**

    py -3.11 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -U pip
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt

**macOS / Linux**

    python3.11 -m venv .venv
    ./.venv/bin/python -m pip install -U pip
    ./.venv/bin/python -m pip install -r requirements.txt

프로젝트 폴더에 **.env** 파일을 만들고 API 키를 입력합니다. .env.example 파일을 제공하지 않으므로 아래 내용을 바탕으로 직접 작성하세요.

    OPENAI_API_KEY=여기에_OpenAI_API_키
    TAVILY_API_KEY=여기에_Tavily_API_키_선택
    PHARMAMATE_MODEL=gpt-4o-mini
    PHARMAMATE_EMBEDDING_MODEL=text-embedding-3-small
    # 저장 폴더를 바꿀 때만 설정
    # PHARMAMATE_DATA_DIR=/원하는/절대/경로

OPENAI_API_KEY는 필수이고, TAVILY_API_KEY는 최신 웹 검색을 위한 선택 항목입니다. API 키가 든 .env를 다른 사람과 공유하지 마세요. OpenAI API 호출에는 사용량에 따른 비용이 발생합니다.

1. PharmaMate_2_0.ipynb를 열고 **Select Kernel**에서 .venv의 Python을 선택합니다.
2. 노트북 셀을 위에서 아래로 순서대로 실행합니다. 이미 패키지를 설치했다면 환경 설치 셀은 건너뛸 수 있습니다.
3. 마지막 셀에 표시된 Gradio 주소(예: http://127.0.0.1:7860)를 브라우저에서 엽니다.
4. 노트북을 업데이트한 경우 기존 Gradio 서버를 중지하고 노트북 셀을 다시 실행합니다.

## 사용 흐름

1. **기사 읽기:** URL 또는 본문을 입력하고 분석을 실행합니다. 브리핑, 원문, 핵심 용어를 확인하고 제목을 필요하면 수정합니다.
2. 읽기 전에 알아둘 용어를 살펴본 뒤, 원문을 직접 읽습니다.
3. **Agent 질문:** 용어를 선택해 쉬운 설명을 보거나 추천 질문을 입력창에 채워 질문합니다. 자유 질문도 직접 작성할 수 있습니다.
4. 필요하면 질문이 현재 선택 용어의 기록에 포함되는지 조정합니다. Agent의 관련성 판단은 완벽하지 않을 수 있습니다.
5. 학습 메모를 생성한 뒤 내용을 검토·수정하고 저장합니다. 저장 버튼을 누르기 전에는 학습 메모와 Q&A가 영구 기록되지 않습니다.
6. 기사를 다 읽은 뒤 읽기 완료를 눌러 기사와 산업 이슈를 저장합니다.
7. **내 학습 기록**에서 저장한 용어, 메모, 관련 Q&A와 기사를 다시 확인합니다.

## 저장 데이터

- 기본 위치: ./pharmamate_data/pharmamate.sqlite3
- 다른 위치를 사용하려면 .env에 PHARMAMATE_DATA_DIR을 설정합니다.
- 저장 데이터는 로컬 컴퓨터에 남습니다. 다른 컴퓨터로 옮길 때는 SQLite 파일도 함께 복사하고, 필요한 기록은 주기적으로 백업하세요.
- 같은 데이터베이스를 사용하면 기존 2.1 학습 기록을 이어서 사용할 수 있습니다. 이미 저장된 중복 기사 행은 자동으로 정리하지 않습니다.

## 개인 학습 RAG (F2)

용어, 학습 메모, 저장한 Q&A, 기사 맥락을 검색 가능한 기록으로 사용합니다. 원본은 기존 SQLite 테이블에 두고, `memory_embeddings` 테이블에는 청크별 임베딩과 원본 기록 ID를 파생 인덱스로 저장합니다. 내용이나 임베딩 모델이 바뀌면 해당 청크를 다시 임베딩하고, 삭제된 기록의 인덱스는 제거합니다. 검색은 임베딩 유사도와 단어 일치를 함께 사용하며 임베딩 API에 문제가 생기면 기존 용어 단어 검색으로 돌아갑니다.

기본 임베딩 모델은 `text-embedding-3-small`이며 `.env`의 `PHARMAMATE_EMBEDDING_MODEL`로 바꿀 수 있습니다. 새 기록과 질문 텍스트는 임베딩을 위해 OpenAI API로 전송됩니다. 앱은 현재 단일 사용자용이므로 로컬 범위(`local`)만 검색하고, 다른 소유자 범위는 세션별 저장소가 추가될 때까지 반환하지 않습니다. 벡터는 기존 SQLite 파일에 남으므로 백업 시 데이터베이스 파일을 함께 복사하세요.

합성 평가 자료로 검색 실험을 다시 실행하려면 다음을 사용합니다. 이 명령은 실제 임베딩 API를 호출하며 결과 JSONL은 Git에서 제외된 `eval/results/`에 저장됩니다.

    python eval/run_rag_experiment.py

실험 조건과 측정 결과는 [F2 실험 보고서](docs/experiments/F2_personalized_rag.md), SQLite 인덱스를 선택한 이유는 [ADR-002](docs/adr/ADR-002-sqlite-vector-index.md)에 있습니다.

## 답변 근거 검증 (F3)

Agent 답변은 생성 후 구조화된 Validator를 거칩니다. 수치·날짜는 제공 자료의 표현과 대조하고, 임상시험의 평가 목적과 실제 결과도 구분합니다. 근거가 부족하면 검증 피드백을 반영해 최대 한 번 다시 생성합니다. 수정 후에도 근거를 확인하지 못하거나 검증 호출이 실패하면 사실을 단정하지 않는 안내를 반환합니다. Gradio 답변에는 검증 상태와 수정 횟수가 표시됩니다.

Validator는 현재 답변마다 추가 모델 호출을 하므로 응답 지연과 API 비용이 늘어날 수 있습니다. 합성 평가 13건의 판정 일치율은 1.000이었고, 별도 검증 호출 지연은 p50 0.987초 / p95 1.159초였습니다. 상세 조건과 한계는 [F3 실험 보고서](docs/experiments/F3_answer_validation.md), 도입 결정은 [ADR-004](docs/adr/ADR-004-answer-validator.md)를 참고하세요.

## 터미널 답변 비교

`eval/compare_answers.py`는 동일 평가 질문을 기준선과 현재 후보에 실행해 답변, 출처, 라우트, Validator 상태, 응답 시간을 나란히 보여줍니다. 시작 전 화면 점검은 API를 부르지 않습니다.

    python eval/compare_answers.py --case-id RAG-01 --demo

실제 모델 응답을 비교하려면 의존성을 설치하고 `.env`에 OpenAI 키를 설정한 뒤 실행합니다. 실제 실행은 두 쪽에서 LLM을 호출해 API 비용이 발생할 수 있습니다.

    python eval/compare_answers.py --case-id RAG-01 --baseline-ref HEAD
    python eval/compare_answers.py --all --baseline-ref HEAD

`HEAD`는 기능 개발 직전의 승인된 커밋이어야 합니다. 기준선은 해당 커밋의 노트북을 읽고, 개선 후보는 현재 작업 트리의 노트북을 사용합니다. 새 기능이 별도 Python 모듈에 있으면 `--candidate-runner package.module:function`으로 실행기를 지정합니다. 학습 기록은 샘플 fixture만 사용하며, SQLite와 Tavily에는 접근하지 않습니다. 실제 답변 기록은 로컬 `eval/results/latest.jsonl`에 저장되고 Git에서 제외됩니다.

LangGraph Agent 그래프는 `backend/app/agents/graph.py`, 설정은 `backend/app/core/config.py`, SQLite 저장소는 `backend/app/db/repository.py`, 기사 본문 추출은 `backend/app/services/article_extraction.py`에 있습니다. 노트북은 이 모듈을 불러 기존 Gradio 화면을 연결합니다.

LangGraph 구성은 `backend/app/agents/graph.py`, 환경 설정은 `backend/app/core/config.py`, SQLite 접근은 `backend/app/db/repository.py`, 기사 본문 추출은 `backend/app/services/article_extraction.py`에 있습니다. 노트북은 이 모듈들을 불러 기존 Gradio 흐름을 연결합니다. F1은 동작을 바꾸지 않는 모듈화 단계이므로, 비교에서는 답변 변화보다 기능 회귀 여부를 확인합니다.

## F4 종합 실험 결과

원본 PharmaMate 2.2와 현재 후보를 같은 합성 질문 4건으로 비교하려면 다음을 실행합니다.

    python eval/compare_answers.py --all --baseline-ref 9814fc2

사례별 Before/After 답변, 라우트, Validator 결과, 응답 시간은 로컬 `eval/results/latest.jsonl`에 기록됩니다. 집계와 한계는 [F4 종합 평가 보고서](docs/experiments/F4_overall_evaluation.md), 발표 자료는 [PharmaMate 3.0 결과 요약](outputs/PharmaMate_3.0_Implementation_Results.pptx)에서 확인할 수 있습니다. 검색·Validator 상세 조건은 `docs/experiments/`에 기능별로 정리했습니다.

## F5 맥락 기반 후속 질문

Agent 답변과 같은 구조화 응답에서 후속 질문 3개를 생성합니다. `원리 심화`, `다른 개념과 연결`, `한계·응용 탐구` 범주마다 학습 목표를 표시하고, 버튼을 누르면 질문 입력창에 넣습니다. 최근 대화와 현재 선택 용어의 저장 메모·Q&A를 문맥으로 사용합니다. 답변 검증이 실패하거나 모델 구조화 출력에 문제가 있으면 기본 질문을 제공하고, 이전 질문과 중복되는 추천은 제외합니다.

합성 Q&A 4건의 실험에서 답변과 추천을 한 번에 생성한 방식은 두 번 나눠 생성하는 방식보다 p50 지연이 `4.38초 → 2.64초`, 토큰이 `4,903 → 3,073`, 집계 비용이 `$0.001373 → $0.000995`였습니다. 질문 4건을 한 번씩 실행한 작은 표본입니다. 실제 화면 비교와 조건은 [F5 실험 보고서](docs/experiments/F5_dynamic_followup_questions.md)에 있습니다. 재현 명령은 각각 LLM 호출과 API 비용이 발생합니다.

    python eval/run_recommendation_experiment.py
    python eval/run_recommendation_strategy_experiment.py

같은 질문에 대한 답변, 출처, Validator와 후속 질문을 터미널에서 나란히 보려면 승인된 기준선 커밋을 지정합니다.

    python eval/compare_answers.py --all --baseline-ref dc9acd8

## F6.1 FastAPI REST API

`backend/app/main.py`에서 기사 분석, Agent 답변, 학습 기록 조회·저장 API를 실행합니다. 앱 서버가 사용하는 모델과 SQLite 저장소는 첫 기능 요청에서 준비됩니다. API를 로컬 주소로 실행하세요.

    uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

- `GET /api/health`: 서버 상태
- `POST /api/articles/analyze`: 공개 기사 URL 또는 직접 붙여넣은 본문 분석
- `POST /api/chat`: 답변, 출처, Validator 결과, 후속 질문 반환
- `POST /api/chat/stream`: 진행 상태와 검증된 답변 조각을 SSE로 반환
- `GET /api/study-records`: 저장된 용어의 요약 목록
- `POST /api/study-records`: 검토한 학습 메모와 선택 용어에 관련된 Q&A 저장
- `POST /api/sessions`: 익명 학습 세션 생성 및 일회성 토큰 발급
- `GET /api/sessions/{session_id}`: 토큰으로 세션 기사·대화 복원
- `PUT /api/sessions/{session_id}/article`: 세션의 현재 기사 저장
- `POST /api/sessions/{session_id}/chat/stream`: 세션 문맥을 불러 답변하고 대화 저장
- `GET/POST /api/sessions/{session_id}/study-records`: 세션 전용 학습 기록 조회·저장
- `POST /api/sessions/{session_id}/articles/mark-read`: 읽은 기사 저장, 중복 판정, 이슈 연결
- `GET /api/sessions/{session_id}/articles`: 세션의 읽은 기사 목록
- `GET /api/sessions/{session_id}/industry-issues`: 이슈별 기사 묶음

요청·응답 스키마와 오류 형식은 FastAPI `/docs` 화면에서 확인할 수 있습니다. API 테스트는 합성 기사와 가짜 Agent로 실행해 실제 학습 DB를 열지 않습니다. 현재 API는 localhost 단일 사용자 개발용이며 로그인·세션 접근 제어는 F7 범위입니다.

스트림 이벤트는 `status`, `token`, `sources`, `recommendations`, `done`, `error`입니다. Agent의 답변 생성·Validator 처리 중 단계 상태를 전송하고, 최종 답변은 근거 검증이 완료된 뒤 작은 조각으로 전송합니다. 따라서 검증 전 초안은 브라우저에 보이지 않습니다. Vue 클라이언트 연결은 F6.3에서 제공합니다.

## F6.3 Vue 브라우저 화면

Vue 화면은 기사 입력·분석, 핵심 용어 선택, SSE 채팅, 출처·검증 결과·후속 질문 확인, 학습 메모와 관련 Q&A 저장을 한 흐름으로 연결합니다. Vite 개발 서버가 `/api` 요청을 FastAPI로 전달합니다. F7.1에서 세션 기사와 대화 복원을 추가했습니다.

의존성 설치 후 API와 화면을 각각 실행합니다.

    npm install --prefix frontend

터미널 1:

    uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

터미널 2:

    npm run dev --prefix frontend

브라우저에서 `http://127.0.0.1:5173`을 엽니다. 프로덕션 번들 점검은 `npm run build --prefix frontend`로 실행합니다. 로컬에서 사용하려면 앞서 설명한 `.env`와 Python 의존성을 준비해야 합니다.

화면과 저장 API의 변경 및 검증 조건은 [F6.3 실험 보고서](docs/experiments/F6_3_vue_frontend.md)에 기록했습니다.

## F7.1 세션 복원과 접근 범위

익명 세션마다 무작위 bearer 토큰을 발급합니다. 브라우저는 토큰을 로컬 세션 목록에 저장하고, 서버에는 토큰의 SHA-256 해시만 둡니다. 세션 ID만 알거나 다른 세션 토큰을 보내면 조회·저장할 수 없습니다. 기사, 대화, 새 Vue 학습 기록 및 임베딩은 세션 ID로 분리하며, 세션에서 검토 후 저장한 기록만 그 세션의 RAG 검색에 들어갑니다. 기존 Notebook/Gradio 기록은 보존하고 새 Vue 세션으로 자동 복사하지 않습니다.

현재 구성은 사용자 로그인 없이 `127.0.0.1`에서 실행하는 단일 사용자 개발 앱입니다. 브라우저 로컬 저장소의 bearer 토큰은 브라우저 프로필 사용자에게 접근 권한을 부여하므로 다른 사람과 프로필을 공유하지 마세요. 외부 공개 전에는 계정 인증, HTTPS, 세션 만료·회수 정책을 추가해야 합니다. 상세 설계와 테스트는 [F7.1 보고서](docs/experiments/F7_1_sessions.md)와 [ADR-001](docs/adr/ADR-001-vue-fastapi-modular-monolith.md)에 기록했습니다.

## F7.2 읽은 기사와 산업 이슈

기사를 읽은 뒤 `읽은 기사로 저장`을 누르면 현재 세션 안에 저장합니다. 정규화한 URL, 본문 SHA-256, 정규화한 제목을 비교해 중복 등록을 막습니다. 서로 다른 기사여도 회사·후보물질 등 명시된 엔티티가 겹치고, 이슈 문구·사건 유형·임상 단계의 유사도가 기준을 넘으면 같은 이슈에 자동으로 묶습니다. 단계나 후보물질이 명확히 다르면 별도 이슈로 둡니다. 자동 판정이 맞지 않으면 화면에서 저장된 이슈를 직접 선택할 수 있습니다.

읽은 기사 및 이슈 목록도 세션별로 분리합니다. 자동 판정 기준과 작은 합성 평가셋의 결과·한계는 [F7.2 실험 보고서](docs/experiments/F7_2_article_issue_management.md)에 정리했습니다.

## F8.1 Query Routing 개선

라우터는 질문에서 필요한 출처만 고르도록 경로 의미와 선택 우선순위를 명시합니다. 합성 질문 24개를 같은 `gpt-4o-mini` 설정으로 비교했을 때 경로 정확도는 `23/24 → 24/24`, p50 지연은 `1,152 ms → 1,046 ms`였습니다. 한 번씩 실행한 작은 평가이므로 실제 질의 분포의 성능을 보장하지 않으며, 토큰 절감도 확인되지 않았습니다. 조건과 한계는 [F8.1 보고서](docs/experiments/F8_1_query_routing.md), 선택 근거는 [ADR-005](docs/adr/ADR-005-query-routing.md)에 있습니다.

## F8.2 Dynamic Planning 검토

현재 복합 경로는 과거 기록과 최신 웹 검색을 모두 요청합니다. 합성 복합 질문 12개에서 현행 경로와 별도 Planner 후보가 모두 작업을 12/12 선택했습니다. Planner를 추가한 후보는 p50 `1,101 ms → 2,036 ms`, 요청당 모델 호출 `1회 → 2회`, 합산 토큰 `10,541 → 15,423`으로 늘어 채택하지 않았습니다. 실제 검색·최종 답변 품질은 평가하지 않았습니다. [F8.2 실험 보고서](docs/experiments/F8_2_dynamic_planning.md)와 [ADR-006](docs/adr/ADR-006-dynamic-planning.md)에 조건과 결정을 기록했습니다.

## F8.3 MCP Server

`backend/app/mcp_server.py`는 현재 세션의 읽기 전용 학습 자료를 MCP 호환 클라이언트에 제공합니다. Tool `search_learning_records`, `search_read_articles`; Resource `pharmamate://learning-records`; Prompt `explain_from_learning_records`를 등록합니다. 서버는 stdio 프로세스로 실행되고, 시작 시 `PHARMAMATE_SESSION_TOKEN`을 SQLite의 해시와 대조해 해당 세션에 고정합니다. 토큰이나 세션 ID를 모델이 도구 인수로 전달하지 않으며, 기록 쓰기 기능은 없습니다.

프로젝트 가상환경에 의존성을 설치하고 MCP 호스트의 로컬 설정에서 다음 실행 정보를 지정합니다. 토큰은 저장된 Vue 세션의 `access_token`이며, 아래 경로와 값은 프로젝트 환경에 맞게 바꾸고 설정 파일을 저장소에 커밋하지 마세요.

    command: /absolute/path/to/project/pharma/bin/python
    args: ["-m", "backend.app.mcp_server"]
    cwd: /absolute/path/to/project
    env:
      PHARMAMATE_SESSION_TOKEN: <현재 세션 bearer token>
      PHARMAMATE_DATA_DIR: <선택: API와 같은 데이터 폴더>

MCP 호스트가 위 명령을 stdio 서버로 실행합니다. 모듈은 API와 같은 `PHARMAMATE_DATA_DIR` 또는 `.env` 값을 읽고, 기본값은 `pharmamate_data/`입니다. 합성 SQLite로 측정한 직접 호출/MCP stdio p50은 `0.317 ms / 1.010 ms`; 30회 호출이 모두 성공하고 결과가 일치했습니다. 상세 조건과 보안 범위는 [F8.3 실험 보고서](docs/experiments/F8_3_mcp_server.md)와 [ADR-007](docs/adr/ADR-007-mcp-server.md)에 있습니다.

## 제한 사항과 향후 개선

- 뉴스 사이트의 접근 제한, 동적 페이지, 본문 구조 차이 때문에 URL 추출이 실패하거나 일부만 가져올 수 있습니다. 이때는 원문을 직접 붙여넣어 주세요.
- 기사 분석과 질문의 용어 관련성은 LLM의 판단을 사용하므로 누락이나 오판이 생길 수 있습니다. 메모를 확인한 뒤 저장하세요.
- Tavily 검색은 최신 정보를 확인하는 보조 수단입니다. 출처의 신뢰성과 맥락을 직접 확인해야 합니다.
- 세션 복원은 아직 지원하지 않습니다. 앱을 새로고침하기 전에 필요한 메모와 Q&A를 저장하세요.
- 향후에는 관심 분야별 기사 추천, 용어 재등장·오답 기반 복습, 검색 근거 검증을 개선할 수 있습니다.

## 문제 해결

- **패키지를 찾지 못함:** VS Code 커널이 .venv인지 확인하고 python -m pip install -r requirements.txt를 실행한 뒤 커널을 재시작합니다.
- **API 키 오류:** .env가 프로젝트 작업 폴더에 있는지와 키 이름을 확인하고, 설정 셀을 다시 실행합니다.
- **Gradio 화면에 접속할 수 없음:** 마지막 셀의 주소를 직접 열고, 이전 서버가 남아 있으면 종료한 뒤 UI 셀을 다시 실행합니다.
- **기사 본문이 제대로 추출되지 않음:** 기사 본문을 복사해 직접 입력합니다.
- **저장 기록이 보이지 않음:** 노트북 출력의 DB 경로를 확인합니다. 다른 작업 폴더에서 실행하면 별도 데이터베이스를 사용할 수 있습니다.
- **최신 웹 검색이 안 됨:** .env에 TAVILY_API_KEY를 입력하고 설정 셀을 다시 실행합니다.

## 의존성

requirements.txt에는 Gradio, LangChain·LangGraph, Pydantic, Tavily와 노트북 실행 패키지가 포함되어 있습니다. requests와 beautifulsoup4는 URL 기사 본문 추출에 사용하고, python-dotenv는 .env 설정을 읽는 데 사용합니다.
