# 프로젝트 아키텍처와 코드 탐색 가이드

이 문서는 에이전트가 저장소 전체를 읽지 않고도 현재 구조를 이해하고, 작업에 필요한 파일만 선택하도록 돕는 상세 지도다. 현재 운영 상태와 최근 결과는 `../PROJECT_STATE.md`, 사람이 실행하는 절차는 `RUNBOOK.md`를 기준으로 한다.

## 1. 한눈에 보는 구조

```text
사용자 / Windows 작업 스케줄러
              |
              v
real-estate-finder/run-scan.ps1
              |
              v
python -m real_estate_finder <command>
              |
              v
CLI -> 설정 -> 네이버 화면 수집 -> 필터/급매 판정 -> 로컬 상태
                                      |              |
                                      |              +-> 실행·관측 이력
                                      v
                              카드 이미지 + 리포트 JSON
                                      |
                         +------------+-------------+
                         |                          |
                         v                          v
                kakao-notifier              Next.js 리포트 UI
                카카오 나에게 보내기          Codex Sites 빌드/배포
```

현재 시스템은 하나의 프로세스로 묶인 모놀리식 Python 애플리케이션에 가깝다. `real-estate-finder`가 수집, 판정, 상태 관리, 카드 생성, 리포트 데이터 생성을 조정하고, `kakao-notifier`와 `property-report-site/site-app`을 경계 밖 어댑터처럼 사용한다.

목표 구조는 다음과 같다.

```text
수집기 -> PostgreSQL -> Django 웹 애플리케이션 -> 고정 공개 URL -> 카카오톡
```

목표 구조는 아직 구현되지 않았다. 현재 코드에 PostgreSQL 또는 Django가 있다고 가정하지 않는다.

## 2. 저장소 경계

### 루트 저장소

루트 저장소는 Python 수집기, 카카오 모듈, 운영 문서와 UI 저장소 포인터를 관리한다.

```text
outputs/
├── .agent/
│   ├── PROJECT_STATE.md       # 최신 운영 상태와 주요 결정
│   └── docs/
│       ├── ARCHITECTURE.md    # 이 문서: 구조와 코드 탐색 지도
│       ├── README.md          # 문서 색인
│       └── RUNBOOK.md         # 사람이 실행하는 운영 절차
├── real-estate-finder/        # 핵심 Python 애플리케이션
├── kakao-notifier/            # 독립 실행 가능한 카카오 API 모듈
├── property-report-site/
│   └── site-app/              # 별도 Git 저장소인 웹 UI
├── AGENTS.md                   # 모든 코딩 에이전트의 공통 규칙
└── README.md                   # 사용자용 짧은 소개
```

### 중첩 UI 저장소

`property-report-site/site-app/`은 루트 Git이 gitlink로 추적하는 별도 Git 저장소다. Git submodule과 비슷한 형태지만 `.gitmodules`에 의존하지 않고, 루트에는 특정 UI 커밋 포인터만 기록된다.

UI 변경 시 순서는 반드시 다음과 같다.

1. `property-report-site/site-app/` 안에서 변경, 검증, 커밋한다.
2. 루트 저장소에서 변경된 `property-report-site/site-app` 포인터를 커밋한다.
3. 두 저장소의 `git status`를 각각 확인한다.

루트에서만 diff를 보면 UI 내부 변경 내용이 아니라 포인터 변경만 보일 수 있다.

## 3. 핵심 Python 애플리케이션

경로: `real-estate-finder/`

### 진입점과 조정 계층

| 파일 | 책임 | 언제 읽는가 |
|---|---|---|
| `run-scan.bat` | 더블클릭용 PowerShell 래퍼 | Windows 실행 진입점 변경 |
| `run-scan.ps1` | Edge CDP 실행/확인, 로그인 확인, `scan-once` 실행 | 브라우저 시작, 사용자 실행 실패 |
| `real_estate_finder/__main__.py` | `python -m real_estate_finder`를 CLI로 연결 | 거의 읽을 필요 없음 |
| `real_estate_finder/cli.py` | 명령 정의, 객체 조립, 명령별 분기 | 새 명령 추가, 실행 흐름 파악 |
| `real_estate_finder/service.py` | 수집 이후 필터, 상태, 알림, digest 조정 | 업무 규칙과 전체 처리 순서 변경 |

