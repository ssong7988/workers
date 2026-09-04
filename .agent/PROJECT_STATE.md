# Project State

마지막 갱신: 2026-09-04 (매물 리포트에서 면적 표시를 지우고 타입 표시로 교체, 통계·리포트 화면에 지역/단지 필터 추가, 매물에 동(building) 필드 추가, 스캔 진단 로그 추가, 백그라운드 Edge 탭 로그인 오탐 완화)

## Current Architecture

- 코드 경계, 실제 데이터 흐름과 작업별 최소 읽기 경로는 `.agent/docs/ARCHITECTURE.md`에 정리되어 있다.
- `real-estate-finder/`는 네이버 부동산 매물을 수집해 `report-site` API로 넘기기만 한다. 조건 판정·상태·표현·전송 코드는 없다.
- `report-site/properties/`가 카카오 메시지 정책을 소유하고, `kakao-notifier/`의 인증 토큰/API 어댑터를 호출한다. finder 쪽 중복 코드는 8단계에서 삭제했다.
- `report-site/`(Django + waitress)가 PostgreSQL을 요청마다 읽어 화면 둘을 렌더링한다. `r/<TOKEN>/`은 활성 `Listing`으로 매물 리포트를, `r/<TOKEN>/stats/`는 `Observation` 이력으로 날짜별 호가 분포를 그린다. 빌드나 배포 단계는 없다.
- `property-report-site/site-app/`(예전 Next.js/Codex Sites UI)은 서빙 경로에서 은퇴했다. 루트와 별도 중첩 Git 저장소이며 삭제하지 않고 참고용으로만 남겼다.
- 사용자용 조회 진입점은 `real-estate-finder/run-scan.bat` 또는 `real-estate-finder/run-scan.ps1`이며, Edge CDP `http://127.0.0.1:9222`에 연결한다.
- 급매가 아닌 전체 결과를 카카오톡으로 보내는 진입점은 `real-estate-finder/send-report.bat`이며 `report-site`의 `manage.py send_digest`를 실행한다. 브라우저·로그인·웹 서버가 필요 없고 DB만 있으면 된다.
- 리포트 서버 실행 진입점은 `report-site/run-site.bat` 또는 `report-site/run-site.ps1`이다.
- `scan-once`는 수집 결과를 `POST /api/scans/`로 넘기고, Django가 급매 또는 신규가 있을 때만 카카오톡을 보낸다. 보내지 않은 경우에도 사유가 응답의 `scan.notification`으로 돌아와 콘솔에 출력되고 `Scan` 행에도 남는다.
- 검색 설정은 PostgreSQL의 `SearchCondition`이며 Django admin에서 고친다. `report-site/properties/seed/searches.yaml`은 초기 시드일 뿐이다.
- `record_scan()`의 트랜잭션이 알림 전송보다 먼저 커밋된다. 그래야 `is_live()`로 확인하는 시점에 이미 이번 조회 결과가 서빙되고 있다.
- `is_live()`(`report-site/properties/publish.py`)는 리포트 서버(그리고 Tailscale Funnel)가 살아있고 이번 조회를 서빙 중인지만 확인한다.
- 외부 공개는 Tailscale Funnel로 `report-site/`의 8000번 포트를 노출해 고정 HTTPS 주소(`https://<pc>.<tailnet>.ts.net`)를 얻는 방식이다. 접근 제어는 추측 불가능한 경로 토큰(`REPORT_PATH_TOKEN`)이다.
- `KAKAO_REPORT_URL`은 루트 `.env`(`load-env.ps1`이 `run-scan.ps1`/`send-report.ps1`/`report-site/run-site.ps1`에 공유)로 관리하고, `REPORT_PATH_TOKEN`은 `report-site/.env`로 관리한다. 둘 다 Git에서 제외한다.

위 구조는 2026-09-03에 끝난 역할 분리 이관의 결과다. 그 배경과 단계별 이력은 아래 "Completed Migration" 절에 있다.

## Current State

