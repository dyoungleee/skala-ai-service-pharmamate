# F4 종합 평가 — PharmaMate 2.2 → 3.0 후보

## 실행 조건

- 실행일: 2026-10-20 (KST)
- 기준선: `9814fc2` (원본 PharmaMate 2.2)
- 후보: `3114e86` (F3 Validator 오탐 수정까지 반영한 3.0 후보)
- 모델: `gpt-4o-mini`, temperature 0.2. 기준선·후보의 모델 설정은 동일
- 사례: `RAG-01`, `EVIDENCE-01`, `GENERAL-01`, `RAG-SEM-01` 합성 질문 4건
- 실행 명령: `./pharma/bin/python eval/compare_answers.py --all --baseline-ref 9814fc2`
- 격리: 평가 fixture만 전달. 개인 SQLite, 사용자 학습 기록, Tavily에 접근하지 않았다. CLI가 토큰·비용을 반환하지 않아 미측정

## 사례별 결과

| 사례 | 기준선 라우트·시간 | 후보 라우트·시간 | Validator | 핵심 확인 |
|---|---|---|---|---|
| `RAG-01` ADC 기록 | memory · 2.86초 | memory · 4.29초 | pass · 수정 0회 | 후보가 ADC 기록을 source ID와 함께 반환 |
| `EVIDENCE-01` 임상 근거 | article · 3.19초 | article · 6.15초 | pass · 수정 1회 | 평가 목적과 실제 임상 결과를 구분하고, 미보고 결과를 명시 |
| `GENERAL-01` 일반 개념 | memory · 4.79초 | memory · 5.11초 | pass · 수정 0회 | 안정적인 개념 설명을 출처 부재만으로 차단하지 않음 |
| `RAG-SEM-01` 표현이 다른 검색 | memory · 2.33초 | memory · 3.64초 | pass · 수정 0회 | ADC 메모를 top-3 안에서 검색하고 답변에 연결 |

네 사례 모두 후보에서 정상 답변을 반환하고 Validator가 `pass`로 끝났다. `EVIDENCE-01`은 첫 답변 검증에서 한 번 고친 뒤 통과했다.

## 함께 확인한 기능 지표

- 개인 학습 검색: 합성 기록 14개·질의 20개에서 Recall@3 `0.950 → 1.000`, MRR `0.925 → 0.942`. 후보 질의 지연 p50 `0.160초`, p95 `0.184초`; 최초 인덱스 생성 `0.67초`
- 답변 검증: 합성 판정 사례 13건 중 기대 분류 `13/13` 일치. 근거 없는 답변 통과 `0/6`, 근거 있는 답변 차단 `0/7`. 단일 Validator 호출 p50 `0.987초`, p95 `1.159초`
- 자동 테스트: `unittest` 16개 통과. 임시 SQLite와 가짜 모델을 사용

## 해석과 한계

답변 비교 시간은 서로 다른 4개 질문을 각각 한 번씩 실행한 결과다. 후보의 응답 시간이 모두 더 길게 측정됐지만 표본이 작고 LLM 응답 변동이 있어 성능 결론으로 일반화하지 않는다. Validator는 추가 모델 호출을 하고, 재작성 사례에서는 더 많은 호출이 필요해 지연과 비용이 증가한다. API가 토큰·비용 수치를 제공하지 않았다.

`RAG-SEM-01`에서는 관련 ADC 메모와 함께 바이오시밀러·CAR-T 기록도 출처 목록에 들어왔다. 검색 Recall@3은 맞췄지만 top-3 출처 정밀도는 더 개선해야 한다. 인덱스와 현재 데이터 범위는 단일 로컬 사용자다. 실제 기록의 검색 품질, 사용량별 성능, 외부 API 데이터 처리와 다중 사용자 격리는 후속 검증 대상이다.

## 구현 범위와 다음 단계

F0 비교 CLI, F1.1 Agent 그래프 분리, F1.2 코어 모듈화, F2 개인 학습 RAG, F3 근거 Validator는 기능별 커밋으로 `main`에 푸시했다. 현재 구조는 Gradio를 유지하면서 Python 모듈을 나눈 단일 백엔드 프로세스다. FastAPI/SSE/Vue, 세션 복원, 동적 후속 질문, 기사·이슈 관리, 선택 기술 비교는 개발 계획의 다음 기능 단위다.

실행·설계 세부 내용은 각 [F0](F0_answer_comparison.md), [F1.1](F1_1_agent_modularization.md), [F1.2](F1_2_core_modularization.md), [F2](F2_personalized_rag.md), [F3](F3_answer_validation.md) 보고서에 있다.
