# 프로젝트 아키텍처와 코드 탐색 가이드

이 문서는 에이전트가 저장소 전체를 읽지 않고도 현재 구조를 이해하고, 작업에 필요한 파일만 선택하도록 돕는 상세 지도다. 현재 운영 상태와 최근 결과는 `../PROJECT_STATE.md`, 사람이 실행하는 절차는 `RUNBOOK.md`를 기준으로 한다.

## 1. 한눈에 보는 구조

```text
사용자 (run-scan.bat)
        |
        v
real-estate-finder            수집 전용. 판정하지 않는다
  Edge CDP -> 관심부동산 스냅샷
        |
        +-- GET  /api/conditions/   어느 단지가 어느 조건인지
        +-- POST /api/scans/        수집한 매물 전량
        |
        v
report-site                   애플리케이션 (Django + PostgreSQL)
  properties/  도메인: 모델, 판정, 카드, 카카오 전송, admin, 관리 명령
  api/         경계:   finder 전용 JSON (Bearer 토큰)
  report/      화면:   공개 HTML 리포트
        |
        +--> PostgreSQL (원본 관측 전량 + 현재 매물 상태)
        +--> kakao-notifier -> 카카오톡 카드
        +--> tailscale funnel -> 공개 HTTPS 주소
```

**역할 경계가 이 프로젝트의 핵심 설계다.** `real-estate-finder`는 네이버에서 본 것을 그대로 넘기고, 그 뒤의 모든 판단은 `report-site`가 한다. 어떤 매물이 조건에 맞는지, 급매인지, 신규인지, 카카오톡을 보낼지, 화면에 어떻게 보일지는 전부 Django 쪽이다.

이 경계의 실질적 결과: **스캔은 리포트 서버 실행을 요구한다.** 데이터가 갈 곳이 없기 때문이다. `run-scan.ps1`은 브라우저를 열기 전에 `/api/health/`를 확인하고 실패하면 멈춘다.

## 2. 저장소 경계

```text
outputs/
├── .agent/
│   ├── PROJECT_STATE.md       # 최신 운영 상태와 주요 결정
│   └── docs/
│       ├── ARCHITECTURE.md    # 이 문서: 구조와 코드 탐색 지도
│       ├── README.md          # 문서 색인
│       └── RUNBOOK.md         # 사람이 실행하는 운영 절차
├── real-estate-finder/        # 수집기 (Python, Playwright/Edge CDP)
├── report-site/               # 애플리케이션 (Django + PostgreSQL)
├── kakao-notifier/            # 독립 실행 가능한 카카오 API 모듈
├── property-report-site/
│   └── site-app/              # 은퇴한 UI. 별도 Git 저장소, 참고용으로만 보존
├── .env                        # KAKAO_REPORT_URL (공유, Git 제외)
├── load-env.ps1                # 위 .env를 여러 PS 스크립트가 공유하는 헬퍼
├── AGENTS.md                   # 모든 코딩 에이전트의 공통 규칙
└── README.md                   # 사용자용 짧은 소개
```

`property-report-site/site-app/`은 루트 Git이 gitlink로 추적하는 별도 Git 저장소다. 서빙 경로에서 은퇴했고 코드가 이를 참조하지 않는다. 다시 건드릴 일이 생기면 중첩 저장소에서 먼저 커밋한 뒤 루트에서 포인터 변경을 커밋한다. 루트에서만 diff를 보면 내부 변경이 아니라 포인터 변경만 보인다.

## 3. 수집기

경로: `real-estate-finder/`

| 파일 | 책임 | 언제 읽는가 |
|---|---|---|
| `run-scan.bat` / `run-scan.ps1` | 서버 확인 → Edge 실행/확인 → 로그인 확인 → `scan-once` | 사용자 실행 실패, 브라우저 시작 |
| `send-report.bat` / `send-report.ps1` | `report-site`의 `manage.py send_digest` 호출 | 전체 결과 즉시 전송 |
| `real_estate_finder/cli.py` | 명령 정의, 수집 실행, API 전달, 실행 잠금 | 실행 흐름 파악, 새 명령 |
| `real_estate_finder/api_client.py` | `report-site` API 호출과 오류 문구 | 서버 연결 문제 |
| `real_estate_finder/collector.py` | 로그인된 Edge를 Playwright CDP로 제어해 관심부동산에서 매물 수집 | 수집 실패, 화면 변경 |
| `real_estate_finder/models.py` | `SearchCondition`(API 응답), `Listing`(원본 행), `iso_now` | 전달 형식 변경 |
| `real_estate_finder/parsing.py` | 화면 텍스트 → 숫자 (`parse_price_won`, `normalize_type_name`) | 가격/타입 표기 변경 |

