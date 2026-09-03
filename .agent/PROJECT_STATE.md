# Project State

마지막 갱신: 2026-09-03

## Current Architecture

- 코드 경계, 실제 데이터 흐름과 작업별 최소 읽기 경로는 `.agent/docs/ARCHITECTURE.md`에 정리되어 있다.
- `real-estate-finder/`가 네이버 부동산 매물을 수집하고 검색 조건, 급매 조건, 이전 상태를 기준으로 결과를 만든다.
- `kakao-notifier/`가 카카오 인증 토큰을 관리하고 이미지형 카카오톡 카드를 전송한다.
- `report-site/`(Django + waitress)가 `real-estate-finder/data/state.json`을 요청마다 읽어 전체 매물 웹 리포트를 렌더링한다. 빌드나 배포 단계가 없다 — 스캔이 끝나면 새로고침만으로 반영된다.
- `property-report-site/site-app/`(예전 Next.js/Codex Sites UI)은 서빙 경로에서 은퇴했다. 루트와 별도 중첩 Git 저장소이며 삭제하지 않고 참고용으로만 남겼다.
- 사용자용 조회 진입점은 `real-estate-finder/run-scan.bat` 또는 `real-estate-finder/run-scan.ps1`이며, Edge CDP `http://127.0.0.1:9222`에 연결한다.
- 급매가 아닌 전체 결과를 카카오톡으로 보내는 진입점은 `real-estate-finder/send-report.bat`이며 `send-digest`를 실행한다. 브라우저와 네이버 로그인이 필요 없다.
- 리포트 서버 실행 진입점은 `report-site/run-site.bat` 또는 `report-site/run-site.ps1`이다.
- `scan-once`는 급매 또는 신규 매물이 있을 때만 카카오톡을 보낸다. 보내지 않은 경우에도 사유를 콘솔에 출력하고 `data/scan-runs.jsonl`의 `notification` 필드에 기록한다.
- 검색 설정은 `config/searches.yaml`에 있고 런타임 데이터 및 생성 결과물은 Git에서 제외한다.
- 스캔은 `data/state.json`을 알림 전송보다 먼저 저장한다(`service.py`의 `scan()`). 그래야 카드가 `is_live()`로 리포트 서버를 확인하는 시점에 이미 이번 조회 결과가 서빙되고 있다.
- `is_live()`(`real_estate_finder/publish.py`)는 이제 빌드가 최신인지가 아니라 리포트 서버(그리고 Tailscale Funnel)가 살아있고 이번 조회를 서빙 중인지만 확인한다.
- 외부 공개는 Tailscale Funnel로 `report-site/`의 8000번 포트를 노출해 고정 HTTPS 주소(`https://<pc>.<tailnet>.ts.net`)를 얻는 방식이다. 접근 제어는 추측 불가능한 경로 토큰(`REPORT_PATH_TOKEN`)이다.
- `KAKAO_REPORT_URL`은 루트 `.env`(`load-env.ps1`이 `run-scan.ps1`/`send-report.ps1`/`report-site/run-site.ps1`에 공유)로 관리하고, `REPORT_PATH_TOKEN`은 `report-site/.env`로 관리한다. 둘 다 Git에서 제외한다.

**주의: 위 구조는 아래 "In-Flight Migration"이 끝나면 크게 바뀐다. 작업 전에 반드시 그 절을 먼저 읽는다.**

## Current State

