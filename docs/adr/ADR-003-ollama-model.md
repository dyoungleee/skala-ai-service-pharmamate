# ADR-003: 현행 OpenAI 모델과 Ollama 로컬 모델

- 상태: OpenAI 유지, Ollama 도입 보류
- 날짜: 2026-10-20

## 배경

PharmaMate의 Agent 라우팅, 답변·후속 질문 생성, Validator는 LangChain의 Pydantic 구조화 출력을 사용한다. 로컬 개발 장비에 Ollama와 Qwen3 모델이 설치되어 있어 기존 구조와 연결되는지 확인했다.

## 검토한 대안

1. 기존 `gpt-4o-mini` 설정 유지
2. 기존 OpenAI 호환 LangChain client에 Ollama endpoint와 모델을 연결
3. 기본 모델을 로컬 Ollama로 교체

## 결정

1번을 유지한다. 같은 24개 질문과 집중형 라우팅 프롬프트 비교에서 `qwen3:0.6b`는 9/24 (37.5%), p50 1.388초였고 `gpt-4o-mini`는 24/24, p50 1.046초였다. `qwen3:8b`는 세 구조화 schema smoke에서 파싱됐지만 각 호출은 21.3~33.0초였고 전체 질문셋은 평가하지 않았다. 라우팅·답변·검증을 거치는 현재 요청에 도입할 품질·지연 근거가 부족하다. 런타임은 OpenAI provider만 지원하며 모델 교체에 따른 최종 답변 품질 회귀도 검증하지 않았다.

## 결과와 제약

현재 실행 동작과 비교 기준선을 보존한다. 이 수치는 각 schema를 1회씩 실행한 smoke test이며 실제 요청 분포의 품질 비교가 아니다. Ollama CLI `0.40.6`과 실행 중인 서버 `0.33.0` 사이 버전 경고가 있었으므로, 버전을 맞춘 뒤 구조화 파싱과 지연을 재검증할 수 있다. 실험 조건은 [F8.5 보고서](../experiments/F8_5_ollama_compatibility.md)에 기록했다.