`cli.py`가 조립 루트(composition root)다. 설정, 수집기, 파일 저장소, 카카오 어댑터를 만들고 `FinderService`에 전달한다. 의존성 주입 프레임워크는 없다.

### 도메인과 설정

| 파일 | 책임 | 핵심 타입/함수 |
|---|---|---|
| `models.py` | 계층 간 공유 데이터 모델 | `SearchCondition`, `AppConfig`, `Listing`, `ScanResult` |
| `config.py` | YAML을 도메인 설정으로 변환하고 검증 | `load_config`, `validate_config` |
| `config/searches.yaml` | 기본 검색·가격·저층·스케줄 정책 | 운영 기본값 |
| `config/searches.local.yaml` | 선택적 로컬 재정의 | Git 제외, 있으면 기본 YAML보다 우선 |
| `parsing.py` | 가격/층/타입 정규화와 조건 일치 판정 | `parse_price_won`, `parse_floor`, `matches_condition`, `explain_condition` |

`Listing.key`는 `condition_id:listing_id`이며 현재 상태와 중복 알림 판정의 식별자다. 같은 네이버 매물이 여러 검색 조건에 속하면 조건별로 별도 키가 된다.

저층은 단순 표시용 값이 아니다. `parsing.py`가 층을 판정하고, 설정에 따라 일반 조사 가격과 급매 가격에서 `price_discount_won`을 차감한 유효 임계값을 `Listing`에 넣는다. 가격 또는 필터 규칙을 바꿀 때는 YAML만 보지 말고 `models.py`와 `parsing.py`를 함께 읽는다.

### 네이버 수집 계층

| 파일 | 책임 |
|---|---|
| `collector.py` | 로그인된 Edge를 Playwright CDP로 제어하고 관심부동산 화면에서 매물을 수집 |

현재 주 실행 경로는 다음과 같다.

```text
FinderService.scan
  -> NaverBrowserCollector.collect_all
     -> collect_favorites_snapshot
        -> 로그인 확인
        -> 네이버 홈에서 부동산 링크 클릭
        -> 관심부동산 열기
        -> 저장된 단지 목록 확인
        -> 각 단지의 화면 필터 적용
        -> 카드/중개사 묶음 펼치기와 스크롤
        -> 개별 매물 파싱
     -> 단지 별칭으로 SearchCondition에 매핑
  -> parsing.matches_condition
```

중요한 수집 불변 조건은 다음과 같다.

- 비공개 API를 직접 호출하거나 접근 제한을 우회하지 않는다.
- CAPTCHA, 로그인 만료, 비정상 접근 화면을 만나면 중단한다.
- 외부 Edge CDP가 기본이며, 수집 종료 시 사용자의 브라우저를 닫지 않는다.
- 관심단지 화면이 표시한 단지 수와 읽은 단지 수가 다르면 성공으로 처리하지 않는다.
- 묶음 매물의 대표 링크는 최저가를 우선하고, 같은 가격이면 매물번호가 큰 최신 링크를 택한다.
- 수집 화면의 면적 필터와 최종 Python 필터는 서로 다른 방어선이다.

`collector.py`에는 `_collect_condition()`과 `_navigate_with_visible_ui()` 같은 예전 단지별 검색 경로도 남아 있다. 현재 `collect_all()`은 이 경로를 호출하지 않고 관심부동산 스냅샷을 사용한다. 수집 버그를 조사할 때 호출 관계를 확인하지 않고 예전 경로부터 수정하지 않는다.