- 검색 조건은 과천 6개·광교 4개·판교 4개, 총 14개가 활성 상태다. 새 8개 조건은 DB까지 반영됐지만 아직 첫 실제 스캔 전이라 새 단지의 `Observation`·`Listing`은 없다.
- **Tailscale Funnel 전환은 완료됐고 종단 확인까지 끝났다.** 공개 리포트는 Funnel 주소로 서빙되며, 실제 카카오톡 카드에 `전체 매물 보기` 버튼이 새 주소로 포함되는 것까지 확인했다.
- 공개 리포트 호스트: `https://desktop-477.tailf8d9d1.ts.net` (Tailscale Funnel → 로컬 `127.0.0.1:8000` 프록시). 전체 경로는 `REPORT_PATH_TOKEN`을 포함하므로 문서에 적지 않는다 — 루트 `.env`의 `KAKAO_REPORT_URL`에 있다.
- Tailscale 설치·로그인·Funnel 활성화 완료(`tailscale funnel --bg 8000`). `tailscaled`는 Windows 서비스라 재부팅 후 Funnel 설정이 자동 복구된다.
- 카카오 개발자 콘솔의 `앱 > 제품 링크 관리 > 웹 도메인`에 위 호스트를 등록 완료. (`플랫폼 키` 메뉴가 아니다 — `kakao-notifier/README.md:31` 참고.)
- `report-site/.env`의 `REPORT_PATH_TOKEN`과 루트 `.env`의 `KAKAO_REPORT_URL` 모두 실제 값으로 채워져 있다(Git 제외).
- `check-report`로 공개 주소가 `data/state.json`의 기준 시각(`2026-09-03T08:38:55+09:00`, 활성 매물 41건)과 일치함을 확인했다.
- `send-report.ps1`로 실제 카카오톡 카드 1통(매물 41건)을 전송해 `전체 매물 보기` 버튼 동작까지 사용자가 휴대폰에서 확인했다.
- 리포트 화면은 관심 단지 6개, 확인 매물 41건, 급매 1건을 정확히 렌더링한다.
- 카카오는 이미지를 보내지 않는다. 텍스트 1통에 `통계 보기`·`전체 매물 보기` 버튼 2개를 붙인다(2026-09-03 통계 기능과 함께 변경).
- 마지막 확인 시 finder 테스트 32개와 Django 테스트 84개 전부 통과, `manage.py check`, `makemigrations --check` 통과. Django 테스트는 DB 생성 권한이 필요하다(아래 Known Issues 참고).
- PostgreSQL 서비스 `postgresql-x64-18`이 자동 시작으로 등록돼 실행 중이며, `property_report` 역할/DB 생성과 Django 마이그레이션 적용을 완료했다.
- `import_searches`와 `import_state`를 실행해 공통 규칙 1개, 검색조건 6개, 수집 실행 27개, 원본 관측 1,304개, 전체 매물 62개를 이관했다. 활성 매물 41개, 활성 급매 1개이며 `last_urgent_alert_price_won`이 있는 기존 매물 2개의 기록도 보존됐다.
- 이관 명령은 두 번 실행해 중복이 생기지 않음을 확인했다. DB 기반 Django 테스트 16개와 `manage.py check`, `makemigrations --check`가 통과했다.
- finder용 `/api/health/`, `/api/conditions/`, `/api/scans/`, `/api/digest/` 경계와 Bearer 인증을 추가했다. 실제 DB에서 health 200, conditions 200, 활성 조건 6개 응답을 확인했다. 스캔 알림과 digest는 7단계에서 Django 동기 전송에 연결됐다.
- 리포트 뷰를 PostgreSQL 기반으로 전환했다. 이관 전 파일 기반 payload와 DB 기반 payload 전체가 동일하며 단지 6개, 매물 41개, 급매 1개, 기준 시각 `2026-09-03T08:38:55+09:00`이 그대로임을 확인했다.
- 실제 DB 활성 매물 41개로 Django `preview_card`를 실행해 1080×8168 PNG(약 617KB)를 생성하고 육안 확인했다. `check_report`도 DB 시각과 공개 리포트 시각이 같은 순간임을 확인해 통과했다. 실제 카카오 전송은 실행하지 않았다.
- `real-estate-finder`를 수집 전용으로 축소했다. 판정·상태·표현·전송 모듈 7개와 `searches.yaml`을 삭제했고(약 2,000줄), `api_client.py`와 5개 명령만 남았다. finder 테스트 32개 통과.
- **새 구조로 실제 네이버 수집을 1회 완주했다(2026-09-03 14:35~14:40 KST, 약 5분).** 6개 조건 전부 성공, 실패 0. 수집 120건 · 조건충족 42건 · 제외 78건(대부분 `가격 초과`)이 모두 DB에 기록됐다. `Scan` 27→28, `Observation` 1,304→1,424, `Listing` 62→74, 활성 41→42.
- **급매 알림 중복 방지가 실제로 동작했다.** 활성 급매 1건이 있었지만 `import_state`가 옮겨 온 `last_urgent_alert_price_won` 때문에 재전송되지 않았다. 이관에서 가장 잃기 쉬웠던 이력이 실제로 보존됐음을 확인한 셈이다.
- 이번 스캔은 카카오톡을 보내지 않았고 그 사유가 `Scan.notification`에 남았다 — "급매 1건은 이미 같은 가격 이하로 알림을 보냈습니다 / 신규 12건은 notify_new가 꺼진 조건이라 알리지 않습니다". 의도된 정책이며 조용한 종료가 아니다.
- Django admin 접속 경로(`.../r/<REPORT_PATH_TOKEN>/admin/`)와 `admin` 슈퍼유저 로그인을 확인했다. `Observation`의 `exclusion_code` 필터로 제외 사유를 구분해 조회할 수 있다.

### 가격 통계 기능 (2026-09-03 추가)

- `r/<TOKEN>/stats/`가 날짜별 호가 분포를 캔들(최저~최고 심지와 위아래 가로 끝선, 1분위~3분위 상자, 평균 가로선)로 보여준다. 서버가 좌표까지 계산하는 inline SVG이며 JS 의존성이 없다.
- 기간은 월 선택 또는 시작일/종료일이고 기본값은 최근 1개월, 범위는 전체/지역/단지이고 기본값은 과천 전체다. 잘못된 질의 문자열은 예외 대신 기본값으로 되돌리고 화면에 사유를 적는다.
- **모집단은 리포트보다 넓다.** `exclusion_code in ("", "price")` — 면적·타입은 통과했고 가격 상한에서만 잘린 매물까지 포함한다. 상한가에서 자르면 최고가와 3분위가 시세가 아니라 사용자의 예산을 나타내게 되기 때문이다.
- **하루에 스캔이 여러 번 도므로 `(조건, 매물, 로컬 날짜)`당 마지막 관측 하나만 센다.** 이것을 빠뜨리면 자주 조회된 매물이 분위수를 지배한다.
- `SearchCondition.region`(과천 5 / 광교 1)과 `Observation.exclusion_code`를 추가하고 기존 행을 백필했다.
- **이관된 과거 관측이 전부 "조건 충족"으로 잘못 표시돼 있었다.** `Scan`의 집계는 맞았지만 행별 `exclusion_reason`이 옮겨오지 않아, 7~27번 스캔의 1,304행이 모두 통과로 읽혔다. 모집단 면적이 35.93~137.21㎡로 벌어져 59㎡와 137㎡가 한 분포에 섞였다. `reclassify_observations`로 다시 판정했다 — 실제로 판정된 28번 스캔 120건을 한 건도 어긋나지 않고 재현한 뒤 나머지 971건을 고쳤다. 지금 모집단은 84.57~84.99㎡다.
- **표본 5건 미만인 날은 1·3분위를 내지 않는다.** `statistics.quantiles(method="inclusive")`는 1분위를 `(n-1)*0.25` 위치에 놓으므로 표본 5건에서 처음으로 실제 관측치(2번째 값) 위에 정확히 떨어진다. 4건 이하는 전부 보간이며, 2건이면 두 값 사이 25% 지점이 시세처럼 표시된다. 사용자가 광교 9/3(2건, 1분위 15.4억 / 3분위 15.8억)을 보고 지적해 고쳤다. 그런 날은 상자 없이 최저~최고와 평균만 그리고 표에는 `–`를 넣는다.
- 확인된 수치(2026-09-03): 과천 9/2 160건 21.5~29.5억(1분위 23.5 / 3분위 26), 9/3 145건 21.5~29.5억(1분위 23 / 3분위 26). 광교는 9/2 4건, 9/3 2건이라 분위수 없음. 통계 표본(145)이 조건충족(42)보다 많은 것이 정상이다.
- 카카오는 카드 PNG 대신 텍스트 1통 + 버튼 2개를 보낸다. **카카오 기본 텍스트 템플릿이 `buttons` 배열을 받는다는 것을 실제 전송 1회로 확인했다.** 200자 예산은 통계 한 줄과 매물 목록이 나눠 쓴다.
- `properties/card.py`, `preview_card`, `test_card.py`를 삭제했다. headless Edge 렌더링 의존이 사라졌다.
- **`Observation`/`Listing`에 `building`(동) 필드를 추가했다(2026-09-04, 마이그레이션 `0004`).** 관심부동산 카드 파서는 이미 동을 읽고 있었지만 finder의 `Listing` 데이터클래스가 버렸다 — 층만으로는 몇 동인지 알 수 없다는 지적으로 finder → API → DB → admin → 리포트 화면까지 이어지도록 연결했다. 통계 화면은 건물을 가로질러 집계하므로 의도적으로 제외했다. **기존에 저장된 매물·관측은 전부 이 기능 이전에 수집된 것이라 동 값이 비어 있다** — 새 스캔이 한 번 돌아야 화면에 동이 나타난다.
- **매물 리포트에서 매물별 면적 표시를 지우고 타입(`type_name`, 예: `84A`)으로 교체했다(2026-09-04).** 조사 조건이 사실상 84㎡ 하나로 고정돼 있어 매물마다 면적을 다시 보여줄 필요가 없다는 지적이었다. `type_name`은 `building`과 달리 최초 마이그레이션(`0001_initial`)부터 존재했고 finder의 실제 수집 경로(`collector.py`의 `_parse_favorite_listing_text`)가 처음부터 채워 왔으므로 스키마·수집 변경은 없었다 — `properties/report.py`의 `build_report_payload()`와 `report/templates/report/index.html` 두 곳(급매 카드, 단지별 매물)만 고쳐 표시 순서를 `타입 · 층 · 동 · 향`으로 맞췄다. `properties/admin.py`의 두 `list_display`에도 `type_name`을 추가해 `building`과 나란히 보이게 했다(전에는 상세 화면에만 보이고 목록에는 빠져 있었다). 조건 설명 문구("전용 83~86㎡ 이하")는 그대로 둔다 — 지운 것은 매물별 면적 표시뿐이다.
- **통계·리포트 화면에 지역/단지 선택 필터를 추가했다(2026-09-04).** 통계 화면은 이미 단지를 고르면 서버가 정확한 지역을 계산했지만 "조회"를 눌러야 화면에 반영됐다 — 두 select에 `onchange` 자동 제출을 붙여 즉시 반영되게 했고, 지역을 바꿀 때 단지 선택을 같이 지워 이전엔 조용히 무시되던 "단지 선택 중 지역 변경"도 실제로 먹히게 고쳤다. 리포트 화면(`report/views.py`의 `index()`)에는 이 선택 기능이 아예 없었는데, 통계와 같은 UI를 추가하되 **기본값은 통계처럼 과천으로 좁히지 않고 전체를 그대로 보여준다** — 카카오 "전체 매물 보기" 링크 등 기존 동작을 깨지 않기 위한 의도적 결정. `resolve_scope()`에 `default_region` 매개변수를 추가해 재사용했다(`stats()`는 기존 기본값 유지, `index()`는 `default_region=""`).

