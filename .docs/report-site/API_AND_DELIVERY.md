# 수집기 API와 카카오 전송

## API 경계

모든 수집기 API는 `/api/` 아래에 있고 `Authorization: Bearer <token>`을
요구한다. `api/auth.py`는 scheme을 대소문자 구분 없이 확인하고 토큰은
`secrets.compare_digest()`로 비교한다. 실패 응답은 401과
`WWW-Authenticate: Bearer`를 반환한다.

사이트 전체가 Tailscale Funnel로 공개되면 `/api/`도 인터넷에서 닿는다.
`REPORT_PATH_TOKEN`은 API에 적용되지 않으므로 `FINDER_API_TOKEN`이 필수
보안 경계다.

## 엔드포인트

| 경로 | 방식 | 역할 | 성공 |
|---|---|---|---|
| `/api/health/` | GET | Django, 인증, PostgreSQL 연결 확인 | 200 |
| `/api/conditions/` | GET | 공통 규칙과 활성 검색 조건 직렬화 | 200 |
| `/api/scans/` | POST | 원본 저장, 판정, 상태 갱신, 필요 시 카카오 전송 | 201 |
| `/api/digest/` | POST | 현재 활성 매물 전체 카카오 전송 | 200 |

허용하지 않은 방식은 405와 `Allow` 헤더를 반환한다. POST는 JSON 전용이며
`Content-Type: application/json`이 아니면 400이다. Bearer 요청은 브라우저
form이 아니므로 두 POST만 `csrf_exempt`다.

## 조건 응답

`GET /api/conditions/`는 `global_rule`과 `conditions`를 반환한다. 조건에는
finder가 단지 매핑과 화면 필터에 쓰는 값뿐 아니라 서버가 판정에 쓰는 가격과
알림 설정도 포함된다. 이 직렬화가 수집기의 `SearchCondition.from_api()`와
맞아야 한다.

`GlobalRule(pk=1)`이 없으면 503 `configuration_missing`, DB 조회 실패는
503 `database_error`다.

## scan 요청 계약

개념적인 요청 형태는 다음과 같다.

```json
{
  "started_at": "timezone-aware ISO datetime",
  "finished_at": "timezone-aware ISO datetime",
  "observations": [
    {
      "condition_id": "condition-slug",
      "listing_id": "article-id",
      "complex_name": "단지명",
      "building": "동",
      "type_name": "84A",
      "exclusive_area_m2": 84.97,
      "price_won": 2300000000,
      "floor_text": "10/25층",
      "direction": "남향",
      "description": "화면 설명",
      "url": "https://new.land.naver.com/...",
      "observed_at": "timezone-aware ISO datetime"
    }
  ],
  "successful_conditions": ["condition-slug"],
  "failed_conditions": {},
  "notify_urgent": true,
  "smoke": false
}
```

검증 규칙:

- `observations`는 객체 배열이다.
- 성공 조건은 문자열 배열, 실패 조건은 문자열→문자열 객체다.
- 성공과 실패 조건은 겹칠 수 없다.
- observation의 `condition_id`는 성공 조건 중 하나여야 한다.
- 한 스캔·조건 안의 `listing_id`는 중복될 수 없다.
- 시작·종료·관측 시각과 면적·가격·매물 ID가 유효해야 한다.
- `notify_urgent`, `smoke`는 boolean이다.

형식 오류는 400 `invalid_request`, DB 오류는 503 `database_error`다.

## scan 응답과 동기 전송

성공 응답에는 `scan` 집계와 실제 `alerts`의 조건 ID, 매물 ID, 급매·신규
플래그가 들어간다. `record_scan()`이 커밋된 뒤 같은 요청 안에서
`DeliveryService`가 메시지를 보낸다.

카카오 전송까지 포함되므로 finder의 scan timeout은 600초다. 전송이 실패하면
DB에 저장된 Scan은 남아 있고 API는 502 `notification_failed`를 반환한다.
가능하면 응답에 저장된 scan 정보도 포함해 “저장은 됐지만 알림이 실패함”을
구분한다.