- **Tailscale Funnel 전환은 완료됐고 종단 확인까지 끝났다.** 공개 리포트는 Funnel 주소로 서빙되며, 실제 카카오톡 카드에 `전체 매물 보기` 버튼이 새 주소로 포함되는 것까지 확인했다.
- 공개 리포트 호스트: `https://desktop-477.tailf8d9d1.ts.net` (Tailscale Funnel → 로컬 `127.0.0.1:8000` 프록시). 전체 경로는 `REPORT_PATH_TOKEN`을 포함하므로 문서에 적지 않는다 — 루트 `.env`의 `KAKAO_REPORT_URL`에 있다.
- Tailscale 설치·로그인·Funnel 활성화 완료(`tailscale funnel --bg 8000`). `tailscaled`는 Windows 서비스라 재부팅 후 Funnel 설정이 자동 복구된다.
- 카카오 개발자 콘솔의 `앱 > 제품 링크 관리 > 웹 도메인`에 위 호스트를 등록 완료. (`플랫폼 키` 메뉴가 아니다 — `kakao-notifier/README.md:31` 참고.)
- `report-site/.env`의 `REPORT_PATH_TOKEN`과 루트 `.env`의 `KAKAO_REPORT_URL` 모두 실제 값으로 채워져 있다(Git 제외).
- `check-report`로 공개 주소가 `data/state.json`의 기준 시각(`2026-09-03T08:38:55+09:00`, 활성 매물 41건)과 일치함을 확인했다.
- `send-report.ps1`로 실제 카카오톡 카드 1통(매물 41건)을 전송해 `전체 매물 보기` 버튼 동작까지 사용자가 휴대폰에서 확인했다.
- 리포트 화면은 관심 단지 6개, 확인 매물 41건, 급매 1건을 정확히 렌더링한다.
- 카카오 이미지는 카카오 이미지 업로드 API를 사용한다(변경 없음).
- 마지막 확인 시 Python 단위 테스트 81개(`real-estate-finder/tests`) 전부 통과, Django 테스트 6개(`report-site/report/tests`) 전부 통과, `manage.py check` 통과.
- PostgreSQL 서비스 `postgresql-x64-18`이 자동 시작으로 등록돼 실행 중이며, `property_report` 역할/DB 생성과 Django 마이그레이션 적용을 완료했다.
- `import_searches`와 `import_state`를 실행해 공통 규칙 1개, 검색조건 6개, 수집 실행 27개, 원본 관측 1,304개, 전체 매물 62개를 이관했다. 활성 매물 41개, 활성 급매 1개이며 `last_urgent_alert_price_won`이 있는 기존 매물 2개의 기록도 보존됐다.
- 이관 명령은 두 번 실행해 중복이 생기지 않음을 확인했다. DB 기반 Django 테스트 16개와 `manage.py check`, `makemigrations --check`가 통과했다.

## In-Flight Migration: 수집기 / 애플리케이션 역할 분리

**상태: 3단계까지 완료했다. PostgreSQL 생성·마이그레이션, admin 슈퍼유저 생성, 기존 데이터 이관이 끝났다. 다음 구현은 4단계 판정 로직 이관이다.**

### 왜

지금 `real-estate-finder`는 "조사"만 하는 게 아니라 애플리케이션 전체다. 수집(`collector.py`), 조건 필터(`parsing.py`), 급매·신규·알림 판정과 상태 diff(`service.py`), 파일 저장(`storage.py`), 표현 포맷(`report.py`), 카드 이미지(`card.py`), 카카오 전송(`notifier.py`)을 모두 소유한다. `report-site`는 DB조차 없고(`settings.py:68` `DATABASES = {}`), `sys.path`에 finder를 끼워넣어(`settings.py:23`) finder 코드를 직접 import하는 얇은 뷰 하나뿐이다.

사용자 결정: **수집과 그 외 전부를 가른다.** 수집한 데이터는 전량 DB에 넣고, 그중 조건에 맞는 것만 필터해서 보여주며, 나머지 판단도 전부 Django가 한다.

### 목표 구조

```text
real-estate-finder/            수집 전용 — 판정하지 않는다
  Edge CDP → 관심부동산 스냅샷
  ├─ GET  /api/conditions/     화면 필터·단지 매칭에 쓸 조건을 받아옴
  └─ POST /api/scans/          수집 원본 전량 업로드
        ↓ 응답: 저장·판정·전송 결과 요약

report-site/                   애플리케이션 (Django + PostgreSQL)
  properties/   b/e 도메인   models, 판정, 카드, 카카오 전송, admin, 관리 명령
  api/          b/e 경계     finder 전용 JSON 엔드포인트 (Bearer 토큰)
  report/       f/e          공개 HTML 리포트 (DB에서 조회)
        ↓
  tailscale funnel → 공개 HTTPS 주소 → 카카오톡 카드
```

### 단계별 진행 상황