## Completed Work: 관심 단지 추가 + 슈르·에코팰리스 표기 수정 (2026-09-03 완료)

**상태: 코드·조건·DB·문서 반영, 자동 검증, 실제 14개 조건 스캔과 카카오 전송까지 완료.**

- 2026-09-03 16:33 KST에 관심단지 14개를 다시 수집했다. 화면 카드 200/200개, 매매 매물 200건이 일치했고 단지명 공란·ID/이름 중복·단지별 카드 수 불일치는 모두 0개다.
- 기존 6개 대비 새 단지는 8개다: `광교더리브`, `봇들7단지엔파트`, `백현마을6단지`, `백현마을7단지`, `백현마을5단지`, `광교경남아너스빌`, `광교센트럴뷰`, `과천푸르지오써밋`.
- 관심단지가 10개를 넘으면 네이버 패널이 일부 카드만 렌더링하는 문제가 처음 드러나 `collector.py`가 패널을 스크롤하며 화면의 총 개수만큼 누적하도록 고쳤다.
- 여러 면적 옵션 변경 직후 목록 헤더의 중간 건수를 최종값으로 오인하지 않도록 결과 갱신 대기를 추가했다.
- `광교더리브`의 일부 묶음 카드는 실제 클릭에도 중개사별 행이 열리지 않았다. 개별 링크가 0개인 경우에만 화면 카드 자체를 한 매물로 보존하고, 일부만 열린 경우는 계속 실패하도록 했다. 이 경로를 포함한 실제 14개 수집이 완주했다.
- 사용자에게 지역 배정을 확인받아 과천 1개, 판교 4개, 광교 3개 조건을 시드와 DB에 추가했다. 기존 6개를 포함해 활성 조건은 14개, 지역은 과천·광교·판교 3개다.
- `래미안슈르 전체`와 `래미안에코팰리스 전체`는 ID와 판정 동작을 유지한 채 각각 `래미안슈르 84`, `래미안에코팰리스 84`로 표기만 고쳤다.
- `import_searches` 결과 신규 8개·갱신 6개. `manage.py check`, `makemigrations --check --dry-run`, Django 테스트 87개, finder 테스트 32개가 통과했고 실행 중 API가 활성 조건 14개를 반환했다. 테스트용 `CREATEDB` 권한은 원래대로 회수했다.
- admin 제목, 빈 digest 문구, finder CLI 설명에서 서비스 전체를 `과천`으로 한정하던 표현을 제거했다. RUNBOOK에 관심단지 추가 절차와 판교 통계 범위를 반영했다.
- 리포트 서버를 새 코드로 재시작했고 health 200, 통계 화면 200 및 판교 선택지, admin의 새 공통 제목을 확인했다.
- 실제 첫 스캔(29번)을 완주했다. 성공 조건 14/14, 수집·관측 201건, 조건충족·활성 매물 93건, 제외 108건, 급매 0건, 실패 0건이다.
- 카카오 메시지 1통(링크 2개)이 실제 전송됐다. 신규 알림 48건, 조건충족 93건으로 기록됐고 `NotificationFailure`는 0건이다.
- `check_report`에서 DB 기준 시각 `2026-09-03T08:19:33+00:00`과 공개 리포트 시각 `2026-09-03T17:19:33+09:00`이 같은 순간임을 확인했다.

### 사용자 요청 (원문 요지)

