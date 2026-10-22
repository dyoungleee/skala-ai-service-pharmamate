# EVIDENCE-01 동일 입력 실제 비교 실행

## 터미널 실행 캡처

아래는 평가 명령을 실행한 Terminal.app 창을 직접 캡처한 이미지입니다. stderr 경고는 별도 임시 파일로 보냈고, 화면에는 실제 비교 명령과 stdout 결과가 보입니다.

![Terminal.app에서 실행한 EVIDENCE-01 비교 결과](F8_before_after_terminal.png)

## 실행 조건

- 실행일: 2026-10-22 (KST)
- 기준선: PharmaMate 2.2 노트북, Git commit `9814fc2`
- 후보: PharmaMate 3.0 FastAPI/LangGraph 그래프, 앱 코드 기준 commit `49bc1b2`
- 모델: `gpt-4o-mini`, temperature 0.2
- 입력: `eval/cases.jsonl`의 합성 사례 `EVIDENCE-01`
- 질문: 아래 기사에 나온 임상 결과와 확인되지 않은 내용을 구분해서 설명해줘.
- 기사 fixture: 초기 임상시험의 안전성·내약성 평가 목적은 있으나 유효성 결과·성공률은 없다는 가상 자료
- 외부 검색·운영 DB·개인 학습 기록: 사용 안 함
- 출력: 아래 실제 Terminal.app 창 캡처. 실행 JSONL은 로컬 `/tmp/EVIDENCE-01_terminal_capture_final.jsonl`에 저장
- 실행 명령: `./pharma/bin/python -B eval/compare_answers.py --case-id EVIDENCE-01 --baseline-ref 9814fc2 --results /tmp/EVIDENCE-01_terminal_capture_final.jsonl`

## 결과

| 항목 | 2.2 기준선 | 3.0 후보 |
|---|---:|---:|
| 라우트 | `article` | `article` |
| Validator | 미적용 | `insufficient_evidence` |
| 답변 수정 횟수 | 0회 | 1회 |
| 응답 시간 | 4.77초 | 15.78초 |
| 토큰 / API 비용 | 미측정 | 미측정 |

기준선은 기사에 적힌 시험 목적과 미보고 결과를 설명했습니다. 3.0 후보는 Validator 재작성 1회 후 안전성·내약성 목적만 확인되고 유효성 결과는 없다고 답했습니다. 실행 기록에 토큰 사용량이나 제공자 비용이 없어 두 값은 미측정입니다.

## 해석과 한계

- 동일한 질문·기사 fixture와 `gpt-4o-mini` 설정으로 한 차례 비교했습니다. 응답 시간은 이 실행에서 2.2가 4.77초, 3.0이 15.78초였습니다. 3.0은 라우팅·답변 검증·추천 생성 단계를 거쳤으며, 단일 실행만으로 일반적인 지연 증가 폭을 추정할 수 없습니다.
- 합성 사례 하나이므로 실제 제약 기사나 사용자 질문의 답변 품질을 대표하지 않습니다.
- LLM 호출은 실제로 수행됐으며 공급자 사용료가 발생할 수 있습니다. 비교기는 사용량·비용 메타데이터를 저장하지 않았습니다.
- 실행 도중 Pydantic serializer 경고가 stderr에 출력됐지만 실행은 완료됐습니다. 캡처는 비교 결과 stdout만 담습니다.
- 평가 실행기 후보는 현재 3.0 백엔드 그래프를 사용하며, 노트북은 기준선으로만 사용합니다.