`collector.py`는 큰 파일이므로 작업별로 다음 구간만 우선 찾는다.

- CDP/로그인: `open_login`, `_verify_login`, `_wait_for_login`
- 전체 수집: `collect_all`, `collect_favorites_snapshot`
- 관심단지 탐색: `_open_favorites`, `_favorite_complexes`, `_collect_favorite_complex`
- 화면 필터: `_apply_screen_filters`, `_select_trade_type`, `_select_similar_exclusive_area`
- 스크롤/묶음: `_collect_complex_cards`, `_expand_listing_groups`, `_merge_article_rows`
- 원시 텍스트 변환: 파일 하단의 `_extract_*`, `_parse_favorite_listing_text`

### 상태와 이력

| 파일/경로 | 책임 | Git |
|---|---|---|
| `storage.py` | 파일 저장소, 원자적 상태 저장, 실행 잠금 | 소스 추적 |
| `data/state.json` | 현재 및 과거에 본 매물 상태, 활성 여부, 마지막 급매 알림 가격 | 제외 |
| `data/observations.jsonl` | 수집된 원시 관측 이력 append-only 로그 | 제외 |
| `data/scan-runs.jsonl` | 실행 성공/실패와 건수 요약 | 제외 |
| `data/notification-queue.jsonl` | 텍스트 알림 전송까지 실패한 항목 | 제외 |
| `data/favorites-latest.json` | `collect-favorites`가 만든 최근 수집 스냅샷 | 제외 |
| `data/run.lock` | 중복 실행 방지용 배타 잠금 | 제외, 정상 종료 시 삭제 |
| `data/cards/card.png` | 최근 생성 카드 이미지 | 제외 |

`state.json`과 `favorites-latest.json`은 임시 파일을 만든 뒤 교체하여 기록한다. JSONL 파일은 append-only다. 현재 데이터 저장소는 PostgreSQL이 아니며, `FileStore`가 미래 저장 계층 전환의 경계다.

### 알림 판정

`FinderService.scan()`의 핵심 규칙은 다음과 같다.

1. 활성 조건의 매물을 모두 수집한다.
2. `matches_condition()`을 통과한 매물만 현재 일치 목록에 넣는다.
3. 처음 본 매물은 `first_seen_at`을 기록한다.
4. 급매는 이전에 알림을 보내지 않았거나, 마지막 알림 가격보다 더 내려간 경우에만 다시 알린다.
5. `notify_new`가 켜진 조건은 신규 매물도 알린다.
6. 이번에 보이지 않은 기존 매물은 해당 조건 수집이 성공한 경우에만 `active: false`로 바꾼다.
7. 관측과 실행 이력을 남기고, 성공한 조건이 하나라도 있을 때 현재 상태를 저장한다.

수집기는 현재 한 번의 관심부동산 수집 실패를 모든 활성 조건 실패로 기록한다. 조건별 부분 성공처럼 보이는 구조가 일부 있지만, 현재 수집 구현은 사실상 전체 스냅샷 단위다.

### 카드와 웹 리포트 데이터

| 파일 | 책임 |
|---|---|
| `card.py` | 자기완결형 HTML을 만들고 임시 headless Edge로 PNG 렌더링 |
| `report.py` | 카드에 담길 매물로 UI의 `app/report-data.json` 생성 |
| `publish.py` | UI 빌드 실행과 공개 사이트 `observedAt` 검증 |
| `notifier.py` | 메시지 요약 포맷과 `kakao-notifier` 동적 로딩 어댑터 |

카드 전송 경로는 다음 순서다.

```text
FinderService._safe_send_card
  -> report.write_report_data
     -> property-report-site/site-app/app/report-data.json 교체
  -> publish.is_live
     -> 공개 페이지의 data-observed-at 비교
  -> card.build_card_image
     -> real-estate-finder/data/cards/card.png
  -> KakaoNotifier.send_image
     -> kakao-notifier/kakao_notifier.py 동적 로딩
```