1. `래미안슈르`, `래미안에코팰리스`가 이름에 "전체"로 나오는데 실제로는 84만 조사하고 있으니 고쳐라.
2. **광교 1개, 과천 1개, 판교 여러 개** 단지를 네이버 관심단지에 이미 추가해 뒀다("추가했어" — 과거형). 앱이 이를 반영해 추가로 조사하고 UI에도 나오게 하라.
3. 조사 조건은 기존과 동일하게.
4. 알림 방식은 — **광교 추가분은 광교푸르지오월드마크와 동일**, **과천·판교 추가분은 과천센트럴파크푸르지오써밋과 동일**.

### 사용자가 확정한 선택 (질문해서 받은 답)

| 질문 | 답 |
|---|---|
| 슈르·에코팰리스를 어떻게 고칠까 | **표기만 84로 바로잡기.** 조건 ID(`raemian-sur-all`, `raemian-eco-palace-all`)와 동작은 그대로 둔다. 전체 면적을 실제로 조사하게 바꾸는 것이 **아니다** |
| 새 단지 이름 확보 방법 | **`collect-favorites`로 먼저 읽어온다.** 사용자가 직접 적어주는 방식은 선택하지 않았다 |
| 과천·판교 추가분 가격 기준 | **과천센트럴파크와 같은 숫자** — 조사 상한 2,550,000,000 / 급매 2,450,000,000 |

### 조사해서 확인한 사실 (다시 확인할 필요 없음)

- **수집기 코드 변경이 필요 없다.** `real-estate-finder/real_estate_finder/collector.py:183` `collect_all()`은 `collect_favorites_snapshot()`으로 관심단지 목록을 **통째로** 읽은 뒤, 조건을 순회하며 이름이 맞는 것만 남긴다. 조건에 없는 단지는 조용히 버려진다. 따라서 **`SearchCondition` 행만 추가하면 새 단지가 수집된다.**
- **화면 필터가 이미 전 단지 공통이다.** `collector.py:123-124` `SCREEN_AREA_MIN_M2 = 80`, `SCREEN_AREA_MAX_M2 = 86`은 클래스 상수이며 조건과 무관하게 모든 단지에 같은 80~86㎡ 필터를 건다. "조건은 동일하게 조사"가 저절로 성립한다. 이것이 슈르·에코팰리스가 "전체"라는 이름으로도 84만 조사하던 이유다.
- `collector.py:320-322` 주석: `MAX_FAVORITE_COMPLEXES = 30`은 폭주 방지용일 뿐이고 관심단지 추가·삭제에 코드 변경이 필요 없다. 현재 6개 → 12개 안팎이 되어도 여유가 있다.
- **UI 코드 추가가 필요 없다.** 리포트(`report/views.py`의 `index`)와 통계(`stats`)는 `SearchCondition`을 읽어 그린다. 통계 화면의 지역 `<select>`는 `dict.fromkeys(c.region for c in conditions)`로 만들어지므로 **`region: 판교`인 조건이 생기면 판교가 자동으로 나타난다.**
- **추가 반영 직전 DB의 기존 조건 6개가 `report-site/properties/seed/searches.yaml`과 완전히 일치했다(드리프트 0).** 2026-09-03에 필드별로 대조해 확인했다. 그래서 이번에는 YAML을 고치고 `import_searches`를 돌리는 것이 안전한 적용 경로였다. `update_or_create`라 기존 행을 지우지 않는다.
- `properties/tests/test_import_commands.py`는 임시 YAML 픽스처를 쓰므로 시드를 바꿔도 깨지지 않는다.
- 판정 규칙이 바뀌지 않으므로 **`reclassify_observations`는 돌릴 필요가 없다.** 새 단지의 과거 관측은 애초에 존재하지 않는다(수집 단계에서 버려졌으므로 서버에 도달한 적이 없다).

### 1단계 — 단지 목록 확보 (완료)

Edge를 CDP 9222로 띄운 뒤(`run-scan.ps1`의 2단계와 같다) 실행한다.

```powershell
cd real-estate-finder
.\.venv\Scripts\python.exe -m real_estate_finder collect-favorites
```

읽기 전용이다. `data/favorites-latest.json`에만 저장하고 서버 전송도 카카오 전송도 하지 않는다.

기존 6개와 대조해 새로 늘어난 이름을 뽑는다. 기존 목록은 다음과 같다(2026-09-02 16:30 스냅샷 기준, 네이버 표기 그대로).

```text
래미안과천센트럴스위트 / 과천센트럴파크푸르지오써밋 / 과천위버필드
래미안슈르 / 래미안에코팰리스 / 광교푸르지오월드마크(주상복합)
```

**뽑은 뒤 반드시 사용자에게 지역 배정을 확인받고 진행한다.** 판교 단지는 이름에 "판교"가 없는 경우가 흔하다(백현마을·봇들마을·알파리움 등). 추측하지 말고 표로 정리해 물어본다.

> **여기서 드러날 수 있는 문제:** `collector.py:315`는 카드 첫 줄이 `아파트`일 때만 단지명을 읽는다(`name = card_lines[1] if len(card_lines) > 1 and card_lines[0] == "아파트" else ""`). 오피스텔·도시형생활주택으로 분류된 단지는 이름이 빈 문자열로 나와 매칭이 불가능하다. 스냅샷에 이름 없는 항목이 있으면 임의로 처리하지 말고 사용자에게 보고한다.

### 2단계 — 조건 추가 (`report-site/properties/seed/searches.yaml`)

기존 두 항목은 `name`만 고친다. **`id`는 건드리지 않는다** — 기본키이고 `Observation`·`Listing`의 외래키가 걸려 있다.

```yaml
- id: raemian-sur-all
  name: 래미안슈르 84          # 기존: 래미안슈르 전체
- id: raemian-eco-palace-all
  name: 래미안에코팰리스 84     # 기존: 래미안에코팰리스 전체
```

새 단지는 아래 두 모양 중 하나를 따른다. 조사 조건(면적·타입)은 전부 동일하고 **알림 관련 필드만 지역에 따라 다르다.**

