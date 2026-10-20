# F6.3 Vue 브라우저 화면 및 학습 기록 저장

## 목표

Notebook/Gradio와 별도로 사용할 수 있는 Vue 화면을 만들고, FastAPI 기사 분석·SSE 채팅·학습 기록 API를 연결한다. 사용자가 저장 버튼을 누를 때 선택 용어와 관련성이 확인된 대화만 해당 용어 기록에 연결한다.

## 구현

- `frontend/`에 Vue 3와 Vite 앱, `/api` 개발 프록시, 반응형 스타일을 추가했다.
- 기사 URL 또는 직접 붙여넣은 본문을 분석하고, 요약·산업 이슈·핵심 용어를 표시한다.
- SSE `status`, `token`, `sources`, `recommendations`, `done`, `error` 이벤트를 처리한다. 실행 중 중단할 수 있고, 검증된 답변만 화면에 출력한다.
- 답변의 선택 용어 관련성 판단을 SSE 완료 이벤트에 포함했다. 저장 요청은 현재 선택 용어에 관련 있는 Q&A만 연결한다.
- `POST /api/study-records`로 검토한 메모와 Q&A를 SQLite 저장소에 기록한다.
- 저장 API 테스트는 repository 함수를 mock 처리해 실제 사용자 SQLite 파일을 열지 않는다.

## 검증

| 검증 | 결과 |
|---|---|
| `PYTHONDONTWRITEBYTECODE=1 ./pharma/bin/python -m unittest discover -s backend/tests -v` | 28개 테스트 통과 |
| `npm run build --prefix frontend` | Vite production build 통과; JS 82.37 kB, CSS 13.47 kB (gzip 전) |
| 저장 API 테스트 | 관련으로 표시한 Q&A만 현재 용어에 연결되는 것 확인 |

브라우저의 실제 LLM 응답과 사용자 DB를 사용하는 전체 시나리오는 실행하지 않았다. F7에서 세션 영속화 및 접근 범위를 추가한 뒤 재접속 흐름까지 확인한다. 화면 코드는 production build로 컴파일을 확인했다.

## 사용 방법

Python 의존성과 `.env`를 준비한 뒤 API와 화면을 두 터미널에서 실행한다.

```bash
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
npm install --prefix frontend
npm run dev --prefix frontend
```

Vite 주소는 `http://127.0.0.1:5173`이다. 재접속 후 대화 복원, 사용자 인증 및 다중 사용자 범위는 구현되지 않았다. 현재 로컬 단일 사용자 앱으로만 사용한다.

## 비용·한계

- 기사 분석, Agent 답변, 임베딩은 설정된 OpenAI API를 호출하고 사용량 비용이 발생할 수 있다.
- SSE는 LangGraph 진행 상태를 먼저 보내고 답변 생성과 Validator가 끝난 뒤에 검증된 답변을 보낸다. 토큰이 생성되는 즉시 전달되는 형태는 아니다.
- 사용자 브라우저의 실시간 종단 간 확인은 이 실험에서 수행하지 않았다.