주의할 점:

- `report-data.json`은 모든 스캔에서 무조건 갱신되지 않는다. 신규/급매 알림 카드가 발생하거나 `send-digest`/성공한 `smoke-test`가 카드 전송 경로를 탈 때 갱신된다.
- 스캔은 UI를 빌드하거나 배포하지 않는다.
- UI는 `report-data.json`을 빌드 시점에 import하므로 JSON 변경만으로 공개 사이트가 바뀌지 않는다.
- 공개 사이트의 `observedAt`이 카드 데이터와 같은 시각일 때만 `전체 매물 보기` 버튼을 넣는다.
- 카드 렌더링 또는 이미지 전송이 실패하면 짧은 텍스트 알림으로 폴백한다.
- 폴백 텍스트 전송도 실패하면 `notification-queue.jsonl`에 기록하고 오류를 다시 올린다.

`service.py`가 `build_site`를 import하고 `build_report` 인자를 보존하지만, 현재 스캔 경로에서는 빌드를 호출하지 않는다. 실제 빌드는 `publish-report` 명령을 명시적으로 실행할 때만 한다.

## 4. 카카오 모듈

경로: `kakao-notifier/`

| 파일 | 책임 |
|---|---|
| `auth.py` | OAuth 인증 코드 수신, 최초 토큰 발급과 저장 |
| `common.py` | `.env` 로드, form/multipart HTTP 요청 공통 코드 |
| `kakao_notifier.py` | 토큰 갱신, 이미지 업로드, feed/text 템플릿 전송, CLI |
| `test_kakao_notifier.py` | 이미지 원본 링크와 리포트 버튼 구성 검증 |
| `.env` | 앱 키, 시크릿, URL 설정; Git 제외 |
| `data/kakao-token.json` | 액세스/리프레시 토큰; Git 제외 |

`real-estate-finder/notifier.py`는 패키지 의존성으로 설치하지 않고 `kakao_notifier.py`를 파일 경로에서 동적으로 불러온다. 두 디렉터리의 결합 지점은 다음 함수다.

- 텍스트: `send_to_me(message, link_url)`
- 이미지 카드: `send_card_to_me(image_path, title, description, link_url, width, height)`

카카오 feed 카드의 이미지 URL은 카카오 이미지 업로드 API의 원본 URL을 사용한다. 리포트 링크가 유효하면 두 번째 버튼으로 추가한다. 등록되지 않은 도메인은 카카오가 조용히 다른 주소로 치환할 수 있으므로 URL 변경은 `.env`만 수정해서 끝내지 않고 카카오 개발자 콘솔의 웹 도메인도 함께 확인한다.

## 5. 웹 리포트 UI

경로: `property-report-site/site-app/`

| 파일/경로 | 책임 |
|---|---|
| `app/page.tsx` | 리포트 JSON을 읽어 단지/매물 카드를 렌더링 |
| `app/report-data.json` | Python이 생성하는 공개 데이터 스냅샷 |
| `app/globals.css` | 화면 스타일 대부분 |
| `app/layout.tsx` | 루트 레이아웃 |
| `components/ui/` | 생성된 범용 UI 컴포넌트 모음; 현재 페이지가 모두 쓰는 것은 아님 |
| `package.json` | Codex Sites와 로컬 Next.js 실행 명령 |
| `vite.config.ts` | Codex Sites/vinext 빌드 설정과 hosting binding |
| `next.config.ts` | 로컬 Next.js 설정 |
| `.openai/hosting.json` | 기존 Codex Sites 프로젝트 연결 정보 |
| `run-local.ps1`, `run-local.bat` | 로컬 UI 실행 래퍼 |

현재 실제 화면은 `app/page.tsx`, `app/globals.css`, `app/report-data.json`에 집중되어 있다. UI 문구나 배치 변경을 조사할 때 `components/ui/` 전체를 먼저 읽을 필요가 없다. `page.tsx`가 import하는 컴포넌트만 따라간다.

