# F9-17 기사 본문 경계 수정

## 문제

뉴시스 기사에서 넓은 `[itemprop="articleBody"]` 컨테이너를 먼저 선택해 제목, 등록·수정 시각, 공유 메뉴가 본문에 들어왔다. 다른 페이지 형태에서는 부제목과 사진 설명, 추천 기사, 발행사 표기가 섞였다.

## 변경

- 실제 기사 문단을 담은 안쪽 `article` 또는 `.article-cont`를 바깥 컨테이너보다 먼저 선택한다.
- `summury`와 `box-summury`를 부제목 표시로 인식해 `subtitle`에 분리한다.
- 추천 기사와 광고 영역, 발행사 꼬리말을 제외한다.
- 본문 맨 앞에 제목과 정확히 같은 독립 행이 남은 경우에만 제거한다.

## 확인 결과

대상: `https://www.newsis.com/view/NISX20260929_0003806482`

| 페이지 형태 | 수정 전 본문 길이 | 수정 후 본문 길이 | 확인 |
| --- | ---: | ---: | --- |
| `www.newsis.com` | 805자 | 693자 | 첫 실제 문단부터 마지막 인용 문단까지 유지 |
| `nwww.newsis.com` | 861자 | 693자 | 동일한 본문 문단 유지 |

수정 후 두 형태 모두 제목, 등록·수정 시각, 공유 메뉴, 부제목의 독립 행, 사진 설명, 이메일 보호 문구, 추천 기사, 발행사 꼬리말이 본문에 없었다. 부제목은 별도 `subtitle` 필드에 저장됐다.

검증: `pharma/bin/python -m unittest backend.tests.test_article_extraction`에서 12개 테스트 통과, `pharma/bin/python -m unittest discover -s backend/tests -p 'test_*.py'`에서 전체 72개 테스트 통과. 실제 문단과 부제목의 표현이 겹쳐도 본문 문장을 유지하는 기존 테스트도 통과했다. 재시작한 API의 `/api/health` 응답은 `status: ok`였다.