```yaml
# 과천·판교 추가분 — 과천센트럴파크푸르지오써밋과 같은 숫자, 급매만 알림
- id: <slug>
  region: 과천                 # 판교 단지는 판교
  name: <단지명> 84
  complex_names: [<네이버 표기 그대로>, <띄어쓰기 변형>]
  search_url: ""
  exclusive_area_m2: 84        # 83~86㎡로 해석된다
  allowed_types: all
  max_price_won: 2550000000
  urgent_price_won: 2450000000
  notify_new: false
  apply_low_floor_discount: true
  enabled: true

# 광교 추가분 — 광교푸르지오월드마크와 같은 알림 방식, 신규만 알림
- id: <slug>
  region: 광교
  name: <단지명> 84
  complex_names: [<네이버 표기 그대로>]
  search_url: ""
  exclusive_area_m2: 84
  allowed_types: all
  max_price_won: null          # 가격 제한 없음 → 급매 판정이 없다
  urgent_price_won: null
  notify_new: true
  apply_low_floor_discount: false
  enabled: true
```

**`complex_names`는 부분 일치다.** `collector.py:190`과 `properties/matching.py:78`이 모두 `alias.replace(" ","") in compact_name`으로 비교한다. 별칭이 짧으면 다른 단지를 삼킨다 — 예를 들어 `판교`만 넣으면 판교 단지 전부가 한 조건에 붙는다. 별칭은 충분히 길게 잡는다.

적용:

```powershell
cd report-site
..\real-estate-finder\.venv\Scripts\python.exe manage.py import_searches
```

### 3단계 — 지역이 셋이 된 결과 문구 정리

`과천`을 서비스 전체 이름처럼 쓰던 곳을 고친다.

| 파일 | 지금 | 바꿈 |
|---|---|---|
| `report-site/report_site/urls.py:26-27` | admin 제목 `과천 관심 매물` | `관심 매물` |
| `report-site/properties/delivery.py:170` | `☀️ 과천 관심 매물이 없습니다.` | `☀️ 관심 매물이 없습니다.` |
| `real-estate-finder/real_estate_finder/cli.py:50` | argparse 설명 `과천 관심 매물 수집기` | `관심 매물 수집기` |

**바꾸지 않는 것 두 가지.** `properties/statistics.py`의 `DEFAULT_REGION = "과천"`은 그대로 둔다(통계 화면과 카카오 통계 한 줄의 기본값). `report/templates/report/stats.html`의 안내 문구 `최근 1개월 · 과천을 봅니다`도 사실과 맞으므로 그대로 둔다.

### 4단계 — 검증

```powershell
cd report-site
..\real-estate-finder\.venv\Scripts\python.exe manage.py check
..\real-estate-finder\.venv\Scripts\python.exe manage.py test

cd ..\real-estate-finder
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m real_estate_finder check-api
```

`manage.py test`는 DB 생성 권한이 필요하다(Known Issues 참고). `check-api`는 활성 조건 수가 6에서 늘었는지 확인하는 용도다.

사용자가 실행할 수동 확인(외부 부작용 있음):

1. `report-site\run-site.bat` **재시작** — 실행 중인 프로세스는 옛 코드를 들고 있다.
2. `real-estate-finder\run-scan.bat` 1회. 단지 수가 두 배가 되므로 수집이 5분에서 10분 안팎으로 늘어난다.
3. 리포트에 새 단지 그룹이 보이는지, 통계 화면 지역 선택에 **판교**가 생겼는지.
4. admin의 `Observation`에서 새 단지 행이 쌓였는지, 제외된 것은 `exclusion_code`가 무엇인지.

### 5단계 — 문서

`.agent/docs/RUNBOOK.md`에 "관심단지를 새로 추가했을 때" 절(= 이 문서의 1~2단계)을 넣고, `.agent/PROJECT_STATE.md`의 단지 수·지역 수를 갱신하고, 이 `Active Work` 절을 완료 기록으로 정리한다. `AGENTS.md`의 프로젝트 개요 한 줄(과천 중심 표현)도 확인한다.

### 위험

- **첫 스캔에서 카카오 알림이 뜬다.** 광교 추가분은 `notify_new: true`라 전 매물이 신규이고, 과천·판교 추가분은 24.5억 이하면 급매로 잡힌다. 한 통으로 묶여 나가므로 스팸은 아니지만 예상하지 못하면 놀랄 수 있다. 사용자에게 미리 알린다.
- **판교에 25.5억/24.5억은 임의의 숫자다.** 사용자가 이 값을 고른 것이며, 판교 시세를 근거로 정한 값이 아니다. 시세가 그보다 낮으면 판교 매물 상당수가 "급매"로 잡히고, 높으면 리포트에서 전부 빠진다. **다만 상한을 넘긴 매물도 `exclusion_code='price'`로 통계에는 남으므로 분포는 정확하다.** 며칠 쌓인 뒤 통계 화면에서 실제 분포를 보고 admin에서 값을 조정하는 것이 바른 순서이며, 이를 사용자에게 제안한다.
- 아파트로 분류되지 않은 관심단지는 이름이 비어 매칭되지 않는다(1단계 경고 참고).
- 별칭 부분 일치로 다른 단지를 삼킬 수 있다(2단계 경고 참고).

## Completed Migration: 수집기 / 애플리케이션 역할 분리 (2026-09-03)

**상태: 이관 완료. 0~9단계와 실제 브라우저 수집 종단 확인까지 모두 끝났다. 남은 결정은 `kakao-image-card` 브랜치를 `main`에 병합할지 여부뿐이다.**

### 왜

이관 시작 당시 `real-estate-finder`는 "조사"만 하는 게 아니라 애플리케이션 전체였다. 수집(`collector.py`), 조건 필터(`parsing.py`), 급매·신규·알림 판정과 상태 diff(`service.py`), 파일 저장(`storage.py`), 표현 포맷(`report.py`), 카드 이미지(`card.py`), 카카오 전송(`notifier.py`)을 모두 소유했다. `report-site`는 DB 없이 finder 코드를 직접 import하는 얇은 뷰 하나뿐이었다. 현재 완료 범위는 아래 단계별 진행 상황을 따른다.

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
- [x] 4. `parsing.py` → `properties/matching.py`, `service.scan()` 판정부 → `properties/scanning.py` + 테스트 이관
- [x] 5. `api` 앱 + Bearer 인증 + 엔드포인트 4개(`health`, `conditions`, `scans`, `digest`). 알림 전송과 digest 본체는 7단계 이관 전까지 명시적 501
- [x] 6. `report` 뷰를 DB 기반으로 전환 (템플릿 무변경)
- [x] 7. `card.py` / `notifier.py` / `publish.py` 이관 + `send_digest`·`preview_card`·`check_report` 관리 명령
- [x] 8. finder 축소 + `api_client.py` + `cli.py` 정리 + `run-scan.ps1` 사전 확인 + `send-report.ps1` 재연결
- [x] 9. `ARCHITECTURE.md`, `RUNBOOK.md`, `AGENTS.md`, 각 `README.md` 갱신

