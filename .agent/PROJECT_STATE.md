# Project State

마지막 갱신: 2026-09-05 (**금융자산 수집을 mable 웹에서 H-able 데스크톱으로 옮겼다.** 웹은 6시간마다 자동 로그아웃돼 평일 18:30 무인 수집에 맞지 않는다. 웹 수집기는 지우지 않고 `stock-importer/stock_importer/web/`으로 옮겨 재워 뒀다. H-able 경로는 `hable/`에 있고, 화면 [1285] 총자산현황 하나로 다섯 계좌를 다 읽는다. **아직 실제 데이터로 종단 성공하지 못했다 — H-able이 자동 로그아웃된 상태여서 그리드가 비어 있다.**) 서비스 namespace는 부동산 `/property/`, 주식 `/stock/`, 공통 운영 `/common/`으로 분리하며 Dagster는 한 인스턴스를 공유한다. 개발 브랜치는 `dev`, 버전은 루트 `VERSION`의 `devX.Y.Z` 형식이다.

## Current Architecture

- 코드 경계, 실제 데이터 흐름과 작업별 최소 읽기 경로는 `.docs/ARCHITECTURE.md`에 정리되어 있다. `.agent/`에는 최신 운영 상태인 이 파일만 두고 장기 상세 문서는 `.docs/`에서 관리한다.
- `real-estate-finder/`는 네이버 부동산 매물을 수집해 `report-site` API로 넘기기만 한다. 조건 판정·상태·표현·전송 코드는 없다.
- `report-site/portfolio/`가 금융자산 도메인을 소유한다 — 계좌·종목·자산분류·목표 비중·국민연금 기준, 수집 자료 저장, 비중·리밸런싱, 현금흐름 보정 수익률과 MDD. 부동산 `properties/`와는 모델도 URL도 계산도 섞이지 않고 DB와 admin만 공유한다.
- `report-site/properties/`가 카카오 메시지 정책을 소유하고, `kakao-notifier/`의 인증 토큰/API 어댑터를 호출한다. finder 쪽 중복 코드는 8단계에서 삭제했다.
- `report-site/`(Django + waitress)가 PostgreSQL을 요청마다 읽어 화면을 렌더링한다. 부동산 화면은 `/property/`, 금융자산 화면은 `/stock/`, 공통 Dagster 운영 화면은 `/common/` namespace다. `REPORT_PATH_TOKEN`을 채우면 두 namespace 앞에 `/<TOKEN>/`이 붙는다. 빌드나 배포 단계는 없다.
- 예전 Next.js/Codex Sites UI였던 `property-report-site/`는 운영 코드가 참조하지 않는 것을 확인한 뒤 2026-09-04 저장소에서 제거했다. 현재 웹 화면은 `report-site/`만 소유한다.
- 운영 조회 진입점은 Dagster의 `scan_job`이고, 수집기 venv에서 Python `run-scan` 명령을 실행해 Edge CDP `http://127.0.0.1:9222`에 연결한다. `run-scan.bat`/`.ps1`은 같은 Python workflow를 부르는 수동 호환 wrapper다.
- 급매가 아닌 전체 결과를 카카오톡으로 보내는 진입점은 `real-estate-finder/send-report.bat`이며 `report-site`의 `manage.py send_digest`를 실행한다. 브라우저·로그인·웹 서버가 필요 없고 DB만 있으면 된다.
- 리포트 서버 실행 진입점은 `report-site/run-site.bat` 또는 `report-site/run-site.ps1`이다.
- `scan-once`는 수집 결과를 `POST /api/scans/`로 넘기고, Django가 급매 또는 신규가 있을 때만 카카오톡을 보낸다. 보내지 않은 경우에도 사유가 응답의 `scan.notification`으로 돌아와 콘솔에 출력되고 `Scan` 행에도 남는다.
- 검색 설정은 PostgreSQL의 `SearchCondition`이며 Django admin에서 고친다. `report-site/properties/seed/searches.yaml`은 초기 시드일 뿐이다.
- `record_scan()`의 트랜잭션이 알림 전송보다 먼저 커밋된다. 그래야 `is_live()`로 확인하는 시점에 이미 이번 조회 결과가 서빙되고 있다.
- `is_live()`(`report-site/properties/publish.py`)는 리포트 서버(그리고 Tailscale Funnel)가 살아있고 이번 조회를 서빙 중인지만 확인한다.
- 외부 공개는 Tailscale Funnel로 `report-site/`의 8000번 포트를 노출해 고정 HTTPS 주소(`https://<pc>.<tailnet>.ts.net`)를 얻는 방식이다. 현재 경로 토큰은 비워 두었다.
- `KAKAO_REPORT_URL`은 루트 `.env`에, 선택 경로 토큰 `REPORT_PATH_TOKEN`은 `report-site/.env`에 둔다. 토큰을 비우면 `/property/`·`/common/` namespace를 쓰고, 채우면 둘 앞에 `/<TOKEN>`이 붙는다. 둘 다 Git에서 제외한다.
- 네 진입점(`run-site.ps1`, `run-scan.ps1`, `send-report.ps1`, `run-dagster.ps1`)은 저장소 루트 `start-logging.ps1`을 통해 그날 콘솔 출력을 `.logs/<앱>/<날짜>.log`에 남긴다(30일 보관). 네이티브 프로세스 출력은 그 프로세스가 끝나는 시점에 기록되므로 크래시 진단에는 쓸 수 있지만 건강한 상태의 실시간 tail 용도는 아니다. 자세한 내용은 `.docs/RUNBOOK.md`의 "로그 보기" 참고.
- Dagster의 run/event-log/schedule 이력은 `property_report` DB의 `dagster` schema에 있다(Django는 `public`). SQLite로 떨어지지 않도록 `dagster_project/data/dagster.yaml`을 `run-dagster.ps1`이 매 실행마다 다시 쓴다. 연결 옵션은 `-c search_path=dagster -c timezone=UTC`이며 타임존 지정은 필수다(아래 Known Issues 참고).

위 구조는 2026-09-03에 끝난 역할 분리 이관의 결과다. 그 배경과 단계별 이력은 아래 "Completed Migration" 절에 있다.

## Current State

- 검색 조건은 과천 6개·광교 4개·판교 4개, 총 14개가 활성 상태다. 새 8개 조건은 DB까지 반영됐지만 아직 첫 실제 스캔 전이라 새 단지의 `Observation`·`Listing`은 없다.
- **Tailscale Funnel 전환은 완료됐고 종단 확인까지 끝났다.** 공개 리포트는 Funnel 주소로 서빙되며, 실제 카카오톡 카드에 `전체 매물 보기` 버튼이 새 주소로 포함되는 것까지 확인했다.
- 공개 리포트: `https://desktop-477.tailf8d9d1.ts.net/property/report/` (Tailscale Funnel → 로컬 `127.0.0.1:8000` 프록시). 가격 통계는 `/property/statistics/`, Dagster 요약은 `/common/dagster/`, 네이티브 UI는 `/common/dagster/console/`다.
- Tailscale 설치·로그인·Funnel 활성화 완료(`tailscale funnel --bg 8000`). `tailscaled`는 Windows 서비스라 재부팅 후 Funnel 설정이 자동 복구된다.
- 카카오 개발자 콘솔의 `앱 > 제품 링크 관리 > 웹 도메인`에 위 호스트를 등록 완료. (`플랫폼 키` 메뉴가 아니다 — `kakao-notifier/README.md:31` 참고.)
- `report-site/.env`의 `REPORT_PATH_TOKEN`은 현재 빈 값이고, 루트 `.env`의 `KAKAO_REPORT_URL`은 `/property/report/` 주소를 쓴다(둘 다 Git 제외).
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
- Django admin은 현재 `.../property/admin/`이며 `admin` 슈퍼유저 로그인을 확인했다. 토큰을 켜면 `.../<TOKEN>/property/admin/`으로 이동한다. `Observation`의 `exclusion_code` 필터로 제외 사유를 구분해 조회할 수 있다.

### 가격 통계 기능 (2026-09-03 추가)

- 현재 `/property/statistics/`가 날짜별 호가 분포를 캔들(최저~최고 심지와 위아래 가로 끝선, 1분위~3분위 상자, 평균 가로선)로 보여준다. 토큰을 켜면 `/<TOKEN>/property/statistics/`로 바뀐다. 서버가 좌표까지 계산하는 inline SVG이며 JS 의존성이 없다.
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
- **단지 select가 선택한 지역과 무관하게 항상 전체 단지를 보여주던 것을 고쳤다(2026-09-04).** 지역을 과천으로 골라도 단지 드롭다운에는 광교·판교 단지까지 optgroup으로 다 나왔다 — 지역 select는 전체 목록을 유지해야 하지만 단지 select는 선택한 지역으로 좁혀야 한다는 지적이었다. `report/views.py`에 `_grouped_conditions(conditions, region)` 헬퍼를 추가해 `index()`·`stats()` 양쪽에서 `scope.region` 기준으로 단지 optgroup을 필터링하도록 재사용했다. 템플릿은 이미 `grouped_conditions`를 그대로 순회하므로 수정하지 않았다.

## Active Work: KB증권 금융자산 포트폴리오 (2026-09-05 설계·Django 구현·수집기 1차)

**수집 방식이 바뀌었다. H-able 데스크톱에서 CSV를 저장하는 대신, `https://mablewide.kbsec.com/go.able`의 내자산 화면을 브라우저로 직접 읽는다.** 네이버 매물 수집기와 같은 모델이다 — 로그인은 사람이 하고, 프로그램은 로그인된 Edge에 CDP로 붙어 화면에 보이는 표만 읽는다. H-able 자동화와 CSV 파서는 이제 계획에 없다.

**상태: `report-site/portfolio/` 애플리케이션과 두 화면, 그리고 `stock-importer/` 수집기를 만들었고 테스트를 통과한다. 실제 화면을 상대로 한 종단 실행은 아직 안 해 봤다. Dagster 스케줄·카카오 전송도 아직 없다.** 기존 부동산 서비스에 주식 기능을 섞는 것이 아니라, 같은 Django/PostgreSQL/Kakao/Dagster 기반 위에 `/stock/` 도메인을 별도로 추가한다.

### 이번에 실제로 만든 것 (2026-09-05)

- `report-site/portfolio/` 앱과 migration `0001_initial`. 모델 9개: `AssetClass`(설계서의 8개에 더한 것 — 목표 비중과 국민연금 매핑이 붙을 안정적인 단위가 필요했다), `InvestmentAccount`, `Instrument`, `ImportRun`, `PositionSnapshot`, `CashFlow`, `PortfolioTarget`, `BenchmarkAllocation`, `DailyPortfolioMetric`.
- `portfolio/importing.py` — 멱등 수집. 같은 파일 해시는 아무것도 바꾸지 않고, 같은 날 재다운로드는 그 자료가 만든 행만 교체하며, 겹치는 거래기간은 `external_key`로 걸러진다. 완결성 판정(`latest_complete_date()`)이 여기 한 곳에만 있다.
- `portfolio/performance.py` — Modified Dietz 일간 수익률(수집을 건너뛴 구간의 흐름은 경과일로 가중), 성과지수, 누적 투자손익, 낙폭과 MDD. 자산분류별 수익률은 분류 안팎의 매수·매도를 그 분류의 현금흐름으로 처리한다.
- `portfolio/allocation.py` + `portfolio/display.py` — 현재 비중, 목표 대비 리밸런싱(만원 반올림 잔액 표시), 국민연금 비교(원본 99.8% 보존, 비교할 때만 정규화). 미분류는 분모에서 빠지고 화면에 제외 금액으로 명시된다.
- `POST /stock/api/import-runs/`, `GET /stock/api/status/`. 토큰은 `STOCK_API_TOKEN`으로 분리했고, 값이 없으면 401이 아니라 503을 돌려준다(미설정이 개방으로 퇴화하지 않게).
- `/stock/allocation/`, `/stock/performance/` 두 화면. 차트 좌표는 서버가 만들고 브라우저는 차트 라이브러리를 받지 않는다 — 부동산 통계 화면과 같은 방식이다.
- `portfolio/seed/portfolio.yaml` + `manage.py import_portfolio_seed`. `my_etf_list.csv`의 계좌 별칭·자산분류와 `국민연금 포트폴리오.xlsx`의 A1:B6을 옮겼다. 보유수량·매입금액은 옮기지 않았다. 다시 돌려도 admin에서 손으로 정한 분류를 되돌리지 않는다.
- `manage.py rebuild_portfolio_metrics`. 평소에는 수집 API가 새 완전 수집일이 생길 때 자동으로 부른다.
- 테스트 40개(`portfolio/tests/`). 손계산한 Modified Dietz/MDD 사례, 멱등성, 완결성, 리밸런싱 부호·합계, 국민연금 정규화, API 인증, 빈 화면까지 포함한다.

### 수집기 (`stock-importer/`, 2026-09-05)

**수집 대상이 웹에서 H-able 데스크톱으로 바뀌었다.** 이유는 하나다 - mable 웹은
6시간마다 자동 로그아웃된다. 웹 코드는 `stock_importer/web/`으로 옮겨 그대로 남겼고
(`web-*` 명령으로 여전히 돌아간다) Dagster에는 연결하지 않는다.

#### H-able에서 실측으로 확인한 것