## 메시지 구성

현재 카카오는 PNG 이미지를 보내지 않는다. 텍스트 한 통과 최대 두 버튼을
사용한다.

```text
[가격 통계 요약]
[급매/신규 또는 전체 매물 목록]

버튼 1: 통계 보기
버튼 2: 전체 매물 보기
```

`properties/notifier.py`가 카카오 텍스트 제한 안에서 매물 줄을 만들고,
`properties/delivery.py`가 어떤 목록과 버튼을 보낼지 결정한다. 실제 OAuth,
토큰 갱신과 API 호출은 형제 디렉터리 `kakao-notifier/`를 동적으로 불러 사용한다.

## 버튼의 라이브 조건

버튼은 URL 설정만 되어 있다고 붙지 않는다.

1. 보낼 매물 중 가장 최신 `observed_at`을 구한다.
2. `KAKAO_REPORT_URL`이 loopback이 아닌 공개 HTTPS인지 확인한다.
3. 공개 리포트 HTML을 가져온다.
4. `data-observed-at="..."` 값을 읽는다.
5. 두 시각이 같은 순간일 때만 통계와 매물 버튼을 붙인다.

공개 사이트가 꺼져 있거나 어제 데이터를 보여주면 깨진·낡은 링크보다 텍스트만
보내는 쪽을 선택한다. `report/templates/report/index.html`의
`data-observed-at` 속성 이름을 바꾸면 이 검사가 실패해 버튼이 사라진다.

통계 URL은 `KAKAO_REPORT_URL`의 origin을 유지하고 path만 현재
`STATISTICS_URL_PATH`로 바꿔 만든다. 두 버튼은 같은 서버의 최신성을 공유하므로
하나의 리포트 확인으로 함께 붙거나 함께 빠진다.

## 전송 모드

### 스캔 알림

`send_scan_alerts()`는 전체 조건 충족 목록으로 최신 시각과 버튼을 계산하지만,
본문에는 실제 급매·신규 alert만 넣는다. 완료 문구를 `Scan.notification`에
갱신한다.

### smoke

성공했고 조건 충족 매물이 있으면 전체 목록을 보낸다. 실패나 빈 결과면 조회
요약 텍스트를 보내 전송 경로 자체를 검증한다. 실제 외부 메시지가 나가므로
자동 테스트 대용으로 실행하지 않는다.

### digest

`active=True`이고 조건도 활성인 현재 매물 전체를 보낸다. 활성 매물이 0건이면
빈 보고 텍스트를 전송한다. 웹 서버는 필요 없지만 DB와 카카오 인증은 필요하다.
사이트 최신성 검사를 통과하지 못하면 버튼 없이 텍스트로 전송한다.

### scheduler 실패 알림

`manage.py send_alert`가 일반 텍스트 앞에 경고 표시를 붙여 보낸다. Dagster가
카카오 토큰을 직접 다루지 않고 이 명령을 호출하므로 인증과 실패 기록이 한
곳에 남는다.

## 실패 기록

어떤 카카오 전송도 예외가 나면 `NotificationFailure`에 메시지, 공개 URL, 오류,
시각을 저장한다. Scan과 연결된 알림이면 `Scan.notification`도 실패 문구로
바꾼다. 그 뒤 `DeliveryError`를 다시 올리므로 호출자가 성공으로 오해하지 않는다.

확인 순서:

1. Django admin의 Notification failure와 Scan
2. 카카오 토큰 파일과 갱신 오류
3. 카카오 개발자 콘솔의 웹 도메인 등록
4. `KAKAO_REPORT_URL`과 선택 경로 token의 일치
5. `manage.py check_report`로 공개 사이트 시각 확인

등록하지 않은 카카오 웹 도메인은 카카오가 링크를 다른 주소로 바꿀 수 있다.
공개 호스트를 바꿀 때는 환경변수뿐 아니라 개발자 콘솔도 함께 갱신한다.