각 단계 끝에서 테스트가 통과하는 상태를 유지하고, 단계를 끝낼 때마다 위 체크박스와 이 문서를 갱신한다. 삭제 범위가 크므로 단계별로 커밋을 나눈다.

### 이어받는 지점 (2026-09-03 갱신)

브랜치 `kakao-image-card`. 코드·문서 이관과 실제 수집 종단 확인을 모두 마쳤다. 아래는 단계별 이력이다.

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
  - `sys.path.insert(0, FINDER_DIR)`는 당시 `report/views.py`의 `FileStore` import 때문에 유지했으며 **6단계에서 둘 다 제거했다.**
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

#### 4단계에서 완료한 코드

- `properties/matching.py`: 가격·층·타입 정규화와 단지명, 면적, 타입, 저층 차감 가격 조건 판정을 Django 모델 입력으로 이관했다. 판정 과정에서 `floor`, `is_low_floor`, 유효 상한가·급매가를 채우고 제외 사유를 반환한다.
- `properties/scanning.py`: `record_scan()`이 한 트랜잭션에서 `Scan`과 수집 원본 전량 `Observation`을 저장하고, 조건 통과분을 `Listing`에 upsert하며, 성공 조건에 한해서만 미관측·탈락 매물을 비활성화한다.
- 최초 급매와 추가 가격 하락만 알림 후보로 만들고, 실제 전송 예정인 경우에만 `last_urgent_alert_price_won`을 갱신한다. smoke 모드는 알림 이력을 소모하지 않는다.
- 트랜잭션이 끝난 뒤 API 계층이 전송할 수 있도록 `ScanDecision`에 알림 후보와 전체 통과 매물을 반환한다. 전송 대상이 없으면 기존 정책과 같은 미전송 사유를 `Scan.notification`에 기록한다.
- 원본 전량·제외 사유, 최초 확인 시각 보존, 급매 재알림, 신규 알림, 실패 조건 비활성화 방지, 잘못된 입력 전체 롤백을 포함한 테스트를 추가했다. Django 테스트 28개와 finder 테스트 81개가 통과했고, 테스트 후 DB 역할을 `NOCREATEDB`로 복구했다.

#### 5단계에서 완료한 코드

- `api` 앱과 `/api/health/`, `/api/conditions/`, `/api/scans/`, `/api/digest/` 라우팅을 추가했다. 네 경로 모두 `Authorization: Bearer <FINDER_API_TOKEN>`을 상수 시간 비교로 검증한다.
- `health`는 PostgreSQL 연결까지 확인하고, `conditions`는 `GlobalRule`과 활성 `SearchCondition`만 JSON으로 반환한다.
- `scans`는 Content-Type과 필드 타입, 성공·실패 조건 중복을 검증한 뒤 `record_scan()`을 호출한다. Bearer 인증된 POST는 CSRF 토큰 없이 사용할 수 있다.
- 아직 카카오 전송 코드가 Django에 없으므로 `notify_urgent=true`, smoke 요청과 `digest`는 쓰기 없이 `notification_not_available` 501을 반환한다. 상태 저장만 필요한 `notify_urgent=false` 스캔은 201로 처리한다. 이 제한은 7단계에서 실제 동기 전송으로 교체한다.
- 인증, 메서드 제한, DB health, 활성 조건 직렬화, 스캔 저장, JSON 오류, 상충 조건, CSRF 면제, 알림 미지원 경로 테스트를 추가했다. Django 테스트 37개가 통과했고 실제 DB 내부 요청에서 health 200, conditions 200, 활성 조건 6개를 확인했다.

#### 6단계에서 완료한 코드

- `properties/report.py`로 가격·면적 문구, 조건별 그룹핑, 가격/최신 매물번호 정렬, 숫자 매물 ID와 `/articles/` 직접 링크만 표시하는 규칙을 이관했다.
- `report/views.py`는 PostgreSQL의 활성 조건·활성 `Listing`을 조회한다. 활성 매물이 없으면 성공 조건이 하나라도 있었던 최근 `Scan` 시각을 `data-observed-at`에 사용한다.
- DB의 `Decimal` 고정 자릿수가 화면에 `84.930`처럼 보이지 않도록 기존과 같은 `84.93` 형식으로 정규화했다.
- `report-site` 설정에서 finder 디렉터리 `sys.path` 삽입을 제거했다. Django 런타임의 finder import와 `FileStore` 의존성은 없다. 남은 `state.json` 참조는 일회성 `import_state`와 그 테스트뿐이다.
- 템플릿은 수정하지 않았고 `data-observed-at` 계약도 유지했다. 실제 이관 데이터로 구형·신형 payload 전체 일치, 단지 6·매물 41·급매 1·기준 시각 일치를 확인했다. Django 테스트 39개와 finder 테스트 81개가 통과했다.

#### 7단계에서 완료한 코드

- `properties/card.py`, `notifier.py`, `publish.py`를 Django 모델과 설정 기반으로 이관하고 `delivery.py`에 전송 조정을 모았다.
- `POST /api/scans/`는 `record_scan()` 트랜잭션이 끝난 뒤 급매·신규가 있으면 동기로 카드를 전송한다. smoke 요청도 전체 카드를 전송하며 급매 알림 이력은 소모하지 않는다.
- `POST /api/digest/`는 PostgreSQL의 활성 매물 전체를 전송한다. 이전의 `notification_not_available` 501 제한은 제거했다.
- 카드 렌더링 또는 이미지 전송이 실패하면 알림 대상 중심의 200자 이하 텍스트로 폴백한다. 텍스트까지 실패하면 `NotificationFailure`에 메시지·링크·오류를 기록하고 API는 502를 반환한다.
- 공개 리포트가 카드와 같은 관측 시각을 서빙할 때만 `전체 매물 보기` 링크를 붙인다. 빈 URL, HTTP, localhost와 loopback 주소는 공개 링크로 인정하지 않는다.
- `send_digest`, `preview_card`, `check_report` Django 관리 명령을 추가했다. 실제 DB 41개 매물로 `preview_card`가 1080×8168 PNG(616,559바이트)를 만들었고 육안 레이아웃을 확인했다. `check_report`는 DB의 UTC 시각과 공개 리포트의 +09:00 시각이 같은 순간임을 확인해 통과했다.
- 실제 카카오 메시지는 보내지 않았다. 모든 전송 테스트는 대체 sender로 수행했고 Django 테스트 49개, `manage.py check`, `makemigrations --check`가 통과했다. 테스트 후 `property_report` 역할은 `NOCREATEDB`로 복구했다.

