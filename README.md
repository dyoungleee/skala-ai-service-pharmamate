# PharmaMate 3.0

제약·바이오 기사를 읽고, 핵심 용어를 이해하고, AI Agent와 질문을 주고받으며 학습 내용을 기록하는 서비스입니다. **사용자는 Vue 3 웹 화면으로 접속하고, FastAPI와 LangGraph가 기사 분석과 AI 응답을 처리합니다.**

## 실행하기: Vue 웹 화면

### 준비물

- Python 3.11 이상
- Node.js 20 이상
- OpenAI API 키
- Tavily API 키는 최신 웹 검색을 사용할 때만 필요합니다.

### 1. Python 환경과 패키지 준비

프로젝트 루트에서 기존 `pharma` 가상환경을 사용할 수 있습니다. 아직 환경이 없다면 다음처럼 만듭니다.

```bash
python3.11 -m venv pharma
source pharma/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

Windows PowerShell에서는 다음 명령을 사용합니다.

```powershell
py -3.11 -m venv pharma
.\pharma\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt
```

### 2. 환경 변수 설정

프로젝트 루트에 `.env` 파일을 만들고 필요한 값을 입력합니다.

```dotenv
OPENAI_API_KEY=여기에_OpenAI_API_키
TAVILY_API_KEY=여기에_Tavily_API_키_선택
PHARMAMATE_MODEL=gpt-4o-mini
PHARMAMATE_EMBEDDING_MODEL=text-embedding-3-small
# 저장 위치를 바꾸려는 경우에만 설정합니다.
# PHARMAMATE_DATA_DIR=/원하는/절대/경로
```

`OPENAI_API_KEY`는 기사 분석과 AI 답변에 필요합니다. `TAVILY_API_KEY`가 없으면 최신 웹 검색 기능은 사용할 수 없습니다. `.env`와 API 키는 Git에 올리지 마세요. 모델 호출에는 API 사용료가 발생할 수 있습니다.

### 3. FastAPI 백엔드 실행

첫 번째 터미널에서 가상환경을 활성화한 뒤 프로젝트 루트에서 실행합니다.

```bash
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

서버 상태는 [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health), API 문서는 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)에서 확인할 수 있습니다.

### 4. Vue 화면 실행

두 번째 터미널에서 프로젝트 루트 기준으로 실행합니다. 프런트엔드 패키지는 처음 한 번 설치하거나 `package-lock.json`이 바뀌었을 때 설치합니다.

```bash
npm ci --prefix frontend
npm run dev --prefix frontend
```

터미널에 표시된 주소 또는 [http://127.0.0.1:5173](http://127.0.0.1:5173)을 브라우저에서 엽니다. Vite 개발 서버가 `/api` 요청을 FastAPI(`127.0.0.1:8000`)로 전달합니다.

## 주요 기능

- 기사 URL 또는 직접 입력한 본문 분석
- 기사 읽기 → AI Tutor → 내 학습 기록 단계별 이동
- 기사 전체 원문 우선 표시와 핵심 용어 새 용어/복습 용어 하이라이트
- 기사 요약, 산업 이슈, 기업·기술 및 핵심 용어 확인
- 원문을 읽으면서 핵심 용어 학습
- 기사와 학습 기록을 바탕으로 한 AI 질문 및 답변
- 답변 근거 검증, 출처 표시, 학습 목적별 후속 질문 추천
- 익명 세션의 기사·대화 복원과 세션별 학습 기록 저장
- 읽은 기사 저장 및 관련 산업 이슈 관리
- MCP 호스트에서 현재 세션의 학습 기록과 읽은 기사 검색

## 구성

```text
Vue 3 + Vite (frontend/)  →  FastAPI + SSE (backend/app/main.py)
                                  ├─ LangGraph Agent 및 답변 검증
                                  ├─ 기사 추출·분석과 개인 학습 검색
                                  └─ SQLite 세션·학습 기록 저장
```

- `frontend/`: Vue 3 브라우저 UI
- `backend/app/`: FastAPI, Agent, 기사 처리, 검색, 세션 및 SQLite 저장소
- `eval/`: 평가 데이터와 답변 비교·기능 실험 실행기
- `docs/experiments/`: 기능별 실험 조건, 결과 및 한계
- `docs/adr/`: 기술 결정과 선택 근거
- `outputs/`: PharmaMate 3.0 구현 결과 발표 자료

학습 기록과 세션은 기본적으로 프로젝트의 `pharmamate_data/pharmamate.sqlite3`에 저장됩니다. 데이터는 로컬에 보관되며, `.env`에서 `PHARMAMATE_DATA_DIR`을 지정해 위치를 바꿀 수 있습니다. 브라우저에 저장된 세션 토큰을 가진 브라우저 프로필이 해당 세션에 접근할 수 있습니다.

## 테스트와 답변 비교

백엔드 테스트:

```bash
python -m unittest discover -s backend/tests -v
```

Vue 프로덕션 빌드 확인:

```bash
npm run build --prefix frontend
```

터미널에서 합성 사례의 비교 화면을 확인하려면:

```bash
python eval/compare_answers.py --case-id RAG-01 --demo
```

기준선과 현재 답변을 실제 모델로 비교하려면 API 키를 설정한 뒤 실행합니다. 모델 호출 비용이 발생하며, 결과는 Git에서 제외된 `eval/results/`에 저장됩니다.

```bash
python eval/compare_answers.py --all --baseline-ref 9814fc2
```

## 기존 노트북과 2.0 기준선

`PharmaMate_2_0.ipynb`는 **Vue 서비스에 접속하기 위한 파일이 아닙니다.** 기존 답변을 재현하는 비교 기준선과 노트북 호환성 회귀 테스트에서 참조하므로 저장소에 유지합니다. 3.0 웹 앱은 위의 FastAPI와 Vue 실행 절차로 시작합니다. 기존 Gradio 동작을 확인해야 할 때만 노트북을 별도로 실행하면 됩니다.

기준선 비교 코드가 이 노트북을 읽으므로 `requirements.txt`에도 노트북·Gradio 실행 의존성이 포함되어 있습니다. 2.2 기준선과 각 기능 실험의 조건·결과는 `docs/experiments/`에 남겨 두었습니다.

## 문서

- [3.0 개발 계획](docs/PharmaMate_3.0_Development_Plan.md)
- [Vue 브라우저 화면 실험](docs/experiments/F6_3_vue_frontend.md)
- [브라우저 E2E 검증](docs/experiments/F6_4_browser_e2e.md)
- [세션 복원 및 접근 범위](docs/experiments/F7_1_sessions.md)
- [단계별 학습 화면과 원문 용어 하이라이트](docs/experiments/F9_1_learning_flow_ui.md)
- [직접 추가 용어 분류](docs/experiments/F9_13_manual_term_classification.md)
- [넓은 화면 학습 레이아웃](docs/experiments/F9_14_wide_learning_layouts.md)
- [기사 부제목 분리 및 분석 문맥 반영](docs/experiments/F9_15_article_subtitle_separation.md)
- [전체 평가 결과](docs/experiments/F4_overall_evaluation.md)
- [3.0 구현 결과 발표 자료](outputs/PharmaMate_3.0_Implementation_Results_F8.pptx)

기존 실행 방식과 기록된 실험을 보존해 기능 비교가 가능하도록 했습니다. 서비스 이용의 기본 경로는 Vue 웹 화면입니다.