두 실행 계열이 공존한다.

| 목적 | 명령 | 구현 |
|---|---|---|
| Codex Sites 개발/빌드 | `npm run dev`, `npm run build` | vinext + Vite + Sites plugin |
| 로컬 Next.js 개발/빌드 | `npm run dev:local`, `build:local`, `start:local` | Next.js |

`npm run build`는 배포 가능한 산출물을 만들 뿐 공개 사이트에 배포하지 않는다. 배포와 배포 후 시각 검증은 `RUNBOOK.md` 절차를 따른다.

## 6. 명령별 실제 경로

모든 Python 명령은 `real-estate-finder/`에서 실행한다고 가정한다.

| 명령 | 읽기/쓰기와 부작용 |
|---|---|
| `validate-config` | 설정만 읽고 검증; 브라우저/카카오 부작용 없음 |
| `browser-login` | Edge 로그인 상태 확인, 필요하면 사용자 로그인 대기 |
| `collect-favorites` | 브라우저 수집 후 `favorites-latest.json`만 저장 |
| `explain-filters` | 저장된 스냅샷을 재생해 제외 이유 출력; 브라우저 없음 |
| `scan-once` | 수집, 상태/이력 기록, 신규·급매가 있으면 카카오 전송 |
| `smoke-test` | 수집과 상태 기록, 정규 급매 이력은 소모하지 않고 전체 카드 전송 |
| `scheduled-run` | `scan-once` 성격 + 평일 설정 시각에 digest 전송 |
| `send-digest` | `state.json`의 활성 매물로 전체 카드 전송; 새 수집 없음 |
| `preview-card` | 저장된 활성 매물로 PNG만 생성; 카카오 전송 없음 |
| `publish-report` | 현재 JSON 확인 후 `npm run build`; 배포는 별도 |
| `publish-report --verify-only` | 공개 사이트의 기준 시각만 비교 |

`send-digest`, `smoke-test`, 알림이 발생한 `scan-once`는 외부 카카오 메시지를 보낼 수 있다. `publish-report`는 빌드만 하고 외부 배포를 완료하지 않는다.

## 7. 작업별 최소 읽기 경로

모든 작업은 먼저 `../PROJECT_STATE.md`를 읽는다. 그 다음 아래 파일만 우선 읽고, 호출 관계가 이어질 때 범위를 넓힌다.

| 작업 | 먼저 읽을 파일 | 관련 테스트 |
|---|---|---|
| 검색 단지/가격/스케줄 변경 | `config/searches.yaml`, `models.py`, `config.py`, `parsing.py` | `tests/test_core.py` |
| 조건에서 매물이 빠지는 이유 | `parsing.py`, `config/searches.yaml`, 최근 `favorites-latest.json` | `explain-filters`, `tests/test_core.py` |
| 네이버 로그인/CDP 문제 | `run-scan.ps1`, `collector.py`의 로그인 메서드 | 브라우저 수동 확인 중심 |
| 관심단지/카드 수집 문제 | `collector.py`의 현재 주 경로와 하단 파서 | `tests/test_core.py` |
| 신규/급매 중복 알림 | `service.py`, `storage.py`, `models.py` | `tests/test_service.py` |
| 카카오 메시지 문구 | `real_estate_finder/notifier.py` | `tests/test_card.py`, `tests/test_core.py` |
| 카카오 OAuth/토큰/API | `kakao-notifier/auth.py`, `common.py`, `kakao_notifier.py` | `kakao-notifier/test_kakao_notifier.py` |
| 카드 이미지 디자인 | `card.py` | `tests/test_card.py`, `preview-card` |
| 리포트 JSON 스키마 | `report.py`, `models.py`, UI `app/page.tsx` | 관련 서비스 테스트 + UI 빌드 |
| 웹 화면 디자인 | UI `app/page.tsx`, `app/globals.css`, 필요한 컴포넌트만 | `npm run build` |
| Codex Sites 빌드/시각 검증 | `publish.py`, `cli.py`의 `_publish_report`, `RUNBOOK.md` | `tests/test_publish.py`, UI 빌드 |
| 로컬 UI 실행 | UI `package.json`, `next.config.ts`, `run-local.ps1` | `npm run build:local` |
| 파일 저장을 PostgreSQL로 전환 | `storage.py`, `service.py`, `models.py`, `cli.py` | `tests/test_core.py`, `tests/test_service.py` |
| CLI 명령 추가 | `cli.py`, 해당 서비스 모듈 | 명령 성격에 맞는 테스트 |