- [x] 0. 이 계획을 `PROJECT_STATE.md`에 기록 — 세션이 끊겨도 이어받을 수 있게 (커밋 `b856954`)
- [x] 1. `settings.py` 재구성 + `psycopg[binary]`/`whitenoise` 추가 + admin 배선 (커밋 `a64a6dc`). PostgreSQL 기동 후 마이그레이션 적용 완료.
- [x] 2. `properties` 앱 + 모델 + 마이그레이션 + admin + `createsuperuser`
- [x] 3. `import_searches` / `import_state` 관리 명령 작성, 기존 데이터 이관 실행
- [ ] 4. `parsing.py` → `properties/matching.py`, `service.scan()` 판정부 → `properties/scanning.py` + 테스트 이관
- [ ] 5. `api` 앱 + Bearer 인증 + 엔드포인트 4개(`health`, `conditions`, `scans`, `digest`)
- [ ] 6. `report` 뷰를 DB 기반으로 전환 (템플릿 무변경)
- [ ] 7. `card.py` / `notifier.py` / `publish.py` 이관 + `send_digest`·`preview_card`·`check_report` 관리 명령
- [ ] 8. finder 축소 + `api_client.py` + `cli.py` 정리 + `run-scan.ps1` 사전 확인 + `send-report.ps1` 재연결
- [ ] 9. `ARCHITECTURE.md`, `RUNBOOK.md`, `AGENTS.md`, 각 `README.md` 갱신

각 단계 끝에서 테스트가 통과하는 상태를 유지하고, 단계를 끝낼 때마다 위 체크박스와 이 문서를 갱신한다. 삭제 범위가 크므로 단계별로 커밋을 나눈다.

### 이어받는 지점 (2026-09-03 갱신)

브랜치 `kakao-image-card`. 3단계 기존 데이터 이관과 admin 슈퍼유저 생성까지 완료했다. 다음 코드는 4단계 `matching.py`와 `scanning.py`다.

#### 1단계에서 실제로 끝난 것

- 공유 venv(`real-estate-finder/.venv`, Python 3.14.3)에 `psycopg 3.3.5` + `psycopg-binary 3.3.5`(cp314 휠) + `whitenoise 6.12.0` 설치 완료. `requirements.txt`에도 반영.
- `report-site/report_site/settings.py` 전면 재작성:
  - `DATABASES`가 PostgreSQL을 가리킨다. 비밀번호 외 전부 기본값(`property_report` / `property_report` / `127.0.0.1` / `5432`).
  - `INSTALLED_APPS`에 `django.contrib.{admin,auth,contenttypes,sessions,messages,staticfiles}` 추가. **`properties`와 `api`는 아직 없다.**
  - admin용 미들웨어 7종 + `whitenoise.middleware.WhiteNoiseMiddleware`, 템플릿 `context_processors` 3종 추가.
  - `STATIC_URL`/`STATIC_ROOT`(`report-site/staticfiles/`)/`STORAGES`(whitenoise `CompressedStaticFilesStorage` — 매니페스트 방식이 아니라 파일 하나가 없다고 리포트 전체가 죽지 않는다).
  - `_load_env()`가 **루트 `.env`도** 읽는다 → `KAKAO_REPORT_URL`이 `settings.REPORT_PUBLIC_URL`로 들어온다.
  - `FINDER_API_TOKEN`을 `REPORT_PATH_TOKEN`과 같이 필수로 요구한다(없으면 기동 실패).
  - `CSRF_TRUSTED_ORIGINS = ["https://*.ts.net"]`, `SECURE_PROXY_SSL_HEADER`. Funnel 뒤에서 admin 로그인 POST가 깨지지 않게 하기 위함.
  - `DATA_DIR = BASE_DIR / "data"` — 카드 이미지 출력 위치(7단계에서 사용).
  - **`sys.path.insert(0, FINDER_DIR)`는 아직 남겨 뒀다.** `report/views.py`가 여전히 finder의 `FileStore`를 import하기 때문이다. 6단계에서 둘을 같이 제거한다.