| 확인한 것 | 결과 |
|---|---|
| 창 구조 | 메인 창 class `Hable`, 화면은 MDI 자식이고 제목이 화면번호로 시작한다(`1285 총자산현황`). **창 제목이 화면을 집는 손잡이다** |
| 그리드 셀 | **창이 아니다.** Win32로도 UIA로도 글자를 읽을 수 없다 |
| 그리드 헤더 | `SysHeader32`가 둘 있지만 `item_count`가 0인 빈 껍데기다. 컬럼 이름조차 못 읽는다 |
| 툴바(엑셀·인쇄·설정·?·조회) | `Button`이 아니다. `BM_CLICK` 불가, 좌표 클릭뿐 |
| Ctrl+C | 클립보드에 아무것도 안 남는다 |
| 우클릭 | 컨텍스트 메뉴가 뜨지 않는다(`PostMessage`도 실제 마우스도) |
| 창 복원 | `ShowWindow(SW_RESTORE)`는 안 먹힌다. `WM_SYSCOMMAND/SC_RESTORE`만 먹혔다 |
| `PrintWindow` | 이 앱은 거절한다(MDI 자식도 최상위 창도). 화면 캡처는 앞으로 꺼낸 뒤 긁는 수밖에 없다 |
| 비트 수 | H-able은 32비트, 우리 Python은 64비트. **구조체를 건네는 메시지는 쓰지 않는다** |
| `kbopenapi.exe` | 매매 API가 아니라 Matomo 행동로그 프록시(`loghub.kbsec.com`) |

**그래서 남은 길은 툴바의 엑셀 내보내기 하나다.** 좌표는 그리드 판의 오른쪽
끝을 기준으로 잡아(`export.py`의 `TOOLBAR_FROM_RIGHT`) 창을 옮겨도 견딘다.
저장 대화상자는 표준 `#32770`이라 컨트롤로 정직하게 다룬다.

#### 아직 확인 못 한 것 — 여기서 막혔다

**H-able이 "타 기기에서 로그인 되어 자동 로그아웃 됩니다" 상태다.** 그리드가
비어 있고 비밀번호 칸도 풀렸다. 그래서 엑셀 버튼을 눌러도 저장 대화상자가 뜨지
않는다(좌표는 화면 그림과 대조해 맞는 것을 확인했다). **다음 사람이 할 첫 일은
H-able 재로그인이고, 그다음 `hable-probe`가 엑셀 내보내기 성공을 보고하는지 보는
것이다.**

주의: mable 웹과 H-able은 **동시에 로그인할 수 없다**. 한쪽이 다른 쪽을
쫓아낸다(멀티로그인은 KB증권 설정에서 따로 켜야 한다). 웹 수집기를 진단용으로
돌리면 H-able 세션이 끊긴다.

#### 계좌번호 마스킹 규칙이 바뀌었다

H-able은 `338-711-781-01`처럼 네 덩어리로 준다. 가운데를 전부 가리던 기존 규칙은
`338-***-***-01`을 만들어 **앞자리가 같은 실제 계좌 둘을 한 값으로 뭉갠다**(실제
계좌 4개 중 2개가 `338`로 시작한다). 지금은 **두 번째 덩어리만** 가린다 -
`338-***-781-01`, `338-***-400-01`. 웹 형식(`338-263-400 01`)도 그대로 처리된다.

#### 두 경로가 공유하는 것 (수집 방식과 무관하게 유효)

- **계좌번호는 마스킹해서 보낸다.** 원본은 어디에도 저장하지 않는다. 어느 번호가
  ISA인지는 사람만 알므로 admin의 `masked_number`에 넣고, 서버의 `_resolve_account`가
  그 값으로 계좌를 찾는다. 모르는 번호는 짐작하지 않고 400으로 돌려보낸다.
- **`file_hash`는 파일이 아니라 그 계좌에서 읽은 행들의 SHA-256이다.** 파일을 받지
  않는 경우가 있어 뜻만 같게 옮겼다 - 하루에 두 번 돌려도 값이 같으면 서버가 200
  `duplicate`로 끝낸다.
- **화면에 종목코드가 없다.** 종목명에서 유니코드 슬러그를 만들어 코드로 쓴다
  (`KODEX 미국나스닥100(H)` → `kodex-미국나스닥100-h`). 그래서 `Instrument.code`에
  `allow_unicode=True`를 켰다(migration `0002`). 코드가 보이는 화면을 나중에 찾으면
  그쪽을 쓴다.
- **표를 값으로 바꾸는 순수 함수는 `parsing.py` 한 곳에 있다.** 헤더 이름으로 열을
  찾으므로 웹이든 H-able이든 같은 코드를 쓴다. H-able [1285]에는 `현재가`가 없어
  `price`를 비워 보낸다(서버에서 선택 값이다).
- 명령: `hable-probe` · `hable-collect` · `hable-import` · `check-api`, 그리고 재워 둔
  `web-browser` · `web-probe` · `web-collect`.
- 테스트 43개(`stock-importer/tests/`). 실제 화면의 열·표기를 픽스처로 쓴다 - 1285의
  중복 `구분` 열, 네 덩어리 계좌번호가 서로 구분되는지, 탭 구분 복사 파싱, ETF 배지
  분리, 손실 부호, 합계 줄 거르기, 외화 원화평가액 누락 거절, 순서가 달라도 같은 해시.

#### 재워 둔 웹 경로에 남은 기록 (`stock_importer/web/`)

- 전용 Edge를 따로 쓴다. CDP 포트 9223, 프로필 `kbsec-edge`. 네이버 스캔(9222/
  `naver-land-edge`)과 창도 로그인 세션도 섞이지 않는다.
- 표를 DOM 구조가 아니라 좌표로 읽는다(`web/grid.js`). mable은 웹 HTS라 표가
  `<table>`이 아닐 수 있고 클래스 이름은 배포마다 바뀐다. 사람이 보는 헤더 글자를
  앵커로 삼고 셀 좌표로 행·열을 복원한다.
- 탭이 말한 건수와 읽은 건수가 다르면 저장하지 않고 멈춘다. **H-able 경로에는 이
  대조가 없다** - 화면이 기대 건수를 알려주지 않는다.

### 아직 하지 않은 것과 이유

- **H-able에서 실제 데이터를 한 번도 못 읽었다.** 위 '여기서 막혔다' 참고.
- **[1285] 화면을 자동으로 열지 않는다.** 사람이 열어 둔 화면을 읽는다. 화면번호 입력창 구조를 아직 안 봤다.
- **조회 버튼을 누르지 않는다.** 계좌 비밀번호를 H-able 설정에 저장해 두어야 조회가 되는데, 그 저장은 사용자가 한다.
- (재워 둔 웹 경로) 내자산 화면까지의 메뉴 자동 클릭이 없다. 실제 DOM을 아직 못 봤다. 지금은 사람이 로그인하고 내자산 화면을 열어 두면 수집기가 최대 5분 기다렸다가 표가 보이는 순간 이어간다.
- **입출금·거래를 수집하지 않는다.** v1은 잔고만이다. 외부 입출금이 생기기 전까지는 수익률이 정확하고, 생긴 뒤에는 그 구간이 왜곡된다. 해당 화면을 `probe`로 확인한 뒤 붙인다.
- **해외주식 탭은 원화평가액 열을 찾지 못하면 실패로 멈춘다.** 환율을 지어내지 않는다는 기존 결정 그대로다. 현재 해외주식은 0건이다.
- **Dagster `stock_portfolio` asset group과 평일 18:30 스케줄이 없다.** 수집기가 없으면 실행할 것이 없다.
- **카카오 요약과 버튼 2개를 붙이지 않았다.** 보낼 완전 스냅샷이 아직 없다.
- **`/stock/admin/`은 별도 admin이 아니라 `/property/admin/`으로 보내는 리다이렉트다.** `admin.site.urls`를 두 번 마운트하면 `admin:` URL namespace가 갈라진다. 포트폴리오 모델은 기존 admin에 등록돼 있다.

### 이미 끝난 설치 (2026-09-05)

`manage.py migrate`(표 9개 + `0002`), `manage.py import_portfolio_seed`(자산분류 8·계좌 5·국민연금 5),
`report-site/.env`의 `STOCK_API_TOKEN` 생성, `restart-site.ps1`로 서버 재시작까지 끝났다.
`/stock/allocation/`·`/stock/performance/`가 200으로 응답하고 `/stock/api/status/`는
토큰 인증으로 동작한다. 계좌 5개는 아직 전부 `계좌번호 미등록`이다.

### 다음 사람이 먼저 할 일

1. **H-able에 다시 로그인한다.** 지금 "타 기기에서 로그인 되어 자동 로그아웃 됩니다"
   상태다. mable 웹과 동시에 로그인할 수 없으니 웹 세션은 닫아 둔다.
2. H-able 설정에서 **계좌 비밀번호를 저장**한다. 저장돼 있어야 [1285] 조회가 된다
   (프로그램은 이 값을 절대 만지지 않는다).
3. [1285] 총자산현황을 열고 `전체`로 조회한다.
4. `stock-importer/`에서 `..\real-estate-finder\.venv\Scripts\python.exe -m stock_importer hable-probe`.
   **`엑셀 내보내기: N행` 이 나오는지가 이번 관문이다.** 실패하면 같은 명령이 남긴
   `data/hable-1285.png`(Git 제외)에서 툴바 버튼 위치를 다시 재 `hable/export.py`의
   `TOOLBAR_FROM_RIGHT`를 고친다.
5. `-m stock_importer hable-collect`로 읽은 결과를 화면과 눈으로 대조한다.
6. 나온 마스킹 계좌번호(`338-***-781-01` 형식)를 admin의 투자 계좌 5개에 넣는다.
7. `-m stock_importer hable-import` → `/stock/allocation/`에서 비중과 미분류 금액 확인 →
   admin에서 새 종목을 분류한다.

### 목표와 확정된 선택

- 관리 범위는 **금융자산만**이다. 부동산 평가액은 주식 비중·수익률·국민연금 비교에 합치지 않는다.
- KB증권의 종합위탁·ISA·연금·퇴직연금 계좌를 포함한다.
- H-able 로그인은 사용자가 완료한다. 프로그램은 인증서 비밀번호나 OTP를 저장·우회하지 않고, 로그인 이후 계좌 순회·조회·파일 저장을 자동화한다.
- Dagster가 **평일 18:30**에 H-able 로그인 상태를 확인한다. 로그인돼 있으면 하루 1회 수집하고, 아니면 실패 사유를 카카오로 알린다.
- 첫 버전부터 잔고뿐 아니라 거래·입출금 자료도 수집해 외부 현금흐름을 보정한 수익률과 MDD를 계산한다.
- 정확한 성과 이력은 서비스의 첫 완전 수집일부터 시작한다. 현재 보유수량을 과거 가격에 소급 적용하지 않는다.
- KB 밖 자산은 첫 버전에서 제외한다. 향후 별도 API 연동 후 전체 성과에 합친다.
- 리밸런싱은 현재 평가총액을 유지하는 **매수·매도 금액**으로 제시한다. 주문 실행은 하지 않는다.
- 카카오는 이미지가 아니라 요약 텍스트 1통과 `비중·리밸런싱`, `수익률·MDD` 버튼 2개를 보낸다.
- 국민연금과는 국내주식·해외주식·채권·대체투자의 공통분류로 변환해 비교한다. 종목별 매핑은 admin에서 수정한다.

### 입력 자료와 먼저 검증할 사실

- H-able `[0345] 실시간잔고(주식)`은 종목별 보유수량·평균단가·현재가·매입금액·평가금액·평가손익 등을 제공하고 엑셀 저장 버튼이 있다.
- H-able 표의 공통 우클릭 메뉴는 Excel·CSV·HTML·TXT 내보내기를 제공한다. CSV를 우선하되 실제 화면에서 안정적이지 않으면 XLSX를 받아 같은 정규화 과정으로 처리한다.
- `[0328] 종목별기간실현손익`은 기간별 실현손익을 제공하지만 외부 입출금을 완전히 설명하는지는 실제 계좌 자료로 확인해야 한다.
- 공식 참고:
  - `https://help2.kbsec.com/0345.html`
  - `https://help2.kbsec.com/pdf/0184.pdf`
  - `https://help2.kbsec.com/0328.html`
- 구현 첫 단계에서 종합위탁·ISA·연금·퇴직연금 각각의 실제 잔고, 예수금, 거래·입출금 파일을 한 번씩 수동 저장한다. 이를 고정 테스트 자료로 삼아 화면 번호, 컬럼, 인코딩, 계좌 식별값, 해외주식 원화평가 방식과 조회 가능 기간을 확정한다.
- `C:/Users/userpc/PycharmProjects/projects/stock_management/test/data/my_etf_list.csv`의 계좌 별칭과 종목 분류를 초기 시드 자료로 쓴다. 이 파일에는 종합위탁·ISA·개인연금·퇴직연금·업비트와 금·기타 주식·미국 주식·채권·코인·한국 주식 분류가 있다.
- `C:/Users/userpc/PycharmProjects/projects/stock_management/test/data/국민연금 포트폴리오.xlsx`의 `Sheet1!A1:B6`을 국민연금 초기 비교 자료로 쓴다. 원본 합계 99.8%는 보존하고 비교 차트를 그릴 때만 100%로 정규화한다.
- 같은 워크북의 개인 목표 비중 예시는 합계가 100%를 넘으므로 그대로 운영 데이터로 넣지 않는다. 목표는 사용자가 admin에서 새로 입력하고 합계 100% 검증을 통과해야 한다.

### 역할 경계와 수집 흐름

```text
stock-importer/                    수집 전용
  H-able 로그인 상태 확인
  → 계좌/화면 순회
  → CSV/XLSX 저장 및 구조 검증
  → 정규화한 원본을 Bearer API로 전달
           ↓
report-site/portfolio/             Django 애플리케이션
  PostgreSQL 저장·분류·성과 계산
  → /stock/allocation/
  → /stock/performance/
  → 카카오 요약 + 버튼 2개
           ↑
Dagster stock_portfolio asset group
  평일 18:30 실행·재시도·실패 알림
```