#### 8단계에서 완료한 코드

- `real_estate_finder/api_client.py` 신설. stdlib `urllib`로 `health`/`conditions`/`scans`/`digest` 4개 요청을 보낸다. 토큰은 `report-site/.env`의 `FINDER_API_TOKEN`을 그대로 읽어 양쪽이 어긋나지 않는다. 실패는 행동 가능한 문구로 바뀐다 — 연결 실패는 `run-site.bat`을, 401은 토큰 설정을 지목하고, 거부된 요청은 서버가 준 사유를 그대로 옮긴다. 스캔 POST는 카드 렌더링·카카오 전송을 포함하므로 타임아웃 600초, 읽기 요청은 20초다.
- `cli.py`를 수집 전용으로 재작성했다. 명령은 `check-api`, `browser-login`, `scan-once`, `smoke-test`, `collect-favorites` 5개다. `scan-once`는 **브라우저를 열기 전에 서버 health를 먼저 확인**하고, 한 조건 안의 중복 매물을 제외한 뒤 POST한다(서버는 중복이 있으면 스캔 전체를 롤백한다). 실행 잠금(`data/run.lock`)은 `cli.py`의 작은 컨텍스트 매니저로 남겼다.
- 삭제: `config.py`, `service.py`, `storage.py`, `report.py`, `card.py`, `notifier.py`, `publish.py`, `config/searches.yaml`.
- `parsing.py`는 `parse_price_won`과 `normalize_type_name`만 남겼다. 수집한 텍스트를 숫자로 바꾸는 일은 수집의 일부지만, 층 규칙과 임계값은 판정이라 사라졌다.
- `models.py`는 `SearchCondition`(API 응답용 `from_api()` 포함)과 원본 `Listing`, `iso_now()`만 남겼다. `Listing`에서 `floor`, `is_low_floor`, `effective_max_price_won`, `effective_urgent_price_won`을 제거했고 `collector.py`의 두 생성 지점도 함께 고쳤다.
- `run-scan.ps1`은 4단계가 되었다. 1단계가 `check-api`이며 실패하면 브라우저를 띄우지 않고 `report-site\run-site.bat`을 먼저 실행하라고 안내한다.
- `send-report.ps1`은 `report-site`로 이동해 `manage.py send_digest`를 호출한다. 브라우저·로그인·웹 서버가 필요 없다.
- **`scheduled-run` 명령을 제거했다.** 평일 digest 시각은 이제 `GlobalRule`에 있고, 이 명령을 부르는 Windows 작업 스케줄러 항목이 실제로 등록돼 있지 않음을 확인했다. 정기 발송이 다시 필요해지면 Django 쪽에서 되살린다.
- 테스트: `tests/test_core.py`는 수집기 헬퍼와 가격·타입 정규화만 남기고, `tests/test_api_client.py`를 추가했다(토큰 누락, Bearer 헤더, JSON 본문, 연결 실패 문구, 400/401 처리, 중복 제거). 판정·리포트·카드·publish 테스트는 코드와 함께 report-site로 갔다.
- 검증: finder 테스트 32개 통과. 실제 DB에 붙은 임시 서버(8010 포트)에 대해 `check-api`가 활성 조건 6개를 응답했고, 잘못된 본문 POST가 서버의 400 메시지(`observations는 배열이어야 합니다.`)로, 잘못된 토큰이 401로 돌아오는 것을 확인했다. 행을 쓰지 않는 요청만 보냈으므로 DB는 바뀌지 않았다. `manage.py check`와 `makemigrations --check` 통과.

#### 9단계에서 완료한 문서

- `.agent/docs/ARCHITECTURE.md`를 역할 경계 중심으로 다시 썼다(350 → 273줄). 수집기 절과 애플리케이션 절을 나누고, "이 작업에는 어떤 파일을 읽는가" 표를 `properties/`·`api/`·`report/` 기준으로 다시 매핑했다. 에이전트가 걸려 넘어질 결과 세 가지를 명시했다 — 스캔이 서버를 요구한다, 코드 변경 후 서버 재시작이 필요하다, 테스트에는 DB 생성 권한이 필요하다.
- `.agent/docs/RUNBOOK.md`: 진입점이 셋이 되었고 리포트 서버를 먼저 켠다. PostgreSQL 준비와 `import_searches`를 최초 설정에 넣었고, digest·카드 미리보기·리포트 확인을 Django 관리 명령으로 바꿨다. "서버가 꺼져 있어도 스캔은 된다"는 설명을 반대로 고쳤다.
- `AGENTS.md`: 역할 경계를 규칙으로 못박았다(판정·표현·전송 코드를 수집기로 되돌려 놓지 않는다). 검증 명령과 비밀 키 목록도 갱신했다.
- `real-estate-finder/README.md`와 루트 `README.md`를 다시 썼다. 사라진 명령과 설정 파일 설명을 걷어내고 실행 순서를 명확히 했다.
- 문서 전체에서 `state.json`, `searches.local.yaml`, `scheduled-run`, `validate-config`, `explain-filters`와 옛 CLI 명령 참조가 남아 있지 않음을 확인했다.

#### 종단 확인 결과 (2026-09-03)

새 구조로 실제 수집을 완주했고 아래를 모두 확인했다.

| 확인 항목 | 결과 |
|---|---|
| 수집기가 새 API에 붙는가 | `check-api`가 활성 조건 6개 응답 |
| 원본이 전량 저장되는가 | `Observation` +120건, 그중 제외 78건에 사유 기록 |
| 조건 통과분이 갱신되는가 | `Listing` +12건, 활성 41→42 |
| 실패 없이 완주하는가 | 6개 조건 전부 성공, `failed_conditions` 비어 있음 |
| 미전송 사유가 남는가 | `Scan.notification`에 급매 재알림 억제와 `notify_new` 꺼짐이 기록됨 |
| 급매 알림 이력이 보존됐는가 | 활성 급매 1건이 재전송되지 않음 |
| admin에서 조회되는가 | 토큰 경로 admin 로그인과 `exclusion_reason` 필터 확인 |

#### 이후 추가된 작업

- 2026-09-03: 가격 통계 화면과 카카오 메시지 개편. 위 "가격 통계 기능" 절 참고.

#### 남은 결정

