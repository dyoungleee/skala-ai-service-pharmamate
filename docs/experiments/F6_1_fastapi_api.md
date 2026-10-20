# F6.1 FastAPI REST API 구현·검증

## 범위

- FastAPI 엔트리포인트: `backend.app.main:app`
- `GET /api/health`: API 프로세스 상태
- `POST /api/articles/analyze`: URL/본문 입력, 구조화 기사 분석, 기사 ID 반환
- `POST /api/chat`: 현재 기사·용어·대화 이력을 Agent에 전달하고 답변·출처·Validator·추천 질문 반환
- `GET /api/study-records`: SQLite 학습 용어 요약 목록
- localhost Vue 개발 서버만 CORS 허용. Uvicorn 실행도 기본 안내에서 `127.0.0.1`에 바인딩

기존 Notebook에 `ui_analyze_article()`가 호출하는 `analyze_article()` 정의가 없던 점을 확인했다. 기사 분석 Pydantic 스키마와 프롬프트를 공용 backend 서비스로 옮겨 Notebook과 API가 같은 함수를 사용하도록 연결했다.

## 실행

```bash
python -m pip install -r requirements.txt
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

OpenAI 키 설정은 첫 분석·질문·기록 요청 때 확인한다. 상태 확인 경로는 LLM 설정이나 DB를 초기화하지 않는다. `/docs`에서 로컬 OpenAPI 스키마를 볼 수 있다.

## 검증

- `python -m unittest discover -s backend/tests -v`: 26개 통과
- API 테스트는 TestClient와 가짜 모델·Agent를 사용했다. 실제 SQLite와 외부 LLM을 사용하지 않는다.
- 기사 입력 검증: 붙여넣기 본문 분석 응답과 기사 ID, 빈 입력 422 오류
- 채팅 API: 입력 이력 전달, Validator 상태, 후속 질문 3개 반환
- Notebook의 기사 분석·질문·화면 셀 AST 구문 검사 통과
- `git diff --check` 통과

## 한계와 다음 단계

이 기능 단계에서는 API를 로컬 단일 사용자 환경으로 제한했다. 요청별 로그인, 세션 복원과 소유권 검사는 아직 없다. 응답은 `POST /api/chat` 완료 후 한 번에 반환하며 SSE는 F6.2에서 구현한다. API 테스트에 모델 실측 지연은 포함하지 않았다. 기사를 분석해도 저장하지 않으며, 사용자가 읽기 완료·학습 기록 저장을 선택하는 흐름은 기존 Notebook에 있다.