여기에는 조건 판정, 상태 저장, 표현 포맷, 카카오 전송 코드가 **없다**. 그런 작업이라면 `report-site/properties/`를 봐야 한다.

### 실행 경로

```text
cli.main (scan-once)
  -> ReportSiteClient.health()          서버가 없으면 여기서 중단
  -> ReportSiteClient.conditions()      -> SearchCondition.from_api
  -> run_lock()                         data/run.lock, 중복 실행 방지
  -> NaverBrowserCollector.collect_all(conditions)
       -> collect_favorites_snapshot()
          -> 로그인 확인 -> 네이버 홈에서 부동산 -> 관심부동산
          -> 단지 목록 확인 -> 화면 필터 -> 묶음 펼치기/스크롤 -> 매물 파싱
       -> 단지 별칭으로 조건에 매핑 (condition.complex_names)
  -> _deduplicate()                     한 조건 안의 중복 제거
  -> ReportSiteClient.post_scan(...)    서버가 저장·판정·전송까지 수행
  -> 응답의 scan.notification 출력
```

수집 불변 조건:

- 비공개 API를 직접 호출하거나 접근 제한을 우회하지 않는다.
- CAPTCHA, 로그인 만료, 비정상 접근 화면을 만나면 중단한다.
- 외부 Edge CDP가 기본이며, 수집 종료 시 사용자의 브라우저를 닫지 않는다.
- 관심단지 화면이 표시한 단지 수와 읽은 단지 수가 다르면 성공으로 처리하지 않는다.
- 묶음 매물의 대표 링크는 최저가를 우선하고, 같은 가격이면 매물번호가 큰 최신 링크를 택한다.
- **한 조건 안에서 같은 매물을 두 번 보내지 않는다.** 서버가 중복을 거부하면서 스캔 전체를 롤백한다.
- 수집은 한 번의 관심부동산 스냅샷이므로 실패는 전체 실패다. 그 경우 모든 조건을 `failed_conditions`로 올려 서버가 기존 매물을 비활성화하지 않게 한다.

`collector.py`는 크므로 작업별로 다음 구간만 우선 찾는다.

- CDP/로그인: `open_login`, `_verify_login`, `_wait_for_login`
- 전체 수집: `collect_all`, `collect_favorites_snapshot`
- 관심단지 탐색: `_open_favorites`, `_favorite_complexes`, `_collect_favorite_complex`
- 화면 필터: `_apply_screen_filters`, `_select_trade_type`, `_select_similar_exclusive_area`
- 스크롤/묶음: `_collect_complex_cards`, `_expand_listing_groups`, `_merge_article_rows`
- 원시 텍스트 변환: 파일 하단의 `_extract_*`, `_parse_favorite_listing_text`

`_collect_condition()`과 `_navigate_with_visible_ui()` 같은 예전 단지별 검색 경로가 남아 있다. 현재 `collect_all()`은 이 경로를 호출하지 않는다. 수집 버그를 조사할 때 호출 관계를 확인하지 않고 예전 경로부터 수정하지 않는다.

### 명령

| 명령 | 부작용 |
|---|---|
| `check-api` | 서버 health와 활성 조건 출력. 읽기 전용 |
| `browser-login` | Edge 로그인 상태 확인, 필요하면 사용자 로그인 대기 |
| `collect-favorites` | 브라우저 수집 후 `data/favorites-latest.json`만 저장. 서버 전송 없음 |
| `scan-once` | 수집 후 서버에 전달. 서버가 급매·신규가 있으면 카카오톡 전송 |
| `smoke-test` | 수집 후 전달하되 급매 알림 이력을 소모하지 않고 전체 카드 전송 |

`scan-once`와 `smoke-test`는 외부 카카오 메시지를 보낼 수 있다. 단순 코드 검증을 위해 임의로 실행하지 않는다.

## 4. 애플리케이션