- 수집기는 H-able 파일 구조를 읽고 원본 필드를 정규화하는 일까지만 한다. 자산분류·목표·국민연금 매핑·성과·리밸런싱·표현·카카오 정책은 Django가 소유한다.
- Windows UI Automation의 UIA/Win32 컨트롤 식별자를 우선 사용한다. 해상도와 창 위치에 깨지는 좌표 클릭이나 이미지 인식은 대체 방법으로만 쓴다.
- 계좌별로 잔고·예수금·거래·입출금 자료를 저장하고 파일 쓰기가 끝난 뒤 크기와 헤더가 안정됐는지 확인한다.
- 계좌번호는 수집 단계에서 마스킹한다. 인증값·원본 파일·다운로드 폴더·로그는 Git에서 제외한다.
- 필수 계좌 하나라도 실패하면 실행 전체를 `incomplete`로 남기고 그날의 공개 최신값과 성과를 갱신하지 않는다. 성공한 중간 원본은 진단용으로 남길 수 있다.
- 파일 해시와 계좌·자료종류·기준일 고유키로 같은 다운로드 또는 겹치는 거래기간을 다시 처리해도 중복 저장되지 않게 한다.
- H-able 화면 변경, 로그인 누락, 파일 검증 실패, 일부 계좌 누락은 조용히 넘어가지 않고 원인과 계좌를 기록한 뒤 기존 `send_alert` 경로로 알린다.

### PostgreSQL 모델 초안

| 모델 | 책임 |
|---|---|
| `InvestmentAccount` | 금융기관, 마스킹 계좌 식별자, 별칭, 종합위탁/ISA/연금/퇴직연금 유형, 활성 여부 |
| `Instrument` | 종목코드, 종목명, 통화, 사용자 자산분류, 국민연금 공통분류 |
| `ImportRun` | 기준일, 계좌, 파일 해시, 자료 종류, 행 수, 성공/불완전/실패 상태와 오류 |
| `PositionSnapshot` | 일별 계좌·종목 수량, 평균단가, 원가, 현재가, 평가액, 평가손익, 원화환산액 |
| `CashFlow` | 입금·출금·배당·이자·수수료·세금·매수·매도·계좌 간 이체와 외부 현금흐름 구분 |
| `PortfolioTarget` | 적용 시작일과 사용자가 입력한 자산분류별 목표 비중 |
| `BenchmarkAllocation` | 국민연금 기준일, 원본 분류, 원본 비중, 표시용 정규화 비중과 출처 |
| `DailyPortfolioMetric` | 평가액, 순입금, 투자손익, 일간/누적 수익률, 고점, 현재 낙폭, MDD |

- Django migration만 사용한다. 기존 프로토타입의 `Base.metadata.drop_all()` 방식은 절대 가져오지 않는다.
- 목표 비중은 같은 적용일의 활성 행 합계가 100%일 때만 활성화한다.
- 처음 보는 종목을 임의 분류하지 않는다. `미분류`로 저장하고 admin에서 분류하기 전에는 제외 금액을 화면에 명시한다.
- 현금·예수금의 초기 사용자 분류는 `안전자산`, 국민연금 공통분류는 `채권`으로 두되 admin에서 바꿀 수 있다.
- 해외주식은 가능하면 H-able이 제공한 원화평가액으로 계좌 합계를 대조하고 원통화 값도 함께 보존한다. 원화평가 기준이 제공되지 않으면 외부 환율을 임의로 섞지 말고 해당 계좌 구현을 보류한다.

### 공개 API와 화면

- `POST /stock/api/import-runs/`
  - 수집기 전용 Bearer 인증 API다.
  - 계좌별 잔고·현금흐름·기준일과 수집 메타데이터를 받는다.
  - 한 날짜의 모든 필수 계좌가 도착해야 완전한 포트폴리오 스냅샷을 확정한다.
- `GET /stock/api/status/`
  - 마지막 완전 수집일, 계좌별 성공 여부, 미분류 종목 수를 반환한다.
- `GET /stock/allocation/`
  - 현재 금융자산 총액과 계좌별 최신 여부
  - 사용자 분류별 현재 비중 파이차트
  - 목표 비중과 현재 비중 차이
  - 자산분류별 매수·매도 필요액
  - 국민연금 공통분류 비교
- `GET /stock/performance/`
  - 총평가액, 최초 평가액, 누적 순입금, 누적 투자손익
  - 누적 수익률, 현재 낙폭, MDD
  - 전체 및 자산분류별 성과선
  - 1개월·3개월·6개월·1년·전체 기간 선택
  - 종목/분류별 1개월·3개월 수익률. 관측기간이 부족하면 추세 판정을 하지 않는다.
- `/stock/admin/`
  - 계좌, 종목분류, 목표 비중, 국민연금 매핑, 수집 실행을 관리한다.
  - 기존 선택적 `REPORT_PATH_TOKEN` 규칙을 동일하게 적용한다.

### 계산 규칙

- 현재 비중 = 분류별 최신 원화평가액 / 분류 가능한 금융자산 총액.
- 목표 평가액 = 분류 가능한 금융자산 총액 × 목표 비중.
- 리밸런싱 금액 = 목표 평가액 - 현재 평가액. 양수는 매수, 음수는 매도다.
- DB에는 원 단위 값을 보존하고 화면에서는 만원 단위로 반올림한다. 반올림 잔액과 미분류 제외액을 함께 표시한다.
- 리밸런싱은 자산분류 단위의 참고 금액이다. ISA·연금·퇴직연금의 매매/인출 제약을 고려한 계좌별 주문안이나 자동주문은 범위 밖이다.
- 총 포트폴리오 외부 현금흐름은 실제 입금과 출금만 수익률 분모를 조정한다. 매수·매도와 포함 계좌 사이 이체는 내부 이동, 배당·이자·수수료·세금은 투자성과로 처리한다.
- 일별 현금흐름 시각이 있으면 Modified Dietz 방식으로 일간 수익률을 만들고 연결한다. 날짜만 있으면 장 마감 시점 흐름이라는 명시적 가정을 사용한다.
- 누적 투자손익 = 현재 평가액 - 최초 평가액 - 누적 순외부입금.
- MDD는 평가액 자체가 아니라 현금흐름 보정 누적 성과지수의 직전 고점 대비 하락률 중 최솟값이다.
- 자산분류별 성과에서는 분류 사이의 매매 이동을 해당 분류의 현금흐름으로 처리해 보유액 변화와 가격 수익을 구분한다.
- 서비스 시작 전 성과를 현재 보유수량과 외부 시세로 합성하지 않는다.

### 국민연금 비교 규칙

- 개인의 원래 분류 파이차트는 그대로 유지하고 비교 영역에서만 공통분류로 변환한다.
- 초기 기본 매핑:
  - 한국 주식 → 국내주식
  - 미국 주식·기타 해외 주식 → 해외주식
  - 채권·현금성 안전자산 → 채권
  - 금·코인 등 → 대체투자
- 위 매핑은 시드일 뿐이며 `Instrument` 또는 사용자 자산분류 단위로 admin에서 수정 가능해야 한다.
- 국민연금의 대체투자와 개인의 금·코인이 동일한 상품군은 아니라는 안내를 화면에 표시한다.

### Dagster와 카카오

- 기존 단일 Dagster 인스턴스에 `stock_portfolio` asset group을 추가한다.
- 기본 lineage는 `hable_exports → portfolio_snapshots → portfolio_metrics → stock_digest`다.
- 평일 18:30에 실행하고 같은 날짜의 완전 스냅샷이 이미 있으면 중복 발송하지 않는다.
- 카카오 요약에는 기준일, 금융자산 총액, 누적 투자손익, 누적 수익률, 현재 MDD, 가장 큰 리밸런싱 항목을 넣는다.
- 버튼은 정확히 두 개다: `비중·리밸런싱`, `수익률·MDD`.
- PostgreSQL 커밋과 두 공개 페이지의 최신성 확인이 끝난 뒤에만 카카오를 보낸다. 서버가 최신 자료를 서빙하지 못하면 버튼을 붙이지 않고 실패로 기록한다.
- `definitions.py`에 잡을 추가할 때 `/common/dagster/`의 정적 `JOBS` 요약도 같은 변경에서 갱신한다.

### 구현 순서

1. **(대체됨)** H-able 데스크톱 샘플 수집은 하지 않는다. mable 웹 화면을 직접 읽는 방식으로 바꿨다.
2. **(완료)** `portfolio` Django 앱, 모델, migration, admin과 초기 분류/국민연금 시드를 만든다.
3. **(완료)** import API와 해시 기반 멱등성·완결성. 계좌번호로 계좌를 찾는 경로(`_resolve_account`)를 더했다.
4. **(절반)** `stock-importer/`로 mable 내자산 표를 읽어 계좌별로 전송한다. 실제 화면 종단 실행과 메뉴 자동 클릭이 남았다.
5. **(완료)** 현금흐름 보정 수익률·손익·MDD 및 리밸런싱 계산을 구현한다.
6. **(완료)** `/stock/allocation/`, `/stock/performance/` 두 페이지를 만든다.
7. **(미완)** Dagster asset group과 평일 18:30 스케줄, 실패 알림을 연결한다.
8. **(미완)** 카카오 요약과 두 버튼을 연결하고 실제 휴대전화에서 한 차례 종단 확인한다.
9. **(진행)** `.docs/ARCHITECTURE.md`, `.docs/RUNBOOK.md`, 구성요소별 문서와 이 상태 문서를 실제 구현 결과로 갱신한다.

### 테스트와 완료 조건

- 실제 내자산 화면의 열과 표기를 픽스처로 고정해 파싱을 테스트한다(`stock-importer/tests/test_parsing.py`). CSV/XLSX·인코딩 테스트는 수집 방식이 바뀌어 필요 없다.
- 컬럼 변경, 빈 파일, 저장 중인 파일, 계좌 불일치, 일부 계좌 실패가 공개 스냅샷을 갱신하지 않는지 확인한다.
- 같은 파일과 겹치는 거래기간을 반복 처리해도 잔고와 현금흐름이 중복되지 않아야 한다.
- 종목 평가액 합계와 H-able 계좌 요약 평가액이 허용 오차 내에서 일치해야 한다.
- 목표 비중 100% 검증, 매수·매도 부호, 반올림 잔액, 전체 리밸런싱 합계가 허용 오차 내 0인지 확인한다.
- 입금·출금·배당·매매·수수료가 섞인 고정 사례를 수작업 기대값과 비교해 TWR, 투자손익, 고점과 MDD를 검증한다.
- 데이터 없음, 하루치만 있음, 미분류 종목, 오래된 계좌, 해외 원화평가액 누락 화면을 테스트한다.
- 로그인된 H-able에서 정상 종단 실행하고 로그인되지 않은 18:30 실행이 카카오 장애 알림으로 끝나는지 확인한다.
- PostgreSQL 저장 → 두 공개 페이지 최신성 → 카카오 요약과 버튼 2개를 실제 휴대전화에서 확인해야 완료다.

### 범위 밖과 주의사항

- 주식 주문, 자동매매, 계좌별 주문 배분은 하지 않는다.
- KB 외 거래소·증권사 자동연동은 후속 작업이다.
- 인증서 비밀번호·OTP·계좌 비밀번호를 코드, 문서, 로그에 기록하지 않는다.
- H-able에서 특정 계좌의 잔고·입출금 자료를 충분히 내보낼 수 없다면 추정값으로 메우지 않는다. 해당 계좌와 계산 한계를 명시하고 구현 결정을 다시 받는다.
- 기존 `stock_management/test/update_db.py`의 DB 초기화 방식과 오늘 보유량을 과거 가격에 적용한 프로토타입 수익률/MDD는 운영 설계의 근거로 사용하지 않는다.

## Active Work: Dagster로 스케줄 구동 (2026-09-04, 실제 설치·실행·검증 완료)

**상태: 설계가 아니라 실제로 설치하고 돌려서 검증까지 끝났다.** Airflow/WSL2 계획(아래 절)이 VT-x 펌웨어 블로커로 보류되자, 사용자가 "WSL2가 필요한지 다시 보자, 필요해지면 그때 Airflow로 가고 그 전까지는 Dagster로 간다"고 결정했다. **Dagster는 순수 Python이라 WSL 없이 이 PC에서 네이티브로 돈다** — 그게 이 전환의 핵심 이유다. `airflow/dags/`는 지우지 않고 그대로 남겨 뒀다("향후에 필요하면 airflow로 전환하던지 할게").

### 왜 이번엔 "검증됨"이라고 말할 수 있는가

Airflow 작업 때는 WSL이 없어 전부 문서 조사만으로 코드를 짰고 그렇게 명시했다. 이번엔 막힌 게 없어서 실제로 했다:

- `dagster_project/.venv`(Python 3.11 — Dagster 문서가 "3.13 권장"이라 하고, 검색된 Windows gRPC 크래시 리포트가 구버전 wheel 쪽이라 3.14 대신 안정적인 3.11을 골랐다)에 `dagster==1.13.21`, `dagster-webserver==1.13.21`을 실제로 `pip install`했다.
- `definitions.py`를 실제로 `python -c "import definitions"`로 로드해 잡·스케줄 구성에 오류가 없음을 확인했다.
- `dagster dev -f definitions.py --host 127.0.0.1 --port 3000`을 실제로 띄워 **gRPC 크래시 없이** 정상 기동함을 확인했다(검색 당시 Windows에서 `cygrpc` 관련 크래시 리포트가 있었던 부분이라 특히 이걸 확인해야 했다).
- `runsOrError` GraphQL 쿼리를 curl로 실제 호출해 응답 형태를 확인했다. **`status` 필드는 대문자(`"SUCCESS"`, `"FAILURE"`)이고 `startTime`/`endTime`은 ISO 문자열이 아니라 float epoch seconds다** — 둘 다 추측이 아니라 실측이다.
- 과거 `site_watchdog_job` 수동 실행 검증에 더해, 통합 후에는 `property_pipeline_job`의 네 가지 모드(서버만, 서버→스캔, 최신 스캔 있음→리포트, 최신 스캔 없음→재스캔→리포트)를 외부 호출 스텁으로 `execute_in_process()` 실행해 순서와 성공을 확인했다. 실제 스캔·카카오 전송은 이 검증에서 호출하지 않았다.
- **asset 전환(2026-09-04) 후 같은 검증을 다시 했다.** `_run_powershell`·`_run_manage`를 스텁으로 바꾸고 네 잡을 전부 `execute_in_process()`로 돌려, 각 잡이 정확히 자기 몫의 스크립트만 부르고(`server_check_job`→`ensure-site.ps1`만, `scan_job`→`ensure-site`+`run-scan`, `morning_report_job`→ 거기에 `send-report` 추가, `restart_report_site_job`→`restart-site.ps1`만) 선택된 asset이 전부 머티리얼라이즈되며 메타데이터에 수집 카운트 다섯 항목이 붙는 것을 확인했다. `ensure_fresh` 회귀도 명시적으로 확인했다 — 07:00 이후 성공 수집이 있으면 `run-scan.ps1`이 **호출되지 않고**, 머티리얼라이즈 메타데이터에 `재수집: 생략`이 남는다. 잘못된 `mode` 값은 `ValueError`로 거부되고 수집을 부르지 않는다.
- **세 스케줄의 `run_config`가 각자의 잡에 대해 실제로 유효한지** `evaluate_tick()` + `validate_run_config()`로 확인했다. 구 이름(`scan_step`)을 넣으면 `DagsterInvalidConfigError`로 거부되는 것도 함께 확인했다 — 설정 오타가 8시 정각이 아니라 Launch 시점에 걸린다는 뜻이다.
- **2026-09-04 함수 기반 실행 전환 뒤 finder 테스트 37개와 Dagster 정의 로드·네 job의 `execute_in_process()`를 다시 검증했다.** 외부 호출을 스텁으로 막은 상태에서 `scan_job`은 `ensure-site.ps1` 뒤 Python `real_estate_finder run-scan`만, `morning_report_job`은 여기에 직접 `manage.py send_digest`만 추가로 호출했다. PowerShell wrapper는 실제 job 경로에서 호출되지 않았다. 실제 네이버 수집·카카오 전송은 부작용 때문에 실행하지 않았다.
- **재시작 후 살아 있는 Dagster에 GraphQL로 직접 물어 반영을 확인했다.** 최종 형태(asset 2개)에서 `naver_listings`가 `graphName=naver_listings`, `opNames=['naver_listings.ensure_site_op', 'naver_listings.run_scan_op']`로 graph-backed asset임을 확인했고, 세 스케줄 모두 각자의 잡을 가리키며 `RUNNING`으로 복귀했다. 스케줄 이름을 바꾸지 않아 기존 schedule storage 상태가 그대로 이어졌다.
- **`scan_status --json`을 운영 DB에 대해 실제로 실행했다.** 오늘 마지막 성공 수집(17:00) 기준 수집 204·조건 충족 93·급매 1·제외 111이 나왔고, 기존 exit-code 계약(있으면 0, 없으면 1)이 그대로임을 `--since=07:00`과 `--since=23:59` 양쪽으로 확인했다. dagster venv에서 finder venv의 python을 거쳐 호출해도 한글 키가 깨지지 않는 것을 `ensure_ascii` 덤프로 확인했다.
- **`alert_on_failure` 훅이 실제로 실패 시 발동하는지**는 별도 스텁 스크립트로 검증했다 — `_run_manage`를 가짜 함수로 바꿔치기하고 일부러 실패하는 옵을 하나 만들어 `execute_in_process()`로 돌린 뒤, 훅이 정확히 `"doomed_job/doomed_op 실패: boom - deliberate test failure"` 형태로 `send_alert`를 호출했음을 어서션으로 확인했다. **실제 카카오 메시지는 보내지 않았다** — `_run_manage`를 스텁으로 바꿨기 때문에 진짜 `manage.py send_alert`가 호출되지 않았다.
- `run-dagster.ps1`도 실제로 실행해 `data/dagster.yaml`이 생성되고(telemetry 끔) 서버가 뜨는 것까지 확인했다.
- `report/dagster_client.py`의 `fetch_status()`를 report-site venv에서 **실제 Django 설정과 실제로 뜬 Dagster 웹서버**를 상대로 호출해 `reachable=True`가 나오는 것까지 확인했다(모킹이 아니라 진짜 HTTP 왕복).
- **실행하지 않은 것(의도적으로):** 실제 `run-scan.ps1`과 `send-report.ps1`을 연달아 호출하는 종단 실행은 네이버 스캔·카카오 전송이라는 부작용이 있어 하지 않았다. 두 스크립트 자체는 독립적으로 검증돼 있고, 이번에는 Dagster 배선을 스텁으로 검증했다.
- 스모크 테스트에 쓴 프로세스는 전부 PID로 찾아 종료했고, `.dagster_home`/로그 파일도 지웠다. 커밋에는 소스 파일 4개(`definitions.py`, `requirements.txt`, `run-dagster.ps1`, `run-dagster.bat`)만 들어간다 — `.venv`와 `data/`는 `.gitignore`에 있다.

### 아키텍처 — Airflow 버전과의 결정적 차이

Airflow는 WSL2 안에서 돌아 Windows 쪽 작업(브라우저, Postgres, Django)을 interop(`wslpath`, `powershell.exe -Command "...; exit $LASTEXITCODE"`)으로 건너가야 했다. **Dagster는 이 PC에서 직접 네이티브 Windows 프로세스로 돌기 때문에 그 경계 자체가 없다:**

- `.ps1` 실행: `subprocess.run(["powershell.exe", "-File", str(path)])` — WSL 경로 변환 불필요.
- `manage.py` 실행: `subprocess.run([str(python_exe), str(manage_py), *args])` — PowerShell `-Command` 레이어도, `exit $LASTEXITCODE` 트릭도 불필요. `subprocess`의 `returncode`가 곧 `manage.py`의 실제 종료 코드다.

이 단순함이 Dagster를 고른 실질적인 이유다 — WSL이 없어도 된다는 것뿐 아니라, 있었어도 코드가 훨씬 단순했을 것이다.

### asset 체인과 시간대별 실행

`dagster_project/definitions.py` 하나에 전부 있다.

**2026-09-04에 op 기반에서 asset 기반으로 바꿨다.** 이전에는 `property_pipeline_job` 하나가 `ensure_site → scan_step → report_step`을 항상 전부 실행하고, 세 스케줄이 run config로 뒤 두 단계를 no-op으로 만들었다. 지금은 asset `naver_listings → morning_report`가 있고, 각 스케줄이 어디까지 실행할지 고른다. `naver_listings`는 `ensure_site_op → run_scan_op` 두 op을 품은 `graph_asset`이다.

등록 잡은 네 개다. asset job 둘(`scan_job`, `morning_report_job`)과 op job 둘(`server_check_job`, `restart_report_site_job`). `server_check_job`은 `naver_listings` 안에서 쓰는 것과 **같은 `ensure_site_op`을 재사용**하므로 서버 확인 로직이 두 벌로 갈라지지 않는다. `restart_report_site_job`(2026-09-04 추가)은 스케줄 없는 잡이며 report-site 코드를 바꾼 뒤 Dagster UI에서 수동으로 Launch Run 한다.

**업무 job은 `.bat`/업무용 `.ps1`을 실행하지 않는다.** `run_scan_op`은 수집기 전용 venv의 `python -u -m real_estate_finder run-scan`을, `morning_report`는 finder venv로 Django `manage.py send_digest`를 직접 실행한다. Dagster venv에 Playwright/Django를 합치거나 앱 모듈을 직접 import하지 않는 이유는 의존성 충돌과 장시간 브라우저 작업의 프로세스 격리를 유지하기 위해서다. Windows 장기 프로세스 수명주기(`ensure-site.ps1`, `restart-site.ps1`)에는 PowerShell이 적합하므로 그대로 둔다. `run-scan.ps1`은 Python workflow를 한 줄 호출하는 수동 호환 wrapper로 축소했다.

전환으로 없어진 것: `scan_step.mode="skip"`과 `report_step.enabled`. 남은 설정 손잡이는 `run_scan_op.mode`(`run` | `ensure_fresh`) 하나뿐이다. graph_asset이라 run config 경로가 한 겹 깊다 — `ops.naver_listings.ops.run_scan_op.config.mode`. 새로 생긴 것: Catalog의 lineage 그래프, 그리고 수집할 때마다 그 `Scan` 행의 수집 수·조건 충족 수·급매 수·제외 수가 머티리얼라이즈 메타데이터로 붙는다(`manage.py scan_status --json`을 새로 추가해 되읽는다). 잡 이름이 스케줄별로 갈라져서 실행 이력에서 어떤 성격의 런인지도 이제 잡 이름만으로 구분된다.

1. `server_only_schedule` — 7·8·12·17시를 제외한 매시 정각. `server_check_job`(=`ensure_site_op`만) 실행. 설정 값이 아예 없다.
2. `scan_schedule` — `0 7,12,17 * * *`. `scan_job`(=`naver_listings`, `mode: run`). 신규 급매 또는 `notify_new` 일반 신규의 카카오는 `record_scan()`이 처리한다.
3. `morning_report_schedule` — `0 8 * * *`. `morning_report_job`(=`naver_listings → morning_report`, `mode: ensure_fresh`). DB에서 07:00 이후 성공 스캔을 확인하고, 없으면 스캔을 재실행한 뒤 전체 리포트를 보낸다. 수집을 생략해도 `naver_listings`는 머티리얼라이즈된다 — "매물이 최신이다"라는 결과는 같기 때문이다.
4. `alert_on_failure` — 네 잡 모두에 걸려 있고 재시도(`RetryPolicy(max_retries=1, delay=300)`)를 다 쓴 뒤 `manage.py send_alert`를 부른다.
5. `restart_report_site_job` — `report-site/restart-site.ps1`을 실행한다. 8000번 포트를 듣는 `python` 프로세스를 찾아 종료(다른 이름의 프로세스면 건너뛰고 경고만 남긴다)하고, 포트가 풀릴 때까지 최대 20초 기다린 뒤 `run-site.ps1`을 hidden으로 새로 띄우고 `check-api`로 최대 60초 재확인한다. `real-estate-finder`는 스캔·리포트 전송이 매번 새 subprocess로 돌기 때문에 이런 재시작 잡이 필요 없다.

**Dagster 자신(`definitions.py`)의 재시작은 job으로 만들 수 없다** — 자기 자신을 실행 중인 프로세스를 자기 job이 끄면 그 실행 자체가 중단된다. 대신 독립 스크립트 `dagster_project/restart-dagster.bat`(→ `restart-dagster.ps1`)을 추가했다(2026-09-04). 3000번 포트의 기존 `python` 프로세스를 종료 → 포트 해제 대기(최대 20초) → `run-dagster.ps1`을 hidden으로 새로 띄움 → GraphQL(`{__typename}`)로 최대 60초 재확인, 구조는 `restart-site.ps1`과 동일하다. `run-dagster.bat`도 기존 프로세스를 자동으로 끄지 않으므로(포트 3000이 이미 쓰이면 새 프로세스가 바인딩 실패), `definitions.py`를 고친 뒤에는 이 스크립트로 직접 재시작해야 한다.

### 공통 Dagster 웹 UI — 요약 `/common/dagster/`, 네이티브 `/common/dagster/console/`

Airflow 화면(현재 `/property/airflow/`, 토큰 사용 시 `/<TOKEN>/property/airflow/`)과 나란히 유지한다. **Airflow 화면은 지우지 않았다** — `AIRFLOW_API_URL`이 비어 있으면 여전히 "설정되지 않았습니다"를 보여줄 뿐 죽지 않는다.