- `report-site/report_site/urls.py`: admin을 `r/<REPORT_PATH_TOKEN>/admin/`에 마운트. `admin.site.site_header` 등 한글 라벨 설정.
- `report-site/run-site.ps1`: `manage.py migrate --check` 실패 시 기동 거부, `collectstatic --noinput` 자동 실행, 배너에 admin 주소 출력.
- `report-site/.env.example` 갱신(`FINDER_API_TOKEN`, `POSTGRES_*` 문서화).
- `report-site/.env`(Git 제외)에 **`FINDER_API_TOKEN`을 생성해 넣었다.** `POSTGRES_PASSWORD=`는 **빈 값으로 추가돼 있다 — 사용자가 채워야 한다.**
- 루트 `.gitignore`에 `report-site/staticfiles/`, `report-site/data/` 추가.
- 검증 결과: `manage.py check` 통과, 기존 Django 테스트 6개 통과(전부 `SimpleTestCase` + `databases = set()`라 DB 없이도 돈다), `collectstatic` 127개 파일 복사 성공.

#### 2단계에서 완료한 코드

- `properties/models.py`: `GlobalRule`, `SearchCondition`, `Scan`, `Observation`, `Listing`, `NotificationFailure` 6개 모델 작성.
- `Listing`은 `(condition, listing_id)` unique 제약을 사용하고 `first_seen_at`, `last_seen_at`, `last_urgent_alert_price_won`을 별도 보존한다.
- `Observation`은 제외 매물까지 담으며 `exclusion_reason`과 원본 보존용 `raw_payload`가 있다.
- 검색 URL, 가격·면적 범위, 시간대, JSON 배열 설정에 모델 검증을 추가했다.
- `properties/admin.py`: 공통 규칙·검색 조건 편집 화면과 수집/원본/현재 매물/알림 실패 조회 화면을 등록했다. `GlobalRule`은 단일 행만 허용한다.
- `properties/migrations/0001_initial.py` 생성, `settings.INSTALLED_APPS`에 `properties` 추가.
- DB 비의존 모델 테스트 8개 추가. 모델+기존 리포트 테스트 14개, finder 테스트 81개, `manage.py check`, `makemigrations --check` 통과.

#### 3단계에서 완료한 코드와 데이터

- `properties/seed/searches.yaml`에 기존 검색 설정을 초기 시드로 복사했다.
- `manage.py import_searches`: 공통 규칙과 검색조건을 검증 후 upsert한다.
- `manage.py import_state`: `scan-runs.jsonl`, `observations.jsonl`, `state.json`, `notification-queue.jsonl`을 트랜잭션으로 이관하며 반복 실행해도 중복되지 않는다.
- 수집 실행 시작 시각과 `(수집 실행, 검색 조건, 매물 ID)`에 고유 제약을 추가하는 `0002` 마이그레이션을 적용했다.
- 실제 이관 결과: 공통 규칙 1, 검색조건 6, 수집 실행 27, 원본 관측 1,304, 전체 매물 62, 활성 매물 41, 활성 급매 1, 알림 가격 이력 보유 2.
- DB 기반 이관 테스트를 포함한 Django 테스트 16개가 통과했다. 테스트 동안만 `property_report`에 `CREATEDB`를 부여했고 종료 후 `NOCREATEDB`로 되돌렸다.

#### 다음에 할 일 (순서대로)

1. 4단계: `parsing.py`의 판정을 `properties/matching.py`로 옮기고 DB 모델 입력으로 동작하게 한다.
2. `service.scan()`의 상태 판정을 `properties/scanning.py`의 트랜잭션 기반 `record_scan()`으로 옮기고 테스트한다.

### PostgreSQL 현재 상태 (2026-09-03 확인)

**정상 실행 중이다.** Windows 서비스 `postgresql-x64-18`이 자동 시작으로 등록돼 있고, `property_report` 역할과 같은 이름의 DB가 생성돼 있다. Django 마이그레이션 `properties.0002`까지 적용됐다.