경로: `report-site/`

Django + PostgreSQL + waitress. 앱 세 개로 b/e와 f/e를 나눈다.

| 파일/경로 | 책임 |
|---|---|
| `report_site/settings.py` | PostgreSQL, admin 배선, whitenoise, 필수 토큰 두 개, 루트 `.env`까지 로드 |
| `report_site/urls.py` | `r/<TOKEN>/` 리포트, `r/<TOKEN>/admin/` admin, `api/` 수집기 API |
| `run-site.ps1`, `run-site.bat` | `check` → `migrate --check` → `collectstatic` → waitress `127.0.0.1:8000` |

### properties — 도메인 (b/e)

| 파일 | 핵심 |
|---|---|
| `models.py` | `GlobalRule`(단일 행), `SearchCondition`, `Scan`, `Observation`, `Listing`, `NotificationFailure`. `PropertyFields`가 관측과 매물의 공통 필드를 담는다 |
| `matching.py` | `explain_condition`, `matches_condition`, `parse_floor`, `parse_price_won`, `normalize_type_name` |
| `scanning.py` | `record_scan()` — 저장과 판정을 한 트랜잭션으로. `ScanDecision`, `AlertDecision`, `_no_alert_reason` |
| `report.py` | `build_report_payload`, `price_text`, `rule_text` — 카드와 웹 리포트가 함께 쓰는 표현 |
| `card.py` | `render_card_html`, `render_card_png`, `build_card_image` — 자기완결형 HTML을 임시 headless Edge로 PNG 렌더링 |
| `notifier.py` | `format_eok`, `batch_listing_message`, `card_heading`, `card_caption`, `KakaoNotifier` 어댑터 |
| `publish.py` | `is_live`, `describe_live`, `is_public_report_url` — 공개 URL이 이번 조회를 서빙 중인지 확인 |
| `delivery.py` | `DeliveryService` — 카드 전송, 텍스트 폴백, 실패 기록 조정 |
| `admin.py` | 조건 편집과 수집 결과 조회 화면 |
| `seed/searches.yaml` | 최초 시드. **운영 소스가 아니다** — 조건은 DB에 있고 admin에서 고친다 |
| `management/commands/` | `import_searches`, `import_state`, `send_digest`, `preview_card`, `check_report` |

`record_scan()`의 순서가 업무 규칙 전체다.

1. `Scan`을 만들고 수집 매물을 **전량** `Observation`으로 저장한다 (조건 통과 여부 무관).
2. 단지명 별칭으로 조건에 매핑하고 `explain_condition()`을 실행해 탈락 사유를 `Observation.exclusion_reason`에 남긴다.
3. 통과분은 `Listing`에 upsert한다. `first_seen_at`은 보존하고 `last_seen_at`과 가격 등을 갱신한다.
4. `is_urgent` = 가격이 유효 급매가 이하. `is_new` = 기존 행 없음.
5. `should_alert` = 급매이면서 이전에 알린 적이 없거나 그보다 **더 내려간** 경우. `notify_new` 조건은 신규도 알림 대상.
6. **수집에 성공한 조건에 한해서만** 이번에 안 보인 매물을 `active=False`로 바꾼다.
7. 여기까지가 하나의 트랜잭션이다. 커밋이 끝나야 리포트가 이번 조회를 서빙하고 `is_live()`가 통과한다.
8. 커밋 후 전송한다. 보내지 않았다면 그 사유를 `Scan.notification`에 기록한다.

저층은 표시용 값이 아니다. `matching.py`가 층을 판정하고, `GlobalRule.low_floor_price_discount_won`을 조사 가격과 급매 가격에서 차감한 유효 임계값을 매물에 넣는다. 가격 규칙을 바꿀 때는 `models.py`와 `matching.py`를 함께 읽는다.

### api — 경계 (b/e)

| 파일 | 책임 |
|---|---|
| `auth.py` | `Authorization: Bearer <FINDER_API_TOKEN>` 상수 시간 비교 |
| `views.py` | `health`, `conditions`, `scans`, `digest` |
| `urls.py` | `/api/` 아래 네 경로 |

사이트가 Tailscale Funnel로 인터넷에 열려 있으므로 `/api/`도 외부에서 닿는다. 인증은 선택이 아니다. Bearer로 인증된 POST는 CSRF 토큰 없이 쓴다(`csrf_exempt`).