- `report/dagster_client.py` — `runsOrError` GraphQL 쿼리 하나만 쓴다(위에서 실측 확인). **작업/스케줄 목록은 GraphQL로 조회하지 않는다** — 깨지기 쉬운 내부 쿼리 대신 `definitions.py`와 손으로 맞추는 정적 요약(`JOBS`)을 쓴다. 2026-09-04 asset 전환으로 스케줄된 잡 이름이 셋 다 바뀌어서 `JOBS`도 함께 갱신했다. **이 손 동기화는 실제로 한 번 어긋났다** — `restart_report_site_job`을 추가하고도 요약을 안 고쳐서 현재 `/common/dagster/`인 화면이 등록 잡을 계속 1개로 표시했다(2026-09-04 수정). 잡·스케줄을 추가하거나 이름을 바꾸면 같은 변경 안에서 `JOBS`도 고친다. 잡 개수는 이제 `{{ jobs|length }}`로 렌더링하고, 스케줄 없는 잡도 "수동 실행"으로 표에 남는다.
- Django 요약 화면은 `/common/dagster/`에 있고 `@staff_member_required`를 유지한다. 실제 Dagster 웹 UI와 실행 목록은 `/common/dagster/console/`·`/common/dagster/console/runs`다.
- `run-dagster.ps1`이 `report-site/.env`의 선택적 `REPORT_PATH_TOKEN`을 읽어 path prefix를 만들며, 값이 생기면 `/<TOKEN>/common/dagster/console/`로 바뀐다. Tailscale Funnel mount도 경로 변경 때 함께 갱신해야 한다.
- 2026-09-04 namespace 전환 때 report-site와 Dagster를 재시작하고 Funnel mount를 `/common/dagster/console`로 옮겼다. 공개 `/property/report/`, `/property/statistics/`, `/common/dagster/console/runs`는 HTTP 200이고 `/common/dagster/`는 의도대로 admin 로그인으로 302, GraphQL은 200이다. 옛 `/report/`·`/statistics/`·`/dagster/`·`/admin/`·`/dagster/console/runs`는 404이며 `check_report`도 새 URL로 통과했다.
- 새 route reverse와 Dagster GraphQL client 단위 테스트 8개, `manage.py check`, `makemigrations --check --dry-run`, PowerShell 문법 검사는 통과했다. DB 기반 테스트 48개는 운영 PostgreSQL 역할에 `CREATEDB`가 없어 테스트 DB 생성 단계에서 실행되지 않았다.
- Dagster를 처음 다루는 사람을 위해 `.docs/dagster_project/`에 코드 지도, PostgreSQL과 Dagster 메타데이터의 차이, console/Funnel 연결, 시간대별 설정, Launchpad 수동 실행 예시와 장애 확인 절차를 정리했다.
- 같은 수준의 구성요소별 문서로 `.docs/real-estate-finder/`와 `.docs/report-site/`를 추가했다. 수집기는 Edge/CDP·관심단지·묶음 매물·전체 실패 보호·API 전달과 운영 진단을, Django는 모델·트랜잭션·판정/알림 정책·통계 모집단·API/카카오 계약·서버/admin 운영을 코드 기준으로 나눠 설명한다.
- `.docs/kakao-notifier/`에 모듈 경계, OAuth 최초 인증, 액세스/리프레시 토큰 수명주기, 텍스트·다중 버튼·이미지 API, Django 동적 로딩 경로, 운영 점검과 장애 대응을 소스 기준으로 정리했다. 현재 운영 발송은 Django가 메시지 정책을 결정하고 `kakao-notifier`는 인증·HTTP 어댑터 역할만 한다.
- 기존 상세 문서를 저장소 루트 `.docs/`로 옮기고 `AGENTS.md`, README, 실행 스크립트 주석, 설정 설명과 상태 문서의 경로 참조를 함께 갱신했다.

### 앱별 날짜 로그 + Dagster 저장소 PostgreSQL 이전 (2026-09-04 완료)

**계기: 서버가 백그라운드로 돈다는 것 자체는 장점이지만, 실패해도 이유를 볼 수 없었다.** `ensure-site.ps1`이 `Start-Process -WindowStyle Hidden`으로 리포트 서버를 띄우는데 리다이렉션이 없어 출력이 통째로 버려졌고, `settings.py`에 `LOGGING`이 없어 `DEBUG=False`에서 뷰 500 에러가 어디에도 안 남았다.

- 저장소 루트 `start-logging.ps1`(신설, `load-env.ps1`과 같은 방식으로 dot-source)이 `Start-AppLog -App '<이름>'` 함수를 제공한다. `report-site/run-site.ps1`, `real-estate-finder/run-scan.ps1`·`send-report.ps1`, `dagster_project/run-dagster.ps1` 네 진입점 모두에 두 줄씩 추가했다. `.logs/<앱>/<yyyy-MM-dd>.log`에 `Start-Transcript -Append`로 기록하고 시작 시 30일 지난 파일을 지운다. `ensure-site.ps1` 자신에는 일부러 넣지 않았다 — 같은 날짜 로그 파일을 `run-site.ps1`과 동시에 열게 되기 때문이다.
- **`Start-Transcript`의 실제 캡처 시점을 직접 검증했다.** Windows PowerShell 5.1에서 네이티브 프로세스의 stdout/stderr는 그 프로세스가 **끝나는 시점에** 한꺼번에 transcript에 기록되고, 떠 있는 동안 실시간으로는 안 찍힌다. 크래시·정상 종료·Ctrl+C 전부 이 경로로 잡힌다 — 서버가 기동 직후 실패하는, 정확히 사용자가 원한 시나리오다. 반대로 몇 주째 멀쩡히 도는 waitress의 요청 로그를 실시간 tail하는 용도는 아니다. 이 구분은 리다이렉션 유무에 따라 갈린다 — `Start-Process`에 `-RedirectStandardOutput`을 붙이면 실시간으로 잡히지만(별도 테스트로 확인), 그러려면 스크립트 구조를 더 바꿔야 해서 이번 범위에서는 하지 않았다.
- **실제 회귀 재현으로 확인했다.** `report-site/.env`를 잠시 치우고 `ensure-site.ps1`과 똑같이 `run-site.ps1`을 숨김 콘솔로 띄웠더니, 이전에는 통째로 사라지던 `report-site\.env not found...` 오류가 파일·행 번호까지 그대로 `.logs/report-site/`에 남았다. 확인 후 `.env`는 원복했다.
- `report_site/settings.py`에 `LOGGING`을 추가해 `django.request`(뷰 500)를 `mail_admins`(설정 안 됨이라 무음) 대신 stdout으로 보낸다. 파일 핸들러는 두지 않았다 — `send_digest`/`send_alert`/`scan_status`/`check_report`가 같은 설정으로 뜨는 별도 프로세스라 파일을 무조건 붙이면 Windows에서 `WinError 32`로 충돌한다. Django 테스트 클라이언트로 뷰에서 강제로 `RuntimeError`를 던져 트레이스백이 타임스탬프와 함께 stdout에 찍히는 것을 실제로 확인했다.
- `.gitignore`에 `.logs/`를 추가했다(`**/logs/`는 `.logs`를 매칭하지 않는다).
- **Dagster의 run/event-log/schedule storage를 SQLite에서 `property_report` DB의 `dagster` schema로 옮겼다.** 아무도 고른 값이 아니라 `dagster.yaml`에 `storage:`가 없어 떨어진 기본값이었다. `property_report`가 DB 소유자라 `CREATE SCHEMA dagster AUTHORIZATION property_report;`에 superuser가 필요 없었다. `dagster-postgres==0.29.21`(+ `psycopg2-binary`)을 `dagster_project/.venv`에 설치했다 — dagster 본체와 버전 번호 체계가 다르다(`dagster==1.13.21`인데 `dagster-postgres`는 0.29대).
- `run-dagster.ps1`이 `report-site/.env`의 `POSTGRES_PASSWORD`를 읽어(토큰을 읽는 것과 같은 방식) `$env:DAGSTER_PG_PASSWORD`로 넘기고, `data/dagster.yaml`을 **매 실행마다 다시 쓴다** — 예전의 "파일 없을 때만 생성" 로직을 유지했다면 이미 diskette에 있던 telemetry-only 파일이 영원히 안 바뀌는 함정이 있었다.
- `search_path=dagster`가 실제로 세션에 적용되는지 `dagster_postgres.get_conn_string()` + SQLAlchemy로 사전 확인(`current_schema()` → `'dagster'`)한 뒤 적용했다. 적용 후 `information_schema.tables`로 Dagster 테이블 9개가 전부 `dagster` schema에 있고 `public`(Django, 16개 그대로)에는 하나도 안 생겼음을 확인했다.
- 옛 SQLite 파일은 지우지 않고 `data/history.sqlite.bak`, `data/schedules.sqlite.bak`로 이름만 바꿔 보존했다(검증 며칠 뒤 삭제 예정). 실행 이력은 이관 도구가 없어 새로 시작한다 — 며칠치뿐이라 손실을 감수했다.
- 재시작 검증: 새 schema에서 실제 job을 2회 실행(`SUCCESS`)했고, Dagster를 완전히 껐다 켠 뒤에도 `dagster.runs`에서 그 기록이 그대로 조회됐다 — `data/history`·`data/schedules` 디렉터리가 재생성되지 않아 SQLite로 조용히 되돌아가지 않았음도 확인했다. 세 스케줄 모두 새 schedule storage에서 자동으로 `RUNNING`으로 복귀했다.
- **작업 중 이 세션이 만들지 않은 Dagster 중복 프로세스 8개(트리 2벌, 한쪽은 문서화되지 않은 `anaconda3\python.exe`로 기동)를 발견해 사용자 확인 후 정리했다.** 둘 다 오늘 같은 초에 시작돼 있었다 — 다른 세션이 남긴 것으로 보인다. `dagster_project\.venv`가 아닌 인터프리터로 뜬 적이 있었다는 뜻이므로, 앞으로 수동으로 `dagster dev`를 띄울 때는 반드시 `run-dagster.bat`을 거친다.
- `manage.py check`, `makemigrations --check --dry-run`, finder 테스트 32개 통과. **`manage.py test`는 실행하지 못했다** — `property_report` 역할에 `CREATEDB`가 없고 부여할 superuser 비밀번호를 에이전트가 모른다(기존에 알려진 제약, `Known Issues` 참고).

### 아직 검증하지 못한 것 (다음에 확인할 목록)

- **무인 상태로 며칠 돌려본 적이 없다.** 오늘 한 것은 수동 실행과 짧은 smoke test뿐이다. Windows gRPC 이슈 리포트들이 언급한 크래시가 장시간 실행에서는 나타날 수도 있다 — 실제 스케줄을 붙이고 최소 하루 이상 지켜봐야 한다.
- **스케줄러 데몬이 실제로 정시에 잡을 틱하는지는 안 봤다** — 통합 잡과 스케줄 정의 로드는 확인했지만 정각까지 기다린 검증은 하지 않았다.
- 스캔·리포트 asset의 실제 실행은 위에서 적었듯 종단 실행하지 않았다 — 특히 Dagster 서브프로세스에서도 Edge CDP·데스크톱 세션에 정상 접근하는지는 실제 스캔으로 한 번 더 확인해야 한다.
- **컴퓨트 로그(옵별 stdout/stderr)가 Dagster UI 안에서는 여전히 기본적으로 꺼져 있다** — 시작 로그에 `PYTHONLEGACYWINDOWSSTDIO`를 설정해야 잡힌다는 경고가 떴다. 필요해지면 `run-dagster.ps1`에 그 환경변수를 추가한다. **UI 밖에서는 2026-09-04부터 `.logs/dagster_project/<날짜>.log`에 전체 콘솔이 남으므로 실무 진단 목적은 이걸로 대신할 수 있다.**
- **부팅 시 자동 시작이 없다.** 지금은 `run-dagster.bat`을 사람이 띄워야 한다 — Windows 작업 스케줄러에 등록하는 문제는 아직 다루지 않았다(Airflow 계획의 "Airflow 자신이 죽으면 아무도 깨우지 않는다" 위험과 동일하게 적용된다).

## Planned Work: Airflow로 스케줄 이관 (2026-09-04 설계, Django·helper 코드 작성 완료, Airflow 자체는 미착수 — **현재 보류, 아래 Dagster 절 참고**)

**상태: 설계 문서 아래 "새로 필요한 코드" 표에 있던 작은 코드 전부와 Django 조회 화면, DAG 3개까지 전부 작성했다. Airflow 설치 자체와 WSL interop 검증은 아직 하지 않았다** — 지금 이 PC에 WSL이 없다(아래 "막힌 지점" 참고). **DAG 코드는 실제 Airflow에 한 번도 물려 보지 않은 상태다** — WSL을 못 쓰는 동안 미리 짜 둔 것이고, 여기 적힌 것 자체가 "다음에 검증할 목록"이다.

### 이번에 실제로 끝난 것 (2026-09-04)

