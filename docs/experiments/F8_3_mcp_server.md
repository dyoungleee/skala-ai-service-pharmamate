# F8.3 MCP Server 실험 및 구현

## 질문과 조건

PharmaMate의 학습 검색을 호환 MCP 클라이언트에서 재사용할 수 있는지 확인했다. 공식 Python SDK의 stdio 전송으로 서버를 별도 프로세스에 실행하고, 합성 학습 기록 하나를 격리된 임시 SQLite에 넣었다.

- 직접 호출과 MCP Tool 모두 `search_learning_records_for_session`의 같은 검색 동작을 사용
- MCP stdio 클라이언트 세션을 한 번 연결한 뒤 동일 검색을 30회 호출
- 프로세스 시작 시간은 지연 측정에서 제외
- 토큰 검증·Tools/Resources/Prompts 탐색과 세션 격리는 별도 통합 테스트에서 확인
- 재현: `python eval/run_mcp_experiment.py`

## 결과

| 측정값 | Python 함수 직접 호출 | MCP stdio Tool |
|---|---:|---:|
| p50 검색 지연 | 0.317 ms | 1.010 ms |
| 도구 호출 성공 | — | 30/30 |
| 직접 결과와 MCP 결과 일치 | — | 예 |
| 서버가 노출한 기능 | — | Tool 2개, Resource 1개, Prompt 1개 |

MCP 프로토콜 경계는 이 fixture에서 p50 약 0.693 ms를 더했다. 프로세스 시작은 포함되지 않는다. 도구는 개인 학습 기록/Q&A/읽은 기사 검색과 읽은 기사 제목·이슈 검색이며, Resource는 세션 학습 자료를 JSON으로 읽고 Prompt는 기록을 바탕으로 답변하도록 안내한다.

## 구현과 결정

표준 도구·리소스·프롬프트를 제공하고자 공식 MCP Python SDK를 채택했다. MCP 서버는 stdio로 실행하며 시작 시 `PHARMAMATE_SESSION_TOKEN`을 검증해 서버 프로세스를 한 세션에 묶는다. 검색 요청은 도구 인수로 세션 ID나 토큰을 받지 않고, 다른 세션 ID를 선택할 수 없다. 기록을 변경하는 도구는 제공하지 않는다.

테스트는 임시 DB의 서로 다른 두 세션을 만들어 유효·무효 토큰 처리와 세션 간 메모 누출 여부를 확인했다. SDK in-memory 클라이언트에서 Tool, Resource, Prompt 목록과 동작을 검사했고, 별도 프로세스 stdio 연결에서도 올바른 세션 자료만 반환하는지 검증했다.

## 한계

성능 값은 로컬 SQLite의 작은 합성 fixture, 한 장비, 30회에서 측정했다. 네트워크 기반 Streamable HTTP, 다른 MCP 호스트, 대용량 기록, 실제 사용자 작업은 측정하지 않았다. stdio 프로세스가 받은 세션 권한은 그 프로세스 수명 동안 유지되므로 세션을 바꾸면 MCP 호스트가 프로세스를 다시 시작해야 한다. SDK의 transport 모델은 [공식 Python SDK 문서](https://py.sdk.modelcontextprotocol.io/run/)에 설명되어 있다.