`POST /api/scans/`는 `record_scan()` 트랜잭션이 끝난 뒤 **같은 요청 안에서 동기로** 카드를 전송한다. 큐가 없는 대신 요청이 수 초~수십 초 걸린다. 클라이언트 타임아웃은 600초다.

### report — 화면 (f/e)

| 파일 | 책임 |
|---|---|
| `views.py` | 활성 조건·활성 `Listing` 조회 → `build_report_payload` → 렌더. `Cache-Control: no-store` |
| `templates/report/index.html` | 마크업 + 인라인 CSS/SVG. 정적 파일 없음 |

템플릿의 `data-observed-at` 속성은 `properties/publish.py`의 정규식이 긁는 계약이다. 이름을 바꾸면 카카오 카드에서 `전체 매물 보기` 버튼이 조용히 사라진다.

활성 매물이 없으면 성공한 조건이 하나라도 있었던 최근 `Scan` 시각을 대신 쓴다.

## 5. 카카오 모듈

경로: `kakao-notifier/`

| 파일 | 책임 |
|---|---|
| `auth.py` | OAuth 인증 코드 수신, 최초 토큰 발급과 저장 |
| `common.py` | `.env` 로드, form/multipart HTTP 요청 공통 코드 |
| `kakao_notifier.py` | 토큰 갱신, 이미지 업로드, feed/text 템플릿 전송, CLI |
| `.env`, `data/kakao-token.json` | 앱 키·시크릿·토큰. Git 제외 |

`report-site/properties/notifier.py`가 이 모듈을 패키지 의존성이 아니라 파일 경로에서 동적으로 불러온다. 결합 지점은 `send_to_me(message, link_url)`와 `send_card_to_me(image_path, title, description, link_url, width, height)` 두 함수다.

카카오 feed 카드의 이미지 URL은 카카오 이미지 업로드 API의 원본 URL이다. 등록되지 않은 도메인은 카카오가 조용히 다른 주소로 치환할 수 있으므로, URL을 바꿀 때는 `.env`만 고치고 끝내지 말고 카카오 개발자 콘솔의 웹 도메인도 함께 확인한다.

## 6. 작업별 최소 읽기 경로

모든 작업은 먼저 `../PROJECT_STATE.md`를 읽는다.

| 작업 | 먼저 읽을 파일 | 관련 검증 |
|---|---|---|
| 검색 단지/가격/스케줄 변경 | Django admin이 먼저. 스키마를 바꿔야 하면 `properties/models.py` | `properties/tests/test_models.py` |
| 조건에서 매물이 빠지는 이유 | admin의 `Observation.exclusion_reason` 필터, `properties/matching.py` | `properties/tests/test_matching.py` |
| 신규/급매 중복 알림 | `properties/scanning.py`, `properties/models.py` | `properties/tests/test_scanning.py` |
| 카카오 문구·카드 디자인 | `properties/notifier.py`, `properties/card.py` | `test_card.py`, `manage.py preview_card` |
| 카드 전송·폴백·실패 기록 | `properties/delivery.py` | `properties/tests/test_delivery.py` |
| 리포트 표시 로직 | `properties/report.py` | `report/tests/test_views.py` |
| 웹 리포트 화면 디자인 | `report/templates/report/index.html` | `manage.py test`, 육안 확인 |
| 라우팅/토큰/설정 | `report_site/settings.py`, `urls.py`, `.env` | `manage.py check` |
| 수집기 API 호출 문제 | `real_estate_finder/api_client.py`, `cli.py` | `tests/test_api_client.py`, `check-api` |
| 네이버 로그인/CDP 문제 | `run-scan.ps1`, `collector.py`의 로그인 메서드 | 브라우저 수동 확인 |
| 관심단지/카드 수집 문제 | `collector.py`의 현재 주 경로와 하단 파서 | `tests/test_core.py` |
| 카카오 OAuth/토큰/API | `kakao-notifier/`의 세 모듈 | `test_kakao_notifier.py` |
| 공개 링크 라이브 확인 | `properties/publish.py`, `manage.py check_report` | `properties/tests/test_publish.py` |
| 외부 공개(Tailscale Funnel) | `RUNBOOK.md`, `report-site/run-site.ps1` | 수동 확인 (휴대폰 LTE 등) |