- `report/airflow_client.py` + `report/templates/report/airflow.html` + `report/views.py`의 `airflow()` 뷰 + `report_site/urls.py`의 선택 경로 라우팅. `@staff_member_required`로 admin 로그인을 추가로 요구한다. Airflow가 꺼져 있거나 설정이 없으면 사유를 적은 화면을 돌려준다(테스트로 확인).
- `report_site/settings.py`에 `AIRFLOW_API_URL`/`AIRFLOW_USERNAME`/`AIRFLOW_PASSWORD`/`AIRFLOW_API_TOKEN`/`AIRFLOW_TIMEOUT_SECONDS` 추가, 전부 선택값. `.env.example`에 문서화.
- `properties/delivery.py`에 `DeliveryService.send_alert(text)` 추가 — `⚠️ ` 접두사를 붙이고 200자로 자른 뒤 기존 `_send_text` 경로로 보낸다. 새 관리 명령 `send_alert`(`properties/management/commands/send_alert.py`)가 이것을 감싼다.
- 새 관리 명령 `scan_status`(`properties/management/commands/scan_status.py`) — `--since HH:MM` 이후 성공한 `Scan`이 있으면 종료 코드 0, 없으면 1(과 `CommandError`). Airflow가 아니라 **DB의 `Scan` 테이블을 진실의 원천으로 삼는다**는 설계 결정을 그대로 구현했다.
- `report-site/ensure-site.ps1` 신설. `run-site.ps1`은 waitress로 끝나 블로킹되므로 그대로 스케줄러 태스크로 못 쓴다 — 이 스크립트는 `check-api`로 먼저 확인하고, 죽어 있을 때만 `run-site.bat`을 `Start-Process`로 분리 실행한 뒤 최대 60초 폴링한다. **서버가 이미 떠 있는 상태에서 실제로 실행해 정상 종료(exit 0)를 확인했다** — 서버가 죽은 상태에서의 기동 분기는 아직 실행해 보지 않았다.
- 새 테스트 19개(`report/tests/test_airflow_client.py`, `report/tests/test_airflow_view.py`, `properties/tests/test_scan_status_command.py`, `properties/tests/test_delivery.py`에 추가한 `send_alert` 테스트 2개) 전부 통과. 전체 Django 테스트 112개 중 111개 통과 — 나머지 1개(`test_urgent_section_respects_region_filter`)는 이 작업 이전부터 있던 무관한 실패임을 stash로 재확인했다. `manage.py check`, `makemigrations --check --dry-run` 통과.
- Airflow REST API의 정확한 필드명은 **아직 실제 응답으로 확인하지 못했다.** `airflow_client.py`는 2.x/3.x 필드명 차이를 방어적으로 읽지만(`_text()`가 여러 후보 키를 시도), Airflow를 실제로 세운 뒤 `/api/v2/dags`·`/api/v2/dags/~/dagRuns` 응답을 한 번 찍어보고 필드명이 맞는지 재확인해야 한다.
- `ensure-site.ps1`을 고쳤다 — 원래 서버가 죽어 있을 때 `run-site.bat`을 띄웠는데, **모든 `.bat` 래퍼는 `pause >nul`로 끝난다.** 사람이 더블클릭할 땐 결과를 읽으라고 있는 배려지만, 무인 실행 중 실패 경로를 타면 아무도 키를 누르지 않는 창이 숨겨진 채(`-WindowStyle Hidden`) 영원히 떠 있게 된다. `run-site.bat` 대신 `run-site.ps1`을 `powershell.exe -File`로 직접 띄우도록 고쳐 이 함정을 없앴다. **DAG를 쓰다가 발견한 버그라 여기 같이 적는다 — `run-scan.bat`/`send-report.bat`도 같은 구조라 DAG는 처음부터 `.ps1`을 직접 부르도록 짰다(아래 `_common.py`의 `run_ps1` 설명 참고).**
- **DAG 3개를 `airflow/dags/`에 작성했다** (요청 4가지와의 대응은 위 "DAG 설계" 절 참고):
  - `airflow/dags/_common.py` — 공용 헬퍼. `run_ps1()`은 `.ps1`을 `-File`로 직접 실행(위 버그 설명대로 `.bat`을 절대 부르지 않는다), `run_manage()`는 `manage.py` 명령을 `-Command`로 실행하되 **`; exit $LASTEXITCODE`를 반드시 붙인다** — PowerShell이 `-Command`로 부른 네이티브 명령의 종료 코드를 자기 프로세스 종료 코드로 자동 전달하지 않기 때문이다(`-File`은 스크립트 안의 `throw`/`exit`가 그대로 전달되므로 다르다). 둘 다 WSL의 `/mnt/c/...` 경로를 `wslpath -w`로 `C:\...`로 바꿔서 넘긴다 — interop이 인자 안의 경로를 자동 변환해 주지 않기 때문이다. `alert_on_failure()`가 `on_failure_callback`으로 모든 태스크에 공통으로 걸리며 실패를 요약해 `send_alert`를 부른다.
  - `airflow/dags/site_watchdog.py` — `0 * * * *`, `ensure-site.ps1` 한 태스크.
  - `airflow/dags/scan.py` — `0 7,12,17 * * *`, `ensure_site` → `run_scan`(`run-scan.ps1`, 20분 타임아웃 — 네이버 로그인 대기가 여기서 매달릴 수 있다).
  - `airflow/dags/morning_digest.py` — `0 8 * * *`, `ensure_fresh_scan`(`scan_status --since=07:00`가 실패하면 `||`로 `run-scan.ps1` 재실행) → `send_digest`(`send-report.ps1`).
  - **Airflow 3.x Task SDK 기준으로 작성했다** — `from airflow.sdk import DAG, Variable` + `from airflow.providers.standard.operators.bash import BashOperator` (Airflow 2.x의 `from airflow import DAG`/`from airflow.operators.bash import BashOperator`가 아니다). `Variable.get(key, default=...)`도 SDK 쪽 인자명(`default_var`이 아니라 `default`)을 썼다. **전부 문서 조사로 짠 것이라 실제 Airflow 인스턴스로 한 번도 검증하지 못했다** — `py_compile`로 문법 오류만 확인했다(4개 파일 전부 통과). 특히 `on_failure_callback`의 `context["task_instance"]`/`context["exception"]` 키가 Airflow 3.x에서 그대로 유효한지, `Variable.get`의 실제 동작이 문서와 같은지는 **Airflow를 세운 뒤 DAG를 한 번 수동 트리거해서 반드시 재확인해야 한다.**

### 막힌 지점 — VT-x가 펌웨어에서 꺼져 있고 지금 물리 접근이 안 된다 (2026-09-04)

**이 계획은 현재 보류다.** `systeminfo`로 실측한 결과 `Virtualization Enabled In Firmware: No`다. CPU 자체는 지원한다(`VM Monitor Mode Extensions: Yes`).

- 보드는 **ASUSTeK H310M-C/HDMI R2.0**(자가조립용 컨슈머 보드, BIOS 벤더 American Megatrends). Dell/HP/Lenovo 같은 기업용 PC와 달리 **Windows 안에서 BIOS 설정을 바꿀 수 있는 공식 벤더 도구가 없다.** `bcdedit`은 하이퍼바이저 실행 여부만 다룰 뿐 VT-x 자체를 켜지 못한다. **소프트웨어·명령으로는 켤 방법이 없다는 결론이다** — BIOS/UEFI 화면(POST 단계, OS 네트워크 스택이 뜨기 전)에 물리적으로 들어가야 한다. RDP 등 일반 원격 프로그램은 이 화면에 닿지 못하고, 이 PC에는 iDRAC·iLO·vPro 같은 원격관리(KVM-over-IP)도 없다.
- 사용자가 지금 물리 접근이 안 되는 상태라 **"물리 접근 가능할 때까지 보류"를 선택했다.** WSL1(가상화 불필요, syscall 변환 방식) 대체안과 Windows 작업 스케줄러로 완전히 대체하는 안도 검토했지만 채택하지 않았다 — 후자를 나중에 다시 고려하려면 이유를 남긴다: WSL1은 `/mnt` 파일 I/O가 느리고 systemd가 없어 Airflow와 궁합이 나쁘고, 작업 스케줄러 대체는 Airflow UI·DAG 의존성 그래프 없이 완전히 새 방식이라 이 설계 문서 대부분이 무의미해진다.
- **재개 조건: 물리 접근이 가능해지면** 아래 1번(가상화 확인)에서 이미 "사용 안 함"으로 확인됐으니 곧장 BIOS에서 Intel VT-x를 켜고 2번부터 이어간다.

### 다음에 할 일 (BIOS에서 VT-x를 켠 뒤부터)

아래 "단계" 절의 1~3번이 남아 있다: WSL2 설치, Airflow 3.x 설치(WSL 안 자체 venv), **interop으로 `powershell.exe`가 Windows 세션에서 실제로 뜨는지 검증**(1순위 — 여기서 막히면 나머지가 무의미하다고 설계 시점에 이미 적어 뒀다). **DAG 3개는 이미 `airflow/dags/`에 작성돼 있다** — Airflow가 서면 그 디렉터리를 `AIRFLOW_HOME/dags`에 심볼릭 링크하고(`ln -s /mnt/c/.../airflow/dags ~/airflow/dags`), DAG를 하나씩 수동 트리거해 위 "이번에 실제로 끝난 것" 절에 적힌 미검증 항목들(Task SDK 임포트 경로, `Variable.get` 동작, 콜백 컨텍스트 키, `run_ps1`/`run_manage`의 경로 변환·종료 코드 전달)을 확인하는 게 다음 작업이다.

**WSL2 설치는 관리자 권한과 재부팅이 필요해 에이전트가 대신 할 수 없다 — 사용자가 직접 한다.** 이 PC는 Windows 10 Pro 22H2(빌드 19045, 19041 이상)라 단일 명령 설치가 된다. 절차(2026-09-04에 안내함):

1. **가상화 확인.** 작업 관리자(Ctrl+Shift+Esc) → 성능 탭 → CPU → "가상화"가 "사용"인지 확인. 원격 세션이라 작업 관리자가 잘 안 보이면 명령으로도 된다: `systeminfo | Select-String "Hyper-V|Virtualization"` (PowerShell). "Virtualization Enabled In Firmware: No"면 재부팅해 BIOS/UEFI(보통 F2/F10/Del)에서 Intel VT-x 또는 AMD-V(SVM)를 켠다. **이 PC는 이미 No로 확인됐다 — 위 "막힌 지점" 참고.**
2. PowerShell을 관리자 권한으로 실행(시작 메뉴 검색 → 우클릭 → "관리자 권한으로 실행").
3. `wsl --install` 한 줄 실행 — WSL 기능·가상 머신 플랫폼·최신 리눅스 커널·기본 배포판(Ubuntu)을 한 번에 설치한다. C 드라이브 여유 공간 1GB 이상 필요.
4. 재부팅.
5. 재부팅 후 Ubuntu가 자동으로 열리며 유닉스 사용자명·비밀번호를 물어본다(Windows 계정과 별개). 아무 값이나 정하면 된다.
6. 확인: 관리자 PowerShell에서 `wsl -l -v` → `Ubuntu`가 `VERSION 2`로 나오면 정상.
7. **interop 검증(1순위).** Ubuntu 터미널에서:
   ```bash
   powershell.exe -Command "Get-Date"
   ```
   Windows 쪽 날짜가 출력되면 interop이 된다. 이어서 실제로 쓸 스크립트도 확인한다:
   ```bash
   powershell.exe -File "/mnt/c/Users/userpc/Documents/Codex/2026-09-01/d/outputs/report-site/ensure-site.ps1"
   ```
   리포트 서버가 켜져 있는 상태라면 "리포트 서버가 이미 실행 중입니다"가 뜨고 조용히 끝나야 성공이다.

이 7단계가 끝나면(=WSL 설치 완료 + interop 검증 통과) 이어서 WSL 안에 Airflow 3.x 설치로 넘어간다.

### 사용자 요청 (원문 요지)

지금은 수집·서버 운용·카카오 전송이 각각 따로 도는 프로그램이다. 이것을 Airflow로 묶는다.

1. 매 1시간마다 리포트 서버가 살아 있는지 확인하고, 죽어 있으면 띄운다.
2. 아침 7시·낮 12시·오후 5시에 수집을 돌린다. 급매가 있으면 카카오톡을 보낸다.
3. 아침 8시에 리포트를 보낸다. 7시 수집이 끝나지 않았으면 그것을 다시 시도한 뒤에 보낸다.
4. 에러가 나면 내용을 요약해 카카오톡으로 보낸다.

### 먼저 확인한 환경 사실 (다시 조사할 필요 없음)

- **이 PC에 WSL도 Docker도 설치돼 있지 않다.** `wsl -l -v`는 사용법만 출력하고 `docker`는 명령 자체가 없다(2026-09-04 실측).
- **Airflow는 Windows에서 네이티브로 돌지 않는다.** POSIX 전용이며 공식 문서가 Windows에서는 WSL2 또는 리눅스 컨테이너를 쓰라고 안내한다. 따라서 **WSL2 설치가 이 계획의 전제 조건**이다(관리자 권한과 재부팅이 필요하다).
- Airflow 3.2부터 Python 3.10~3.14를 지원한다. 저장소의 공유 venv는 3.14지만 그것은 Windows 쪽 것이고, Airflow는 WSL 안에 자기 venv를 따로 갖는다. **두 파이썬을 섞지 않는다.**
- 현재 자동 스케줄은 **하나도 없다.** 8단계에서 `scheduled-run`을 지웠고 Windows 작업 스케줄러에도 등록된 항목이 없음을 확인했다. 지금은 사람이 `.bat`을 더블클릭한다.
- `/api/health/`는 `@bearer_required`다. 무인증 헬스 경로는 없다.

### 핵심 설계 결정: Airflow는 스케줄만 잡고, 일은 전부 지금처럼 Windows에서 한다

수집은 Windows의 Edge를 CDP로 붙잡고 네이버 로그인 세션을 쓴다. PostgreSQL·Django·waitress도 전부 Windows에 있다. **이것을 리눅스로 옮기거나 다시 구현하지 않는다.** Airflow는 WSL2 안에서 스케줄러·오케스트레이터 역할만 하고, 각 태스크는 WSL interop으로 `powershell.exe`를 불러 **기존 `.ps1` 스크립트를 그대로 실행한다.** 그러면 실제 작업 프로세스는 오늘과 똑같이 Windows 사용자 세션에서 돈다.

방향에 따라 난이도가 다르다는 점이 이 설계의 근거다.

| 방향 | 방법 | 난이도 |
|---|---|---|
| Airflow(WSL) → Windows 작업 | interop으로 `powershell.exe` 실행 | 쉬움 |
| Django(Windows) → Airflow API | `http://127.0.0.1:8080` (WSL2가 자동 포워딩) | 쉬움 |
| WSL → Windows HTTP·DB 직접 접속 | 호스트 IP + 방화벽 필요 | **피한다** |

Windows 10에는 WSL2 미러 네트워킹이 없다(Windows 11 22H2+ 기능). 그래서 **헬스체크조차 HTTP로 WSL에서 건너가지 않고**, interop으로 Windows 쪽에서 실행한다. 네트워크 경계를 넘는 것은 Django가 Airflow를 읽는 한 방향뿐이다.

### DAG 설계 — 요청 4가지 매핑

**1) `site_watchdog` — `0 * * * *` (매시 정각, Asia/Seoul)**

태스크 하나. 새 스크립트 `report-site/ensure-site.ps1`을 interop으로 부른다. 그 스크립트가 하는 일:

- `real_estate_finder check-api`로 서버 확인 — 토큰 로딩과 사람이 읽을 수 있는 실패 메시지가 이미 그 명령에 있으므로 재사용한다.
- 죽어 있으면 `Start-Process`로 `run-site.bat`을 **분리 실행**한다. `run-site.ps1`은 마지막 줄이 waitress라 블로킹이므로, 그냥 부르면 Airflow 태스크가 영원히 안 끝난다.
- 30초쯤 헬스를 폴링하고, 그래도 안 뜨면 0이 아닌 코드로 종료한다(→ 4번 실패 알림).