다음 파일은 보통 처음부터 읽지 않는다.

- `collector.py` 전체: 관련 메서드부터 좁혀 읽는다.
- UI `components/ui/` 전체: `page.tsx`가 실제 import한 것만 읽는다.
- `node_modules/`, `.next/`, `dist/`, `.vinext/`, `.wrangler/`: 생성 결과물이므로 소스 조사에서 제외한다.
- `.venv/`, `__pycache__/`: 생성 결과물이므로 제외한다.
- `real-estate-finder/project_state.md`: 세부 과거 문맥일 수 있지만 최신 공통 상태는 `.agent/PROJECT_STATE.md`가 우선이다.

## 8. 검증 범위

변경 범위에 맞는 최소 검증을 선택한다.

```powershell
# Python 수집기, 판정, 서비스, 발행 로직 전체
cd real-estate-finder
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# 카카오 모듈의 순수 단위 테스트
cd ..\kakao-notifier
.\.venv\Scripts\python.exe -m unittest -v test_kakao_notifier.py

# Codex Sites UI 빌드
cd ..\property-report-site\site-app
npm run build

# 로컬 Next.js 경로까지 건드렸을 때
npm run build:local
```

실제 네이버 수집과 카카오 전송은 외부 상태와 사용자 계정에 영향을 준다. 단순 코드 검증을 위해 `scan-once`, `smoke-test`, `send-digest`를 임의로 실행하지 않는다. 필요하면 대상과 부작용을 확인한 뒤 실행한다.

## 9. 변경 시 지켜야 할 경계

- 비밀정보는 `.env`, 토큰 파일, 브라우저 프로필 밖으로 복사하거나 문서화하지 않는다.
- 런타임 데이터와 생성 결과물을 Git에 추가하지 않는다.
- 스캔과 UI 빌드/배포의 분리를 유지한다.
- 카카오 공개 링크에 `localhost`나 `127.0.0.1`을 넣지 않는다.
- 공개 리포트 시각 검증 없이 `전체 매물 보기` 버튼을 강제로 넣지 않는다.
- 수집 실패 시 기존 매물을 전부 비활성화하지 않는다.
- 알림 렌더링 실패가 중요한 급매 알림 유실로 이어지지 않도록 텍스트 폴백을 유지한다.
- 리포트 JSON 필드를 바꾸면 Python 생산자(`report.py`)와 TypeScript 소비자(`app/page.tsx`)를 함께 변경한다.
- UI 변경은 중첩 저장소와 루트 포인터의 두 커밋 경계를 지킨다.

## 10. 문서의 역할 구분

- `../PROJECT_STATE.md`: 지금 무엇이 배포되어 있고 최근 결과와 결정이 무엇인지
- `ARCHITECTURE.md`: 코드가 어떻게 연결되고 어떤 작업에 어떤 파일을 읽는지
- `RUNBOOK.md`: 사람이 설치, 조회, 빌드, 배포를 어떻게 실행하는지
- 각 하위 프로젝트 `README.md`: 해당 구성 요소의 상세 사용법

아키텍처, 저장 계층, 배포 방식 또는 실제 주 실행 경로가 바뀌면 이 문서와 `../PROJECT_STATE.md`를 같은 작업에서 갱신한다.
