# F8.5 Ollama 호환성 확인

## 확인 환경

- Ollama CLI: `0.40.6`; 실행 중인 서버는 `0.33.0`으로 표시되어 client/server 버전 경고가 발생
- 설치된 모델: `qwen3:8b` (5.2 GB), `qwen3:0.6b` (522 MB) 등
- 호출 경로: Ollama의 OpenAI 호환 chat endpoint를 기존 `ChatOpenAI`에 연결
- 합성 프롬프트만 사용. 개인 기록·실제 기사·OpenAI API를 사용하지 않음
- 재현: Ollama 서버를 실행한 뒤 `python eval/run_ollama_smoke.py --model qwen3:8b`

## 결과

`qwen3:8b`에서 프로젝트의 구조화 스키마 호출은 모두 파싱됐다.

| 스키마 | 파싱 | 지연 |
|---|---:|---:|
| RouteDecision | 예 | 33.018 s |
| LearningTurnResponse (답변+후속 질문) | 예 | 27.853 s |
| AnswerValidation | 예 | 21.321 s |

같은 F8.1 질문 24개와 집중형 라우팅 프롬프트를 `qwen3:0.6b`에서 실행했다. 시작 warm-up은 1.713 s, 평가 p50은 1.388 s였고 9/24개(37.5%)만 기대 경로를 선택했다. 기준선 `gpt-4o-mini`는 24/24개(100%), p50 1.046 s였다. 이는 모델 선택 비교이며 아키텍처 변경 효과가 아니다. 일부 소형 모델 요청은 구조화 출력 오류도 반환했다.

최초 cold-start 단일 라우팅 호출은 8.079 s였다. `think=false` 옵션을 보낸 8B 라우팅 smoke도 36.593 s로 빨라지지 않았다.

## 결정과 한계

현재 API 런타임에 Ollama provider 선택 옵션을 추가하지 않는다. 0.6B는 기준선보다 라우팅 정확도가 낮고 p50도 더 길었다. 8B는 세 구조화 schema가 파싱됐지만 개별 요청이 21~33초로 느렸으며 전체 라우팅셋은 실행하지 않았다. Agent 질문 한 번에서 라우팅·답변·검증이 각각 호출되므로, 현재 결과로는 로컬 실행을 운영 옵션으로 채택할 근거가 부족하다.

0.6B 라우팅 평가는 유형별 6개인 합성 질문 각 1회이며 실제 사용자 요청의 분포를 대표하지 않는다. 8B의 전체 경로 정확도와 최종 답변 품질은 미측정이다. CLI/서버 버전을 맞추고 가속이 가능한 장비에서 재평가할 수 있다. OpenAI 호환 연결 방법은 [Ollama 공식 안내](https://ollama.com/blog/openai-compatibility), LangChain의 구조화 출력 인터페이스는 [LangChain 공식 참조](https://reference.langchain.com/python/langchain-ollama/chat_models/ChatOllama/with_structured_output)에 설명되어 있다.