- 설치 경로: `C:\Program Files\PostgreSQL\18` (PostgreSQL 18, pgAdmin 4 포함)
- 데이터 디렉터리: `C:\Program Files\PostgreSQL\18\data` — 이미 초기화돼 있고 기존 클러스터가 들어 있다
- 서비스 `postgresql-x64-18`: `Running`, 시작 유형 `Automatic`. 127.0.0.1:5432 연결 확인 완료.
- `property_report` 역할은 애플리케이션 DB 소유자이며 `CREATEDB` 권한은 없다. 테스트 때만 잠시 부여했다가 회수했다.
- `psql`이 PATH에 없다 (`C:\Program Files\PostgreSQL\18\bin`을 직접 쓰거나 `pg_env.bat`을 사용)
- **`postgres` 슈퍼유저 비밀번호는 에이전트가 모른다. 사용자만 안다.**
- 현재 `pg_hba.conf`의 IPv4 로컬 접속(`127.0.0.1/32`)은 `trust`다. 로컬 프로세스의 DB 접근까지 비밀번호로 제한하려면 추후 `scram-sha-256`으로 바꾸고 PostgreSQL 서비스를 재시작해야 한다.

### 새로 만들 테이블 (`report-site/properties/models.py`)

| 모델 | 대체 대상 |
|---|---|
| `GlobalRule` (단일 행) | `searches.yaml`의 `global_rules` + `schedule` |
| `SearchCondition` | `searches.yaml`의 `searches` |
| `Scan` | `data/scan-runs.jsonl` |
| `Observation` | `data/observations.jsonl` — **수집 원본 전량**, `exclusion_reason`에 제외 사유 |
| `Listing` | `data/state.json`의 `listings` — 조건 통과 매물의 현재 상태 |
| `NotificationFailure` | `data/notification-queue.jsonl` |

`Listing`의 unique 키는 `(condition, listing_id)`이며 기존 `Listing.key`(`condition_id:listing_id`)를 그대로 표현한다.

### 판정 순서 (`properties/scanning.py`의 `record_scan()`)

기존 `service.scan()`(`service.py:42-154`)의 순서를 그대로 옮긴다.

1. `Scan` 생성, 수집 매물을 **전량** `Observation`으로 저장 (조건 통과 여부 무관)
2. 단지명 별칭으로 `SearchCondition`에 매핑하고 `explain_condition()` 실행 → 탈락 사유를 `Observation.exclusion_reason`에 기록
3. 통과분은 `Listing` upsert (`first_seen_at` 보존, `last_seen_at`·`price_won` 갱신)
4. `is_urgent` = `price_won <= effective_urgent_price_won`, `is_new` = 기존 행 없음
5. `should_alert` = 급매이면서 (`last_urgent_alert_price_won`이 없거나 그보다 **더 내려간** 경우). `notify_new` 조건은 신규도 알림 대상
6. 수집 성공한 조건에 한해 이번에 안 보인 `Listing`을 `active=False`로
7. 여기까지 하나의 **트랜잭션**으로 커밋 — 커밋이 끝나야 리포트가 이번 조회를 서빙하고 `is_live()`가 통과한다
8. 커밋 후 전송. 알림 대상이 없으면 `_no_alert_reason()`(`service.py:278-313`)을 옮겨 **미전송 사유를 반드시 기록**

### 이관 중 반드시 지킬 불변 조건

- **`import_state`가 `last_urgent_alert_price_won`과 `first_seen_at`을 보존해야 한다.** 잃으면 이미 알린 급매를 다시 보낸다.
- 상태 저장(트랜잭션 커밋)이 전송보다 **먼저**여야 한다. 순서가 바뀌면 `is_live()`가 항상 실패해 `전체 매물 보기` 버튼이 매번 빠진다.
- `report/templates/report/index.html:69`의 `data-observed-at` 속성은 `publish.py`의 정규식이 의존한다. 이름을 바꾸지 않는다.
- 수집 실패 시 기존 매물을 전부 비활성화하지 않는다.
- 카카오를 보내지 않는 모든 경로는 사유를 남긴다. 조용한 종료는 실패와 구분되지 않는다.
- 카드 렌더링·이미지 전송 실패 시 텍스트로 폴백하고, 텍스트마저 실패하면 기록 후 오류를 올린다.
- 카카오 공개 링크에 `127.0.0.1`/`localhost`를 넣지 않는다.
- `build_report_payload`는 숫자 `listing_id` + `/articles/` URL만 포함한다. 묶음 카드의 해시 id(`card-...`)가 리포트에서 빠지는 현재 동작을 그대로 보존한다.

