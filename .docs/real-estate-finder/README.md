# real-estate-finder 입문과 코드 지도

이 디렉터리는 수집기를 처음 보는 사람이 무엇을 수집하고, 무엇을 절대로
판정하지 않으며, 어느 파일부터 고쳐야 하는지 이해하기 위한 문서다.

- [`COLLECTION.md`](COLLECTION.md): Edge/CDP부터 관심단지, 화면 필터, 묶음
  매물과 원본 행 생성까지의 수집 과정
- [`OPERATIONS.md`](OPERATIONS.md): 설치, 명령, 실행 스크립트, 로그 해석,
  장애 확인과 테스트

## 한 문장으로 정의

`real-estate-finder`는 로그인된 네이버 부동산 화면에서 본 매물을 원본에 가까운
형태로 모아 `report-site`의 JSON API로 넘기는 **수집 전용 프로세스**다.

다음 일은 이 프로젝트에서 하지 않는다.

- 가격·면적·타입·층 조건의 최종 판정
- 급매·신규 여부 결정과 알림 중복 방지
- 현재 매물 상태 또는 과거 관측 저장
- 웹 리포트·가격 통계·카카오 문구 생성과 전송

이 책임은 모두 `report-site/properties/`에 있다. 수집기에 판정 코드를 넣으면
화면, 알림, 과거 통계가 서로 다른 규칙을 쓰게 되므로 이 경계를 유지한다.

## 전체 흐름

```text
run-scan.bat
  -> run-scan.ps1
       -> GET /api/health/          서버·인증·DB 확인
       -> Edge CDP :9222 준비
       -> browser-login             네이버 로그인 확인
       -> scan-once
            -> GET /api/conditions/
            -> 관심부동산 스냅샷 1회 수집
            -> 조건별 단지 별칭 매핑
            -> 조건 안의 중복 제거
            -> POST /api/scans/
                 `-> Django가 저장·판정·알림
            -> scan.notification 출력
```

`scan-once`는 브라우저를 만지기 전에 API health를 확인한다. 데이터의 원천이
PostgreSQL로 옮겨간 뒤에는 서버가 꺼진 상태에서 로컬 파일에 임시 저장하는
정상 경로가 없다. 따라서 `report-site/run-site.bat`이 먼저 실행돼야 한다.

## 코드 지도

| 파일 | 책임 |
|---|---|
| `real_estate_finder/cli.py` | CLI 정의, 실행 잠금, 조건 조회, 수집, 중복 제거, scan POST |
| `real_estate_finder/api_client.py` | 환경변수 로드, Bearer 인증, 네 API 호출, 사람이 읽을 오류 변환 |
| `real_estate_finder/collector.py` | Playwright로 Edge와 네이버 관심부동산 화면 제어 |
| `real_estate_finder/models.py` | API에서 받는 얇은 `SearchCondition`과 보내는 원본 `Listing` |
| `real_estate_finder/parsing.py` | 화면의 가격·타입 문자열을 전송 가능한 값으로 변환 |
| `run-scan.ps1` | 서버 확인, Edge 기동, 로그인 확인, 1회 수집을 묶는 사용자 진입점 |
| `send-report.ps1` | 브라우저 없이 Django `send_digest`를 호출하는 편의 진입점 |
| `tests/` | 브라우저·네트워크 없이 파서, 병합, CLI, API 오류 계약 검증 |

## 프로세스 안의 데이터 두 종류

### `SearchCondition`

`GET /api/conditions/`에서 받는다. 수집기가 실제로 사용하는 핵심은
`id`, `complex_names`, 화면 필터에 필요한 면적과 타입이다. 가격 상한,
급매가, 저층 할인 같은 값이 API 응답에 있어도 수집기가 최종 판정하지 않는다.

### `Listing`

네이버 화면에서 읽은 매물 한 행이다.

```text
condition_id, listing_id, complex_name, building, type_name,
exclusive_area_m2, price_won, floor_text, direction,
description, url, observed_at
```

`key`는 `condition_id:listing_id`다. 같은 네이버 매물도 서로 다른 검색 조건에
속할 수 있으므로 전역 `listing_id` 하나로 중복을 판단하지 않는다.

## 실패와 상태 보호

관심부동산 목록은 한 번 읽은 스냅샷으로 모든 검색 조건을 채운다. 중간에 한
단지라도 실패하면 부분 성공으로 가장하지 않고 모든 활성 조건을
`failed_conditions`로 서버에 보낸다. 서버는 실패한 조건의 기존 `Listing`을
비활성화하지 않는다.

반대로 정상 수집에서는 모든 조건을 `successful_conditions`로 보낸다. 특정
조건에서 매물이 0건인 것도 성공한 빈 결과일 수 있으며, 이때 서버는 그 조건의
기존 활성 매물을 비활성화할 수 있다. 성공/실패 구분이 현재 상태 보존 계약이다.

## 외부 의존성

| 의존성 | 용도 | 실패 시 의미 |
|---|---|---|
| Microsoft Edge | 사용자가 로그인하는 실제 브라우저 | CDP 포트를 열 수 없음 |
| Playwright | 공개 화면 조작과 DOM 읽기 | 수집 시작 불가 |
| 네이버 로그인 | 관심부동산 접근 | 사용자가 로그인할 때까지 대기하거나 실패 |
| report-site API | 조건 조회와 결과 저장 | 브라우저를 열기 전에 중단 |
| PostgreSQL | 직접 연결하지 않고 API health를 통해 확인 | `check-api` 실패 |

수집기는 카카오 토큰이나 PostgreSQL 비밀번호를 직접 사용하지 않는다.
`FINDER_API_TOKEN`만 `report-site/.env`에서 읽어 API에 보낸다.

## 변경할 때 지킬 계약

- 현재 주 경로는 `collect_all()` → `collect_favorites_snapshot()`이다. 파일에
  남은 `_collect_condition()` 같은 예전 검색 URL 경로를 먼저 고치지 않는다.
- 비공개 API 호출, CAPTCHA 우회, 접근 제한 회피를 추가하지 않는다.
- 사용자가 띄운 외부 Edge에 연결했으면 수집 종료 시 브라우저를 닫지 않는다.
- 화면에 표시된 관심단지·매물 개수와 실제로 읽은 개수가 다르면 성공으로
  처리하지 않는다.
- 한 조건의 동일 `listing_id`는 POST 전에 한 번만 남긴다. 서버는 중복 행을
  받으면 스캔 전체를 롤백한다.
- 새 필드를 추가하면 수집기 `Listing`, 서버 API 입력과 `PropertyFields`, 관련
  테스트를 한 세트로 확인한다.
- 실제 `scan-once`, `smoke-test`는 카카오 메시지를 보낼 수 있으므로 단순 코드
  검증에 사용하지 않는다.
