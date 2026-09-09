# report-site 입문과 애플리케이션 구성

이 디렉터리는 Django 애플리케이션을 처음 보는 사람이 데이터가 어디에
저장되고, 판정·리포트·통계·카카오 전송이 어떻게 연결되는지 이해하기 위한
문서다.

- [`DATA_AND_RULES.md`](DATA_AND_RULES.md): PostgreSQL 모델, 스캔 트랜잭션,
  조건 판정, 급매·신규 정책과 통계 모집단
- [`API_AND_DELIVERY.md`](API_AND_DELIVERY.md): finder API 계약, Bearer 인증,
  카카오 문구·버튼·라이브 확인과 실패 기록
- [`OPERATIONS.md`](OPERATIONS.md): 환경설정, PostgreSQL, 서버, admin, 관리
  명령, 공개 경로, 테스트와 장애 확인

## 한 문장으로 정의

`report-site`는 수집 원본과 현재 매물 상태를 PostgreSQL에 저장하고, 조건과
알림을 판정하고, 웹 리포트와 가격 통계를 렌더링하며, 카카오톡 메시지까지
보내는 **전체 애플리케이션**이다.

`real-estate-finder`는 로그인된 네이버 화면을 읽어 JSON으로 전달할 뿐이다.
매물의 의미를 결정하는 코드는 이 프로젝트의 `properties/`에 둔다.

## 앱 세 개의 경계

```text
real-estate-finder
       |
       | Bearer JSON
       v
api/                 수집기 전용 경계
       |
       v
properties/          도메인과 PostgreSQL
       |
       +--> report/  공개 화면과 운영 요약
       `--> kakao-notifier/ 외부 모듈
```

| 앱 | 책임 | 넣지 않는 것 |
|---|---|---|
| `properties/` | 모델, 판정, 상태 갱신, 통계 계산, 표현 payload, 전송 조정 | HTTP 화면 라우팅 |
| `api/` | Bearer 인증, JSON 검증·직렬화, 도메인 호출 | 조건 판정과 메시지 문구 |
| `report/` | DB 조회, 질의 파라미터 해석, HTML 렌더링, 운영 상태 조회 | 수집 원본 저장 |

프로젝트 설정과 최상위 URL은 `report_site/`에 있다.

## 요청과 데이터 흐름

```text
POST /api/scans/
  -> JSON 형식 검증
  -> record_scan() [한 DB 트랜잭션]
       -> Scan 생성
       -> 모든 원본 Observation 저장 + 제외 사유
       -> 통과분 Listing upsert
       -> 성공한 조건의 사라진 Listing 비활성화
       -> 신규·급매 알림 대상 결정
  -> 트랜잭션 커밋
  -> DeliveryService
       -> 현재 DB로 메시지 구성
       -> 공개 report의 data-observed-at 확인
       -> 카카오 전송 또는 텍스트 폴백
  -> JSON 응답