다음은 보통 처음부터 읽지 않는다.

- `collector.py` 전체: 관련 메서드부터 좁혀 읽는다.
- `property-report-site/site-app/` 전체: 은퇴했고 코드가 참조하지 않는다.
- `node_modules/`, `.next/`, `dist/`, `.venv/`, `__pycache__/`, `staticfiles/`: 생성 결과물.
- `real-estate-finder/project_state.md`: 과거 문맥. 최신 공통 상태는 `.agent/PROJECT_STATE.md`가 우선이다.

## 7. 검증 범위

```powershell
# 애플리케이션 전체 (모델, 판정, 카드, 전송, API, 리포트)
cd report-site
..\real-estate-finder\.venv\Scripts\python.exe manage.py check
..\real-estate-finder\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
..\real-estate-finder\.venv\Scripts\python.exe manage.py test

# 수집기
cd ..\real-estate-finder
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# 카카오 모듈
cd ..\kakao-notifier
..\real-estate-finder\.venv\Scripts\python.exe -m unittest -v test_kakao_notifier.py
```

`manage.py test`는 테스트 DB를 만들므로 `property_report` 역할에 `CREATEDB`가 필요하다. 평소에는 꺼 두고 테스트할 때만 부여한 뒤 되돌린다(`PROJECT_STATE.md` 참고).

실제 네이버 수집과 카카오 전송은 외부 상태와 사용자 계정에 영향을 준다. `scan-once`, `smoke-test`, `send_digest`를 임의로 실행하지 않는다.

## 8. 변경 시 지켜야 할 경계

- **수집기에 판정을 되돌려 놓지 않는다.** 조건, 급매, 신규, 표현, 전송은 전부 `report-site`다.
- 비밀정보는 `.env`(루트와 `report-site/`), 카카오 토큰 파일, 브라우저 프로필 밖으로 복사하거나 문서화하지 않는다.
- 런타임 데이터와 생성 결과물을 Git에 추가하지 않는다.
- 상태 저장(트랜잭션 커밋)이 전송보다 먼저다. 순서가 바뀌면 `is_live()`가 항상 실패해 `전체 매물 보기` 버튼이 매번 빠진다.
- 카카오 공개 링크에 `localhost`나 `127.0.0.1`을 넣지 않는다. `is_public_report_url()`이 이를 거부한다.
- 리포트 서버 시각 검증 없이 `전체 매물 보기` 버튼을 강제로 넣지 않는다.
- 수집 실패 시 기존 매물을 전부 비활성화하지 않는다.
- 알림 렌더링 실패가 급매 알림 유실로 이어지지 않도록 텍스트 폴백을 유지한다. 텍스트마저 실패하면 `NotificationFailure`에 남기고 오류를 올린다.
- 카카오를 보내지 않는 모든 경로는 사유를 남긴다. 조용한 종료는 실패와 구분되지 않는다.
- `data-observed-at` 속성 이름을 바꾸지 않는다.
- `build_report_payload`는 숫자 매물번호 + `/articles/` 직접 링크만 포함한다. 묶음 카드의 해시 id가 리포트에서 빠지는 것은 의도된 동작이다.
- 검색 조건 스키마를 바꾸면 `properties/models.py`, `import_searches`, `api/views.py`의 조건 직렬화, 수집기의 `SearchCondition.from_api`를 함께 확인한다.
- `property-report-site/site-app/`을 건드릴 일이 생기면 중첩 저장소와 루트 포인터의 두 커밋 경계를 지킨다.

## 9. 문서의 역할 구분

- `../PROJECT_STATE.md`: 지금 무엇이 돌고 있고 최근 결과와 결정이 무엇인지
- `ARCHITECTURE.md`: 코드가 어떻게 연결되고 어떤 작업에 어떤 파일을 읽는지
- `RUNBOOK.md`: 사람이 설치, 조회, 서버 실행, Tailscale Funnel 설정을 어떻게 하는지
- 각 하위 프로젝트 `README.md`: 해당 구성 요소의 상세 사용법

아키텍처, 저장 계층, 서빙 방식 또는 실제 주 실행 경로가 바뀌면 이 문서와 `../PROJECT_STATE.md`를 같은 작업에서 갱신한다.