### 사용자 선행 작업

- 현재 없음. admin 슈퍼유저 1개가 생성돼 있음을 DB에서 확인했다. 사용자명과 비밀번호는 문서에 기록하지 않았다.

### 종단 검증 순서 (전환 완료 후)

1. `import_searches` → admin에서 6개 조건이 YAML과 일치하는지 확인
2. `import_state` → 활성 매물 41건, 급매 1건, `last_urgent_alert_price_won` 보존 확인
3. `report-site\run-site.bat` → 리포트가 이관 전과 **같은 화면**인지 육안 비교 (관심 단지 6 / 확인 매물 41 / 급매 1)
4. `manage.py check_report` → 공개 URL이 최신 조회를 서빙하는지 확인
5. `run-scan.bat` 실제 수집 1회 → `Observation`에 원본 전량이 쌓이고 `Listing`이 갱신되는지, 콘솔에 전송 여부와 사유가 찍히는지 확인
6. `send-report.bat` → 카카오톡 카드에 `원본 이미지 보기` / `전체 매물 보기` 두 버튼이 붙는지 휴대폰에서 확인

## Known Issues

- **`report-site/run-site.bat`이 실행 중이 아니면 공개 리포트 주소가 죽는다.** PC 종료·절전도 마찬가지다. 자동 시작을 등록하지 않기로 했으므로(Key Decisions 참고) 리포트를 외부에서 열어야 할 때 사용자가 직접 켜야 한다. 다행히 조용히 깨지지는 않는다 — 서버가 없으면 `is_live()`가 실패해 카카오 카드에서 버튼이 빠진다.
- **전환이 끝나면 스캔 자체가 Django 서버 실행을 요구하게 된다.** 지금은 서버가 꺼져 있어도 스캔이 돌고 카드에서 버튼만 빠지지만, 이후에는 `run-scan.ps1`이 `/api/health/` 사전 확인에서 멈춘다. 자동 시작 등록 여부를 그때 다시 판단한다.
- **전환 후 Django admin이 공개 URL에 노출된다.** 토큰 경로 뒤에 두더라도 로그인 화면이 인터넷에 열린다. 강한 비밀번호가 필요하다.
- 예전 Codex Sites 주소(`https://my-property-report-20260902.ssong7988.chatgpt.site`)는 더 이상 갱신되지 않는다. 루트 `.env`의 `KAKAO_REPORT_URL`을 지우면 이 오래된 주소로 폴백하므로 비우지 않는다.
- 휴대전화에서 `127.0.0.1`/`localhost`는 서버 PC를 가리키지 않으며 카카오 웹 도메인으로도 부적합하다(Tailscale Funnel 주소를 써야 하는 이유).
- 토큰 경로(`REPORT_PATH_TOKEN`)는 우발적 노출만 막는다. 주소가 유출되면 인증 없이 누구나 볼 수 있다.
- `state.json` 기반이므로 PostgreSQL 전환은 아직 남은 과제다 — 위 In-Flight Migration이 이것을 해결한다.
- 루트와 예전 UI(`property-report-site/site-app/`)가 중첩 Git 저장소로 남아 있다. 그 디렉터리를 다시 건드릴 일이 생기면 UI 커밋 누락이나 루트 포인터만 변경되는 실수에 유의한다.
- 마지막 `npm audit` 결과는 취약점 11개(낮음 1, 보통 2, 높음 8)였다(예전 UI 저장소 기준, 더 이상 서빙 경로가 아니므로 우선순위 낮음).
- 공개 리포트에는 매물 정보가 노출되므로 민감한 개인 데이터나 인증 정보를 포함하지 않아야 한다.

## Key Decisions

### 이번 전환에서 정한 것 (2026-09-03)