```

저장과 전송은 같은 HTTP 요청 안에서 동기로 일어나지만 같은 트랜잭션은 아니다.
DB 커밋이 먼저여야 공개 리포트가 방금 수집한 시각을 보여 줄 수 있고, 그래야
카카오 버튼이 붙는다.

## 코드 지도

### 프로젝트 설정

| 파일 | 책임 |
|---|---|
| `report_site/settings.py` | `.env`, PostgreSQL, 경로 prefix, 공개 URL, static, Dagster/Airflow 조회 설정 |
| `report_site/urls.py` | 고정 `/api/`와 선택 prefix 아래 비-API 경로 연결 |
| `report_site/wsgi.py` | waitress WSGI 진입점 |
| `run-site.ps1` | check, migration 확인, collectstatic, waitress 기동 |
| `ensure-site.ps1` | 스케줄러가 health 확인 후 서버를 숨김 프로세스로 기동 |

### 도메인 `properties/`

| 파일 | 책임 |
|---|---|
| `models.py` | 공통 규칙, 조건, 스캔, 원본 관측, 현재 매물, 알림 실패 |
| `matching.py` | 단지·면적·타입·층·가격 판정과 안정적인 제외 코드 |
| `scanning.py` | `record_scan()` 트랜잭션과 신규·급매 결정 |
| `report.py` | 웹과 카카오가 공유하는 가격·규칙·매물 표시 payload |
| `statistics.py` | 일별 호가 표본, 요약, SVG 좌표, 표 데이터 |
| `notifier.py` | 카카오 텍스트 제한과 매물 문구, 외부 모듈 어댑터 |
| `delivery.py` | 라이브 버튼, 텍스트 폴백, digest, 실패 기록 |
| `publish.py` | 공개 HTTPS와 `data-observed-at` 최신성 확인 |
| `admin.py` | 운영자가 조건과 결과를 다루는 Django admin |

### HTTP `api/`와 `report/`

| 파일 | 책임 |
|---|---|
| `api/auth.py` | 상수 시간 비교를 사용하는 Bearer 인증 |
| `api/views.py` | health, conditions, scans, digest JSON 경계 |
| `report/views.py` | 매물, 통계, Airflow/Dagster 요약 뷰 |
| `report/stats_params.py` | 사람이 입력한 기간·지역·단지를 안전하게 해석 |
| `report/templates/report/index.html` | 현재 활성 매물 리포트 |
| `report/templates/report/stats.html` | JS 없는 inline SVG 가격 통계 |
| `report/dagster_client.py` | 로컬 Dagster GraphQL 읽기 전용 조회 |

## 경로 구조

`REPORT_PATH_TOKEN`이 비어 있는 기본 구성은 다음과 같다.

| 경로 | 처리자 | 접근 |
|---|---|---|
| `/api/health/`, `/api/conditions/`, `/api/scans/`, `/api/digest/` | Django API | Bearer 토큰 |
| `/property/report/` | Django | 공개 |
| `/property/statistics/` | Django | 공개 |
| `/property/airflow/` | Django | staff 로그인, 현재 전환 계획 보류 상태의 요약 |
| `/common/dagster/` | Django | staff 로그인 |
| `/common/dagster/console/` | Dagster 직접 프록시 | 현재 Django 인증 없음 |
| `/admin/` | Django admin | staff 로그인. 두 서비스 공용이라 namespace 밖에 둔다. 옛 `/property/admin/`·`/stock/admin/`은 여기로 리다이렉트 |

토큰을 채우면 비-API 경로에만 `/<TOKEN>`이 붙는다. `/api/`는 URL이 바뀌지
않고 계속 Bearer 토큰으로 보호된다. 실제 토큰은 문서나 Git에 남기지 않는다.

## 화면은 빌드 결과물이 아니다

리포트와 통계는 요청마다 PostgreSQL을 읽어 Django template으로 렌더링한다.
프런트엔드 빌드나 배포 단계가 없고, 새 스캔 뒤 새로고침하면 데이터가 바뀐다.
다만 Python 또는 template 코드를 수정했다면 실행 중인 waitress가 옛 코드를
들고 있으므로 `run-site.bat`을 재시작해야 한다.

이전 Next.js/Codex Sites UI는 운영 경로에서 은퇴한 뒤 저장소에서도 제거했다.
현재 화면 구현은 이 Django 프로젝트만 소유한다.

## 데이터베이스 역할

PostgreSQL은 단순 캐시가 아니라 애플리케이션의 원천이다.

- `Observation`: 스캔에서 본 원본 전량과 당시 판정 결과
- `Listing`: 조건을 통과한 매물의 현재 상태
- `Scan`: 실행 성공 여부, 집계, 알림 결과 또는 미전송 이유
- `SearchCondition`, `GlobalRule`: 운영 중인 설정
- `NotificationFailure`: 카카오 실패 진단

Dagster의 실행 이력은 같은 DB의 별도 `dagster` schema에 있다 — 스케줄러
자체 이력일 뿐 매물 데이터가 아니고, Django 모델은 그 schema를 보지 않는다.

## 핵심 불변 조건

- 운영 검색 조건은 DB와 Django admin이 원천이다. seed YAML은 최초 이관용이다.
- 받은 원본은 조건 탈락 여부와 무관하게 `Observation`으로 보존한다.
- 실패한 조건 때문에 기존 활성 매물을 비활성화하지 않는다.
- 저장 트랜잭션을 커밋한 다음 메시지를 보낸다.
- 공개 리포트가 현재 수집 시각을 서빙할 때만 카카오 링크 버튼을 붙인다.
- 카카오 공개 URL에 `localhost`나 `127.0.0.1`을 쓰지 않는다.
- 리포트의 `data-observed-at` 속성은 `publish.py`와 맺은 계약이다.
- 표시 문구는 `properties/report.py`와 `notifier.py`에 모아 웹과 카카오의
  의미가 갈라지지 않게 한다.