**2) `scan` — `0 7,12,17 * * *`**

`ensure_site` → `run_scan` 두 태스크. `run_scan`은 기존 `run-scan.bat`을 그대로 부른다. `execution_timeout`은 20분쯤, `retries=1`.

**급매 카카오 전송을 위해 Airflow가 할 일은 없다.** `scan-once`가 `POST /api/scans/`로 넘기면 Django가 급매·신규를 판정해 그 자리에서 보낸다. 요청 2번의 "급매 있으면 카톡"은 **이미 구현돼 있는 동작**이고, Airflow는 스캔을 제때 돌리기만 하면 된다.

**3) `morning_digest` — `0 8 * * *`**

- `ensure_fresh_scan`: 오늘 07:00 이후 성공한 스캔이 있는지 확인하고, 없으면 그 자리에서 `run-scan.bat`을 돌린다.
- `send_digest`: 기존 `send-report.bat`(= `manage.py send_digest`)을 부른다.

**판단 근거를 Airflow 메타데이터가 아니라 DB에서 본다.** `ExternalTaskSensor`로 7시 DAG런 상태를 보는 방법도 있지만, 정작 중요한 것은 "DAG가 돌았는가"가 아니라 **"보낼 수집 결과가 있는가"**다. `Scan` 모델에 `started_at`·`success`·`successful_conditions`가 이미 있으므로 그것이 진실의 원천이다. 7시 런이 성공 표시여도 조건이 전부 실패했을 수 있고, 반대로 사람이 손으로 돌린 수집이 있으면 다시 돌릴 필요가 없다.

**4) 실패 알림 — `on_failure_callback`**

세 DAG의 `default_args`에 공통 콜백을 건다. 콜백은 DAG id·태스크 id·시도 횟수·로그 꼬리를 200자 예산에 맞게 요약해 interop으로 `manage.py send_alert "<요약>"`을 부른다. **카카오 인증·전송 경로를 WSL에서 다시 만들지 않기 위해** Django 명령을 통한다.

### 새로 필요한 코드 (작다)

| 무엇 | 어디 | 왜 |
|---|---|---|
| `ensure-site.ps1` | `report-site/` | 분리 실행 + 헬스 폴링. `run-site.ps1`은 블로킹이라 그대로 못 쓴다 |
| `send_alert` 명령 + `DeliveryService.send_alert(text)` | `report-site/properties/` | 지금 `DeliveryService`는 `CardItem` 목록만 받는다. 임의 텍스트 1통을 보낼 공개 경로가 없어 `_send_text`가 private로 막혀 있다 |
| `scan_status` 명령 | `report-site/properties/` | "오늘 N시 이후 성공 스캔이 있는가"를 종료 코드로 답한다. 3번 DAG가 쓴다 |
| DAG 3개 | `airflow/dags/` (WSL에서 심볼릭 링크) | |

기존 `run-scan.bat`·`send-report.bat`·`check-api`는 **고치지 않고 그대로 재사용한다.**

### 위험 (실제로 이 계획을 깨뜨릴 것들)

- **네이버 로그인 만료가 최대 약점이다.** `run-scan.ps1`의 3단계 `browser-login`은 사람이 로그인할 때까지 기다린다. 무인 실행 중 세션이 끊기면 그 태스크는 타임아웃까지 매달린다. 자동화할 수 없는 지점이므로 **타임아웃 → 실패 → 카톡 알림 → 사람이 로그인**이 유일한 경로다. 이것을 "가끔 있는 일"로 받아들일 수 있어야 이 계획이 성립한다.
- **Windows 세션이 잠기거나 로그아웃되면 Edge 자동화가 깨진다.** 이 PC는 켜져서 로그인된 상태로 있어야 한다.
- **Airflow 자신이 죽으면 아무도 깨우지 않는다.** 감시자의 감시자가 없다. WSL과 Airflow를 부팅 시 자동 기동하도록 Windows 작업 스케줄러에 등록하는 것으로 최소한만 막는다.
- WSL2 설치는 관리자 권한과 재부팅을 요구한다.

### 단계

1. WSL2 + Ubuntu 설치, 부팅 시 자동 시작 설정.
2. WSL 안에 Airflow 3.x 설치(자체 venv, constraints 파일 사용), simple auth manager, 8080 포트.
3. interop 확인 — WSL에서 `powershell.exe -File "C:\...\run-site.ps1"`이 Windows 세션에서 실제로 뜨는지 먼저 확인한다. **여기서 막히면 나머지가 전부 무의미하므로 1순위로 검증한다.**
4. Django 쪽 작은 명령 2개(`send_alert`, `scan_status`)와 `ensure-site.ps1` 작성 + 테스트.
5. DAG 3개 작성, 각각 수동 트리거로 1회씩 확인.
6. 스케줄 활성화. 첫 하루는 결과를 사람이 확인한다.
7. `RUNBOOK.md`에 "Airflow가 돌리는 것 / 사람이 여전히 해야 하는 것"을 적는다.

### Django에서 Airflow 보기 (작업 중)

운영 화면은 현재 `/property/airflow/`이며 토큰을 켜면 `/<TOKEN>/property/airflow/`로 이동한다. **`@staff_member_required`를 걸어 admin 로그인을 추가로 요구한다** — 스케줄 상태는 이 PC가 언제 비어 있는지와 무엇이 실패했는지를 알려주므로 일반 리포트 방문자에게까지 보일 내용이 아니다.

- `report/airflow_client.py`: stdlib `urllib`로 Airflow REST API v2를 읽는다(`POST /auth/token`으로 JWT → `GET /api/v2/dags`, `GET /api/v2/dags/~/dagRuns`). `real-estate-finder/api_client.py`와 같은 이유로 HTTP 의존성을 새로 넣지 않는다. **읽기 전용이다 — DAG를 트리거·중지·삭제하는 경로를 두지 않는다.**
- Airflow가 꺼져 있거나 설정이 없으면 500이 아니라 사유를 적은 화면을 돌려준다. 스케줄러가 죽었을 때 그 사실을 보여주는 것이 이 화면의 목적이므로 스택 트레이스로 죽으면 안 된다.
- 필드 이름은 방어적으로 읽는다. Airflow 2.x와 3.x가 DAG 런 필드명을 여러 개 바꿨고 아직 붙일 인스턴스가 없어 실제 응답을 확인하지 못했다. **Airflow를 세운 뒤 실제 payload로 반드시 재확인한다.**
- 설정은 전부 선택값이다(`AIRFLOW_API_URL`, `AIRFLOW_USERNAME`/`AIRFLOW_PASSWORD` 또는 `AIRFLOW_API_TOKEN`, `AIRFLOW_TIMEOUT_SECONDS`). 비어 있으면 화면이 "설정되지 않았다"고 말한다.
- **현재 상태:** `report/airflow_client.py`와 뷰·URL·설정 배선까지 작성했고, **템플릿(`report/templates/report/airflow.html`)과 테스트가 아직 없다.** 그 상태로는 화면이 열리지 않는다.

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

`.docs/RUNBOOK.md`에 "관심단지를 새로 추가했을 때" 절(= 이 문서의 1~2단계)을 넣고, `.agent/PROJECT_STATE.md`의 단지 수·지역 수를 갱신하고, 이 `Active Work` 절을 완료 기록으로 정리한다. `AGENTS.md`의 프로젝트 개요 한 줄(과천 중심 표현)도 확인한다.

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

- `.docs/ARCHITECTURE.md`를 역할 경계 중심으로 다시 썼다(350 → 273줄). 수집기 절과 애플리케이션 절을 나누고, "이 작업에는 어떤 파일을 읽는가" 표를 `properties/`·`api/`·`report/` 기준으로 다시 매핑했다. 에이전트가 걸려 넘어질 결과 세 가지를 명시했다 — 스캔이 서버를 요구한다, 코드 변경 후 서버 재시작이 필요하다, 테스트에는 DB 생성 권한이 필요하다.
- `.docs/RUNBOOK.md`: 진입점이 셋이 되었고 리포트 서버를 먼저 켠다. PostgreSQL 준비와 `import_searches`를 최초 설정에 넣었고, digest·카드 미리보기·리포트 확인을 Django 관리 명령으로 바꿨다. "서버가 꺼져 있어도 스캔은 된다"는 설명을 반대로 고쳤다.
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
5. `should_alert` = **이번 스캔에서 처음 발견된 급매**. 기존 매물이 나중에 급매가 되거나 더 내려가도 재알림하지 않는다. `notify_new` 조건은 일반 신규도 별도 알림 대상
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

- 주소는 현재 `.../property/admin/`이며, 나중에 `REPORT_PATH_TOKEN`을 채우면 `.../<TOKEN>/property/admin/`으로 이동한다. `run-site` 창이 `Local admin:` 줄로 현재 주소를 출력한다.
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

- **`report.tests.test_views.ReportViewTests.test_urgent_section_respects_region_filter`가 실패한다(2026-09-05 관측, 주식 작업 이전부터).** 지역 필터를 걸면 `urgent` 목록이 비어 나온다. 해당 커밋(`0cb96bc`) 상태로 되돌려도 같은 실패라 이번 주식 작업과는 무관하다. 급매 섹션이 지역 필터를 안 따르는 실제 버그인지 테스트의 기대값이 낡은 것인지는 아직 확인하지 않았다.
- **주식 도메인은 아직 수집기가 없다.** `/stock/allocation/`과 `/stock/performance/`는 배선이 끝났지만 `POST /stock/api/import-runs/`로 들어온 자료가 없으면 "수집 결과 없음" 화면만 보여준다. `STOCK_API_TOKEN`도 비어 있어 그 API는 지금 503을 돌려준다.
- **네이티브 `/common/dagster/console/`은 현재 Django 인증을 거치지 않는다.** `/common/dagster/` 요약은 staff 로그인이 필요하지만 console은 Funnel이 3000번 포트로 직접 프록시하며, 현재 `REPORT_PATH_TOKEN`도 비어 있다. URL을 아는 외부 사용자는 실제 스캔·카카오 발송이 가능한 job을 실행할 수 있다. 필요하면 console Funnel mount를 제거해 Tailscale 사설망 Serve로만 열거나 인증 reverse proxy 뒤로 옮겨야 한다.
- **`report-site/run-site.bat`이 실행 중이 아니면 공개 리포트 주소가 죽는다.** PC 종료·절전도 마찬가지다. 자동 시작을 등록하지 않기로 했으므로(Key Decisions 참고) 리포트를 외부에서 열어야 할 때 사용자가 직접 켜야 한다. 다행히 조용히 깨지지는 않는다 — 서버가 없으면 `is_live()`가 실패해 카카오 메시지에서 두 버튼이 빠지고 텍스트만 나간다.
- **이제 스캔 자체가 리포트 서버 실행을 요구한다.** Python `run_scan_workflow()`의 첫 단계 서버 확인이 실패하면 브라우저를 열지 않고 멈춘다. 예전처럼 "서버가 꺼져 있어도 스캔은 된다"가 더 이상 성립하지 않는다. 자동 시작(작업 스케줄러 로그온 트리거) 등록 여부를 다시 판단할 시점이다.
- **Django admin 로그인 화면이 공개 `/property/admin/`에 노출된다.** 토큰을 다시 켜기 전에는 경로 은닉도 없으므로 특히 강한 비밀번호가 필요하다.
- 예전 Codex Sites 주소(`https://my-property-report-20260902.ssong7988.chatgpt.site`)는 더 이상 갱신되지 않는다. 루트 `.env`의 `KAKAO_REPORT_URL`을 지우면 이 오래된 주소로 폴백하므로 비우지 않는다.
- 휴대전화에서 `127.0.0.1`/`localhost`는 서버 PC를 가리키지 않으며 카카오 웹 도메인으로도 부적합하다(Tailscale Funnel 주소를 써야 하는 이유).
- 현재 `REPORT_PATH_TOKEN`은 비어 있어 `/property/report/`, `/property/statistics/`, `/common/dagster/console/`이 namespace만으로 공개된다. 나중에 값을 채우면 우발적 노출을 줄일 수 있지만, 주소가 유출되면 인증 없이 누구나 볼 수 있다는 한계는 같다.
- **코드를 바꿨으면 리포트 서버를 재시작해야 한다.** 실행 중인 프로세스는 옛 코드를 들고 있다. 이 구조에서는 재시작을 잊어도 조용히 넘어가지 않고 `check-api`가 404로 실패해 드러난다.
- **과천·판교 조건은 신규 급매일 때만 카카오톡이 온다.** 기존 매물이 나중에 급매 기준을 통과하거나 더 내려가도 보내지 않는다. `notify_new`가 켜진 광교 4개는 급매 여부와 별개로 일반 신규도 보낸다. 사유는 항상 콘솔과 `Scan.notification`에 남는다. 지금 전체를 받고 싶으면 `send-report.bat`이다.
- **Django 테스트에는 DB 생성 권한이 필요하다.** `property_report` 역할에 `CREATEDB`가 없어 `manage.py test`가 테스트 DB를 만들지 못한다. 테스트 동안만 부여했다가 되돌린다(`ALTER ROLE property_report CREATEDB;` → `NOCREATEDB;`).
- **검색 조건을 admin에서 바꾸면 과거 관측은 옛 기준으로 판정된 채 남는다.** 통계가 새 조건과 어긋나므로 `manage.py reclassify_observations`로 다시 판정한다. 다시 판정은 *현재* 조건을 쓰므로 당시 조건과 다를 수 있다 — 의도된 절충이다.
- 공개 리포트에는 매물 정보가 노출되므로 민감한 개인 데이터나 인증 정보를 포함하지 않아야 한다.
- **관심단지 하나가 실패하면 스캔 전체가 실패로 끝난다(2026-09-04 관측).** `collect_favorites_snapshot()`이 단지 목록을 순회하다 예외가 나면 그 자리에서 전체가 중단되고, 활성 조건 전부가 실패로 보고된다. 이제 단지별 진행 로그(`관심단지 N/총 'OO' 확인 중...`)와 필터 에러에 단지명이 붙어 어디서 막혔는지는 바로 보이지만, 부분 실패를 허용하도록 격리하는 작업은 아직 하지 않았다.
- **Edge 창을 최소화하거나 백그라운드에 두면 스캔이 "네이버 로그인 상태가 만료되었습니다"로 오탐 실패할 수 있다(2026-09-04).** Chromium이 비활성 탭의 렌더링을 늦춰, `page.goto()` 직후 로그인 헤더가 아직 안 그려진 상태를 로그아웃으로 오인했다. `_raise_if_blocked()`에 짧은 재시도와 `page.bring_to_front()`를 추가해 완화했지만, OS 창이 완전히 최소화된 경우까지는 보장하지 못한다 — 스캔 중에는 Edge 창을 보이는 상태로 두는 것이 가장 확실하다(`.docs/RUNBOOK.md` 참고).
- **PostgreSQL DB 기본 타임존이 `Asia/Seoul`이라 Dagster 실행 시각이 9시간 미래로 기록됐다(2026-09-04, 원인 규명·수정 완료).** `pg_settings`의 `TimeZone.reset_val`이 `Asia/Seoul`이다. Dagster가 **파이썬에서 UTC로 직접 채우는** 값(`event_logs.timestamp`, `runs.start_time/end_time` — float epoch)은 멀쩡했지만, **PostgreSQL이 `CURRENT_TIMESTAMP` 기본값으로 채우는** 컬럼(`runs.create_timestamp/update_timestamp`, `job_ticks.*`)에는 KST 벽시계가 들어갔고 Dagster는 그걸 UTC로 읽어 +9시간이 됐다. 결과적으로 **Dagster UI의 Overview 타임라인이 텅 비고**(모든 실행이 시간창 바깥 미래로 밀림) `Runs` 목록만 정상으로 보여 원인을 찾기 어려웠다. SQLite는 `CURRENT_TIMESTAMP`가 항상 UTC라 PostgreSQL 이관(`fcf3105`) 때 딸려 들어온 문제다. `run-dagster.ps1`이 쓰는 연결 옵션에 `-c timezone=UTC`를 넣어 고쳤고, 기존 `runs` 11행·`job_ticks` 5행은 `- interval '9 hours'`로 한 번 보정했다. **Django는 세션마다 UTC를 지정하므로 영향이 없었다** — 더 넓게 막고 싶으면 `ALTER DATABASE property_report SET timezone TO 'UTC';`도 가능하다.
- **`.ps1`에서 네이티브 CLI를 부를 때 `$ErrorActionPreference='Stop'`과 stderr가 충돌한다(2026-09-04, 실증 확인).** Windows PowerShell 5.1은 스트림이 리다이렉트된(`*> $null` 등) 네이티브 명령이 stderr에 한 줄이라도 쓰면 종료 코드가 0이어도 terminating error로 바꾼다. `check-api`는 서버에 닿지 못할 때 `실행 실패: ...`를 stderr로 내므로, `Test-Site`가 "아직 안 뜸"을 `$false`로 돌려주는 대신 스크립트째 exit 1로 죽었다 — `restart_report_site_job` 실패와 `ensure-site.ps1`이 정작 서버가 죽었을 때 복구하지 못하던 원인이 모두 이것이다. 두 스크립트의 `Test-Site`는 호출 구간만 `$ErrorActionPreference='Continue'`로 낮추고 `catch`에서 `$false`를 돌려주도록 고쳤다. **이 저장소는 `.ps1`이 파이썬 CLI를 부르는 패턴을 계속 쓰므로 새 스크립트에서도 같은 함정을 조심한다.**
- **`.logs/`는 건강한 상태에서 계속 도는 서버의 실시간 로그가 아니다(2026-09-04, 검증됨).** `Start-Transcript`는 네이티브 프로세스 출력을 그 프로세스가 끝날 때 한꺼번에 기록한다 — 크래시·정상 종료는 잡히지만, waitress나 Dagster가 몇 주째 멀쩡히 떠 있는 동안의 요청 로그를 `Get-Content -Wait`로 실시간 추적할 수는 없다. 필요해지면 `Start-Process -RedirectStandardOutput`으로 구조를 바꿔야 하는데, 스크립트가 블로킹 호출을 직접 하는 대신 자식 프로세스를 추적해야 해서 이번 범위에서는 하지 않았다.

