# F9.7 기사 저장 완료 문구 간소화

## 변경

- 기사와 산업 이슈 저장 성공 응답을 `기사와 산업 이슈를 저장했습니다.`로 고정했습니다.
- 이슈 제목과 요약은 저장 데이터 및 내 학습 기록의 이슈 목록에 계속 보존하되, 저장 완료 안내 뒤에는 덧붙이지 않습니다.
- 자동 이슈 연결 및 신규 이슈 저장 응답이 모두 고정 문구인지 API 회귀 테스트로 확인했습니다.

## 검증

```bash
PYTHONDONTWRITEBYTECODE=1 ./pharma/bin/python -m unittest backend.tests.test_api.ApiTests.test_read_articles_dedupe_copies_and_group_issues_conservatively -v
```

결과: 기사 저장·중복 판정·이슈 연결 테스트 통과.