- **수집기는 판정하지 않는다. 수집한 매물을 전량 API로 넘긴다.** 이유: 조사와 표현·판정이 한 프로세스에 섞여 있어 변경 범위가 항상 전체로 번졌다. 원본을 전부 DB에 넣어두면 조건을 바꿨을 때 재수집 없이 과거 데이터를 다시 판정할 수 있다.
- **검색조건은 Django 모델이 소스이고 admin에서 수정한다.** `config/searches.yaml`은 `report-site/properties/seed/searches.yaml`로 옮겨 초기 시드로만 쓴다. 이유: 조건 필터를 Django가 수행하려면 조건이 DB에 있어야 하고, YAML을 고치고 스크립트를 돌리는 것보다 화면에서 고치는 편이 낫다고 판단했다.
- **SQLite를 거치지 않고 PostgreSQL로 바로 간다.** 이유: 어차피 목표 아키텍처이고 두 번 마이그레이션할 이유가 없다.
- **카드 생성·카카오 전송까지 `report-site`가 소유한다.** 이유: 원래 불만이 "조사도 하고 그 결과도 꾸미는 것"이었다. Playwright가 이미 공유 venv에 있어 새 설치 없이 옮길 수 있다.
- **DRF를 추가하지 않는다.** 엔드포인트가 4개뿐이라 `JsonResponse` + 명시적 검증으로 충분하고, 프로젝트의 "가장 단순한 해법" 원칙에 맞는다.
- **카드 전송을 `POST /api/scans/` 요청 안에서 동기로 처리한다.** 큐를 도입하지 않는 대신 요청이 수 초~수십 초 걸린다. 단일 사용자 시스템이고 수집기는 어차피 대기 중이다.
- **API는 `Authorization: Bearer <FINDER_API_TOKEN>`으로 보호한다.** 사이트가 Tailscale Funnel로 인터넷에 열려 있어 `/api/`도 외부에서 닿는다.
- **Django admin을 `r/<REPORT_PATH_TOKEN>/admin/` 아래에 둔다.** `/admin/`을 그대로 노출하지 않기 위해서다.

### 이전에 정해져 유지되는 것

- **서빙 방식을 Next.js/Codex Sites 빌드·배포에서 Django(`report-site/`) 요청 시 렌더링으로 전환했다.** 이유: 조회할 때마다 UI를 빌드·배포해야 하는 것이 불합리했고, 목표 아키텍처에도 더 가깝다.
- 외부 공개는 도메인 구입 없이 Tailscale Funnel을 쓴다. 접근 제어는 로그인이 아니라 추측 불가능한 경로 토큰이다 — 리포트에 담긴 정보가 네이버 부동산 공개 정보 수준이라 판단했기 때문이다.
- **리포트 서버 자동 시작(작업 스케줄러)은 등록하지 않는다.** 상시 실행 프로세스를 늘리지 않는 대신, 서버가 꺼져 있으면 카카오 카드에서 버튼이 빠지는 것을 정상 동작으로 받아들인다. (전환 후 스캔이 서버를 요구하게 되면 이 결정을 재검토한다.)
- 표시 로직은 한 곳에만 둔다. 가격/면적 포맷이 카카오 카드와 웹 리포트 사이에서 갈라지지 않게 하기 위함이다. 전환 후 그 한 곳은 `report-site/properties/report.py`가 된다.
- `is_live()` 게이트는 유지한다. "리포트 서버가 살아있고 이번 조회를 서빙 중인가"를 확인하며, PC가 꺼져 있으면 카카오 카드에서 `전체 매물 보기` 버튼이 올바르게 빠진다.
- 예전 `property-report-site/site-app/`은 삭제하지 않는다. 별도 중첩 Git 저장소라 삭제는 되돌리기 어렵다.
- `KAKAO_REPORT_URL`(루트 `.env`)과 `REPORT_PATH_TOKEN`(`report-site/.env`)은 분리해서 관리한다. 전자는 공유 공개 URL, 후자는 Django 라우팅에만 쓰는 비밀 토큰이다.
- 고정 도메인이 바뀌면(Tailscale 호스트명 포함) 카카오 개발자 콘솔의 웹 도메인과 `KAKAO_REPORT_URL`을 함께 변경한다.
- 토큰, 비밀번호, 쿠키, 인증 코드는 Git 및 상태 문서에 기록하지 않는다.
