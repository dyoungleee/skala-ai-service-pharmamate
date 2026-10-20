# F6.4 Vue 브라우저 E2E와 SSE 연결 복구

## 목적

FastAPI와 Vue를 연결한 사용자 흐름을 브라우저에서 확인하고, API가 스트림 도중 멈추거나 연결이 끊길 때 입력 화면이 계속 잠기지 않는지 검증한다.

## 실행 조건

| 항목 | 조건 |
|---|---|
| 실행 일자 | 2026-10-20 |
| 브라우저 | Google Chrome 155.0.8059.85, headless |
| Node.js | v26.7.0 |
| 프런트엔드 | Vite 6.4.4, `http://127.0.0.1:5173` |
| API | 실제 FastAPI 대신 Node 기반 합성 API, `http://127.0.0.1:8000` |
| SSE 유휴 제한 | 브라우저 재현용 `VITE_STREAM_IDLE_TIMEOUT_MS=1200`; 기본값 120초 |
| 기사·질문 데이터 | 가상 ADC 기사와 합성 학습 기록 |
| 외부 서비스 | OpenAI, Tavily, 사용자 SQLite 미사용 |

합성 API는 세션 생성·조회, 기사 분석, SSE 답변, 학습 기록, 읽은 기사/산업 이슈 API를 메모리에서 제공한다. 연결 종료 사례에서는 `status` SSE 이벤트를 보낸 뒤 상류 TCP 연결을 강제로 닫는다. Vite 개발 프록시를 거친 브라우저 요청이 바로 종료되지 않는 동작을 재현했다.

## 확인 결과

| 시나리오 | 결과 |
|---|---|
| 세션 생성 및 세션 기사의 분석 결과 저장 | 통과 |
| 검증된 답변·출처·후속 질문 3개 표시 | 통과 |
| 후속 질문 카드를 눌러 입력창에 질문 채우기 | 통과 |
| 학습 메모와 관련 Q&A 저장 | 통과 |
| 읽은 기사 저장 및 산업 이슈 목록 표시 | 통과 |
| 브라우저 새로고침 뒤 기사·대화·기록·이슈 복원 | 통과 |
| 서버가 보내는 SSE `error` 표시와 입력창 복구 | 통과 |
| 사용자가 스트림을 취소한 뒤 입력창 복구 | 통과 |
| `done` 없이 응답 본문이 먼저 끝난 경우 오류 표시와 입력창 복구 | 통과 |
| 상류 TCP 연결 종료 뒤 무응답 타임아웃, 오류 표시와 입력창 복구 | 통과 |
| 브라우저 JavaScript 예외 | 없음 |

Vue는 SSE에서 `done` 이벤트 없이 본문이 끝나면 불완전 응답으로 처리한다. 새 데이터가 설정된 유휴 시간 동안 오지 않는 경우에는 AbortController로 요청을 종료하고 오류를 표시한 뒤 전송 입력을 다시 활성화한다. 기본 유휴 제한은 모델 요청 제한보다 여유 있는 120초이며, E2E에서는 `VITE_STREAM_IDLE_TIMEOUT_MS=1200`으로 줄여 같은 동작을 짧게 확인했다.

```text
backend: PYTHONDONTWRITEBYTECODE=1 ./pharma/bin/python -m unittest discover -s backend/tests -v
result: 37 tests passed

frontend: npm run build --prefix frontend
result: Vite production build passed

browser: Chrome + Vite + synthetic Node API
result: all listed flows passed; no browser runtime exceptions
```

![E2E 종료 후 스트림 시간 초과 안내](assets/F6_4_browser_e2e.png)

## 한계

- 모델 답변의 실시간 품질·TTFT·토큰/비용은 측정하지 않았다. 응답과 데이터는 합성 API가 제공했다.
- 브라우저 E2E는 프런트엔드, Vite 프록시, API 형식 간 연결을 확인한다. 실제 FastAPI와 OpenAI/Tavily를 연결한 외부 서비스 E2E와 실제 사용자 데이터 검증은 포함하지 않는다.
- Vite 개발 프록시에서 상류 연결이 닫힌 뒤 브라우저 응답이 즉시 끝나지 않는 경우를 유휴 타임아웃으로 처리했다. SSE 자동 재접속은 구현하지 않았으며, 사용자는 질문을 다시 전송해야 한다.