## Key Decisions

### 이번 전환에서 정한 것 (2026-09-03)

- **수집기는 판정하지 않는다. 수집한 매물을 전량 API로 넘긴다.** 이유: 조사와 표현·판정이 한 프로세스에 섞여 있어 변경 범위가 항상 전체로 번졌다. 원본을 전부 DB에 넣어두면 조건을 바꿨을 때 재수집 없이 과거 데이터를 다시 판정할 수 있다.
- **검색조건은 Django 모델이 소스이고 admin에서 수정한다.** `config/searches.yaml`은 `report-site/properties/seed/searches.yaml`로 옮겨 초기 시드로만 쓴다. 이유: 조건 필터를 Django가 수행하려면 조건이 DB에 있어야 하고, YAML을 고치고 스크립트를 돌리는 것보다 화면에서 고치는 편이 낫다고 판단했다.
- **SQLite를 거치지 않고 PostgreSQL로 바로 간다.** 이유: 어차피 목표 아키텍처이고 두 번 마이그레이션할 이유가 없다.
- **카드 생성·카카오 전송까지 `report-site`가 소유한다.** 이유: 원래 불만이 "조사도 하고 그 결과도 꾸미는 것"이었다. Playwright가 이미 공유 venv에 있어 새 설치 없이 옮길 수 있다.
- **DRF를 추가하지 않는다.** 엔드포인트가 4개뿐이라 `JsonResponse` + 명시적 검증으로 충분하고, 프로젝트의 "가장 단순한 해법" 원칙에 맞는다.
- **카드 전송을 `POST /api/scans/` 요청 안에서 동기로 처리한다.** 큐를 도입하지 않는 대신 요청이 수 초~수십 초 걸린다. 단일 사용자 시스템이고 수집기는 어차피 대기 중이다.
- **API는 `Authorization: Bearer <FINDER_API_TOKEN>`으로 보호한다.** 사이트가 Tailscale Funnel로 인터넷에 열려 있어 `/api/`도 외부에서 닿는다.
- **Django admin에도 선택 토큰 규칙을 적용한다.** 현재는 `/property/admin/`, `REPORT_PATH_TOKEN`을 채우면 `/<TOKEN>/property/admin/`이다.

### Dagster 구조에 대해 정한 것 (2026-09-04)

- **Dagster는 부동산·주식이 공유하는 한 인스턴스로 운영한다.** 같은 PC에서 webserver·daemon·PostgreSQL run storage를 두 벌 운영할 실익이 작다. 도메인 충돌은 부동산의 기존 `property_report` asset group과 주식용 별도 group/job, 필요 시 code location으로 분리한다. 한 인스턴스 장애가 두 도메인 스케줄에 영향을 주는 단점은 있지만 현재 단일 PC 자체가 이미 공통 장애 지점이라, 별도 인스턴스의 운영 복잡도가 더 크다. 공통 주소는 `/common/dagster/`와 `/common/dagster/console/`이다.
- **파이프라인을 op가 아니라 asset으로 모델링한다.** `naver_listings → morning_report`를 선언하고, 각 스케줄이 어디까지 실행할지 고른다. 이유: 세 스케줄이 원하는 것은 결국 "어디까지"인데, op 방식에서는 그것을 "세 단계를 전부 실행하되 두 개는 아무것도 안 한다"로 우회 표현해야 했다. 설정 손잡이가 둘에서 하나(`run_scan_op.mode`)로 줄었고, `skip`·`enabled: false` 같은 가짜 실행이 없어졌다.
- **서버 확인은 asset이 아니라 op다.** 전환 직후 `report_site_up`이라는 asset을 하나 뒀다가 같은 날 되돌렸다. asset은 끝나고 나서 남는 것인데 "서버가 응답했다"는 아무것도 남기지 않는다 — 실제로 셋 중 유일하게 머티리얼라이즈 메타데이터가 영구히 비어 있었다. 지금은 `ensure_site_op`이 `server_check_job`의 전부이자 `naver_listings`의 첫 단계로 재사용된다(`ensure-site.ps1`이 멱등이라 안전).
- **그래서 `naver_listings`는 `@dg.graph_asset`이다.** 평범한 op은 asset의 상류가 될 수 없다 — `@dg.asset(deps=[some_op])`은 `ParameterCheckError`, `define_asset_job(selection=[asset, op])`은 `DagsterError`로 거부된다(둘 다 실측). 하지만 asset **안에서** op을 순서대로 돌리는 것은 `graph_asset`으로 가능하다. 대가는 서버 확인이 Catalog·Lineage에서 독립 노드로 안 보인다는 것이고, 대신 모든 런에 `naver_listings.ensure_site_op` step으로 남는다. "전제 조건을 그래프에 그릴 값어치가 있는가"에서 없다고 판단했다.
- **잡을 셋으로 나눈 것이 lineage를 만든 것은 아니다.** Dagster에서 잡끼리는 여전히 이어지지 않는다. 순서를 아는 것은 asset 의존성이고, 잡은 그 그래프에서 얼마만큼을 실행할지 고르는 창이다. (전환 전에는 "잡을 쪼개면 `run_status_sensor`가 필요하다"는 이유로 단일 잡을 유지했는데, asset으로 옮기면서 그 전제 자체가 사라졌다.)
- **Catalog는 탐지가 아니라 선언 기반이다.** Dagster는 PostgreSQL을 들여다보지 않는다. 상태를 Django/PostgreSQL이 소유해도 asset 선언은 성립한다 — Dagster가 직접 써야만 asset인 것이 아니다. 다만 선언만으로는 이름과 시각뿐이라, 값어치는 메타데이터를 돌려줄 때 생긴다.
- **Catalog와 Lineage는 Dagster UI의 서로 다른 화면이다.** `/assets`(목록)와 `/lineage`(그래프)로 좌측 내비게이션에 따로 있다. 같은 asset 집합의 두 표현이다.
- **그래서 `manage.py scan_status`에 `--json`을 추가했다.** Dagster가 `run-scan.ps1`을 불투명한 subprocess로 실행해 종료 코드밖에 모르므로, 수집 후 방금 기록된 `Scan` 행의 카운트를 되읽어 머티리얼라이즈 메타데이터로 붙인다. 기존 exit-code 계약(0=있음/1=없음)은 그대로 두고 stdout에 JSON 한 줄만 추가했으며, 페이로드는 순수 ASCII라 Windows 콘솔 코드페이지를 추측하지 않아도 된다. 이 조회가 실패해도 머티리얼라이즈는 성공한다 — 장식이 본 작업을 깨뜨리면 안 된다.

### 이전에 정해져 유지되는 것

- **서빙 방식을 Next.js/Codex Sites 빌드·배포에서 Django(`report-site/`) 요청 시 렌더링으로 전환했다.** 이유: 조회할 때마다 UI를 빌드·배포해야 하는 것이 불합리했고, 목표 아키텍처에도 더 가깝다.
- 외부 공개는 도메인 구입 없이 Tailscale Funnel을 쓴다. 현재 사용자의 결정으로 부동산은 `/property/`, 공통 운영은 `/common/`, 향후 주식은 `/stock/` namespace를 쓴다. 나중에 `REPORT_PATH_TOKEN` 환경변수만 채워 namespace 앞에 토큰을 붙일 수 있게 유지한다.
- **리포트 서버 자동 시작(작업 스케줄러)은 등록하지 않는다.** 상시 실행 프로세스를 늘리지 않는 대신, 서버가 꺼져 있으면 카카오 카드에서 버튼이 빠지는 것을 정상 동작으로 받아들인다. (전환 후 스캔이 서버를 요구하게 되면 이 결정을 재검토한다.)
- 표시 로직은 한 곳에만 둔다. 가격/면적 포맷이 카카오 카드와 웹 리포트 사이에서 갈라지지 않게 하기 위함이다. 전환 후 그 한 곳은 `report-site/properties/report.py`가 된다.
- `is_live()` 게이트는 유지한다. "리포트 서버가 살아있고 이번 조회를 서빙 중인가"를 확인하며, PC가 꺼져 있으면 카카오 카드에서 `전체 매물 보기` 버튼이 올바르게 빠진다.
- **은퇴한 UI는 운영 참조가 없으면 보존하지 않는다.** `property-report-site/`는 중첩 저장소가 깨끗하고 운영 소스 참조가 없음을 확인한 뒤 2026-09-04 제거했다. 과거 UI가 필요하면 Git 이력의 gitlink 커밋에서 찾는다.
- `KAKAO_REPORT_URL`(루트 `.env`)과 `REPORT_PATH_TOKEN`(`report-site/.env`)은 분리해서 관리한다. 전자는 공유 공개 URL, 후자는 Django 라우팅에만 쓰는 비밀 토큰이다.
- 고정 도메인이 바뀌면(Tailscale 호스트명 포함) 카카오 개발자 콘솔의 웹 도메인과 `KAKAO_REPORT_URL`을 함께 변경한다.
- 토큰, 비밀번호, 쿠키, 인증 코드는 Git 및 상태 문서에 기록하지 않는다.