`kakao-image-card` 브랜치를 `main`에 병합할지 결정한다.

진행 중인 작업은 위쪽 **"Active Work: 관심 단지 추가 + 슈르·에코팰리스 표기 수정"** 절에 있다. 그것이 지금 이어서 할 일이다.

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

### Django admin 접속

- 주소는 리포트와 같은 토큰 경로 아래다: `.../r/<REPORT_PATH_TOKEN>/admin/`. 실제 토큰은 `report-site/.env`에 있고 `run-site` 창이 `Local admin:` 줄로 출력한다. 여기에는 적지 않는다.
- 슈퍼유저 `admin`이 생성돼 있다. 비밀번호는 문서에 기록하지 않았으며, 잊었다면 `manage.py changepassword admin`으로 재설정한다.
- 조회에 쓰는 화면: `Observation`(제외 사유는 `exclusion_reason` 필터), `Listing`(`active` 필터), `Scan`(실행 이력과 미전송 사유), `Search condition`(가격·면적 조건 편집).
- admin은 Tailscale Funnel 공개 주소로도 열린다. 로그인 화면이 인터넷에 노출돼 있으므로 비밀번호는 강해야 한다.

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

- **`report-site/run-site.bat`이 실행 중이 아니면 공개 리포트 주소가 죽는다.** PC 종료·절전도 마찬가지다. 자동 시작을 등록하지 않기로 했으므로(Key Decisions 참고) 리포트를 외부에서 열어야 할 때 사용자가 직접 켜야 한다. 다행히 조용히 깨지지는 않는다 — 서버가 없으면 `is_live()`가 실패해 카카오 메시지에서 두 버튼이 빠지고 텍스트만 나간다.
- **이제 스캔 자체가 리포트 서버 실행을 요구한다.** `run-scan.ps1`의 1단계 `check-api`가 실패하면 브라우저를 열지 않고 멈춘다. 예전처럼 "서버가 꺼져 있어도 스캔은 된다"가 더 이상 성립하지 않는다. 자동 시작(작업 스케줄러 로그온 트리거) 등록 여부를 다시 판단할 시점이다.
- **전환 후 Django admin이 공개 URL에 노출된다.** 토큰 경로 뒤에 두더라도 로그인 화면이 인터넷에 열린다. 강한 비밀번호가 필요하다.
- 예전 Codex Sites 주소(`https://my-property-report-20260902.ssong7988.chatgpt.site`)는 더 이상 갱신되지 않는다. 루트 `.env`의 `KAKAO_REPORT_URL`을 지우면 이 오래된 주소로 폴백하므로 비우지 않는다.
- 휴대전화에서 `127.0.0.1`/`localhost`는 서버 PC를 가리키지 않으며 카카오 웹 도메인으로도 부적합하다(Tailscale Funnel 주소를 써야 하는 이유).
- 토큰 경로(`REPORT_PATH_TOKEN`)는 우발적 노출만 막는다. 주소가 유출되면 인증 없이 누구나 볼 수 있다.
- **코드를 바꿨으면 리포트 서버를 재시작해야 한다.** 실행 중인 프로세스는 옛 코드를 들고 있다. 이 구조에서는 재시작을 잊어도 조용히 넘어가지 않고 `check-api`가 404로 실패해 드러난다.
- **급매가 아니면 과천·판교 조건에서는 카카오톡이 오지 않는다. 정상이다.** `notify_new`가 켜진 조건은 광교 4개(광교푸르지오월드마크·광교더리브·광교경남아너스빌·광교센트럴뷰)다. 과천·판교 10개는 신규 매물이 나와도 알리지 않으며 급매 기준을 통과할 때만 보낸다. 이미 같은 가격 이하로 알린 급매도 더 내려가지 않으면 다시 알리지 않는다. 사유는 항상 콘솔과 `Scan.notification`에 남으므로, 조용하다고 느껴지면 먼저 그것을 읽는다. 지금 전체를 받고 싶으면 `send-report.bat`이다.
- 루트와 예전 UI(`property-report-site/site-app/`)가 중첩 Git 저장소로 남아 있다. 그 디렉터리를 다시 건드릴 일이 생기면 UI 커밋 누락이나 루트 포인터만 변경되는 실수에 유의한다.
- 마지막 `npm audit` 결과는 취약점 11개(낮음 1, 보통 2, 높음 8)였다(예전 UI 저장소 기준, 더 이상 서빙 경로가 아니므로 우선순위 낮음).
- **Django 테스트에는 DB 생성 권한이 필요하다.** `property_report` 역할에 `CREATEDB`가 없어 `manage.py test`가 테스트 DB를 만들지 못한다. 테스트 동안만 부여했다가 되돌린다(`ALTER ROLE property_report CREATEDB;` → `NOCREATEDB;`).
- **검색 조건을 admin에서 바꾸면 과거 관측은 옛 기준으로 판정된 채 남는다.** 통계가 새 조건과 어긋나므로 `manage.py reclassify_observations`로 다시 판정한다. 다시 판정은 *현재* 조건을 쓰므로 당시 조건과 다를 수 있다 — 의도된 절충이다.
- 공개 리포트에는 매물 정보가 노출되므로 민감한 개인 데이터나 인증 정보를 포함하지 않아야 한다.
- **관심단지 하나가 실패하면 스캔 전체가 실패로 끝난다(2026-09-04 관측).** `collect_favorites_snapshot()`이 단지 목록을 순회하다 예외가 나면 그 자리에서 전체가 중단되고, 활성 조건 전부가 실패로 보고된다. 이제 단지별 진행 로그(`관심단지 N/총 'OO' 확인 중...`)와 필터 에러에 단지명이 붙어 어디서 막혔는지는 바로 보이지만, 부분 실패를 허용하도록 격리하는 작업은 아직 하지 않았다.
- **Edge 창을 최소화하거나 백그라운드에 두면 스캔이 "네이버 로그인 상태가 만료되었습니다"로 오탐 실패할 수 있다(2026-09-04).** Chromium이 비활성 탭의 렌더링을 늦춰, `page.goto()` 직후 로그인 헤더가 아직 안 그려진 상태를 로그아웃으로 오인했다. `_raise_if_blocked()`에 짧은 재시도와 `page.bring_to_front()`를 추가해 완화했지만, OS 창이 완전히 최소화된 경우까지는 보장하지 못한다 — 스캔 중에는 Edge 창을 보이는 상태로 두는 것이 가장 확실하다(`.agent/docs/RUNBOOK.md` 참고).

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
