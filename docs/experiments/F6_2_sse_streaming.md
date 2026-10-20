# F6.2 FastAPI SSE 스트리밍 구현·검증

## 동작

`POST /api/chat/stream`은 요청을 LangGraph Agent에 전달하고 `text/event-stream`으로 다음 이벤트를 보냅니다.

| 이벤트 | 내용 |
|---|---|
| `status` | 질문 분류, 학습 기록/웹 검색, 답변 생성, 근거 검증 단계 |
| `token` | 검증 완료된 답변의 텍스트 조각 |
| `sources` | 답변 출처 목록 |
| `recommendations` | 학습 목표별 후속 질문 3개 |
| `done` | 라우트, Validator 상태와 수정 횟수 |
| `error` | 스트림 중 처리 오류 |

Agent가 답변을 만드는 동안 `status`를 전송합니다. 초안은 근거 검증 전까지 보류하고 Validator가 확정한 최종 답변만 작은 조각으로 보냅니다. 사용자는 검증 상태와 단계 변화를 먼저 보고, 검증이 끝나면 답변이 점진적으로 표시됩니다. 답변 출처·추천 질문·최종 상태는 그 뒤에 전송합니다.

Vue에서는 `fetch()`의 `ReadableStream`으로 POST SSE를 읽어야 합니다. 브라우저 `EventSource`는 POST 요청 본문을 보낼 수 없어 이 API와 맞지 않습니다. 연결 재개를 위한 SSE `id`/`retry`는 구현하지 않았으며, 클라이언트가 연결이 끊긴 경우 새 요청을 시작해야 합니다.

## 검증

- `POST /api/chat/stream` 응답의 MIME 타입이 `text/event-stream`인지 확인
- `status → token → sources → recommendations → done` 순서와 이벤트 본문 확인
- 가짜 Agent가 내보낸 `DRAFT_UNVALIDATED` 조각은 최종 SSE에 포함되지 않고, 검증된 답변만 전달되는지 확인
- 전체 `unittest` 27개 통과
- 실제 LLM 호출이나 개인 SQLite 데이터는 사용하지 않음

## 한계

- 답변 텍스트 조각은 모델 토큰 생성 중에 바로 노출하지 않고 검증 후 보냅니다. 이 선택은 검증 실패 초안의 노출을 막지만, 답변 내용의 첫 글자는 Agent·Validator 처리가 끝난 뒤 도착합니다. 그 전에는 진행 상태 이벤트만 실시간으로 표시됩니다.
- 실측 TTFT 및 실제 브라우저 연결 끊김/재요청은 F6.3 화면 연결 뒤 검증할 예정입니다.
