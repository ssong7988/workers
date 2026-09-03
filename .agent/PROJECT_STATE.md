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

## Current State

- **전환 완료. 종단 확인까지 끝났다.** 공개 리포트는 Tailscale Funnel 주소로 서빙되며, 실제 카카오톡 카드에 `전체 매물 보기` 버튼이 새 주소로 포함되는 것까지 확인했다.
- 공개 리포트 호스트: `https://desktop-477.tailf8d9d1.ts.net` (Tailscale Funnel → 로컬 `127.0.0.1:8000` 프록시). 전체 경로는 `REPORT_PATH_TOKEN`을 포함하므로 문서에 적지 않는다 — 루트 `.env`의 `KAKAO_REPORT_URL`에 있다.
- Tailscale 설치·로그인·Funnel 활성화 완료(`tailscale funnel --bg 8000`). `tailscaled`는 Windows 서비스라 재부팅 후 Funnel 설정이 자동 복구된다.
- 카카오 개발자 콘솔의 `앱 > 제품 링크 관리 > 웹 도메인`에 위 호스트를 등록 완료. (`플랫폼 키` 메뉴가 아니다 — `kakao-notifier/README.md:31` 참고.)
- `report-site/.env`의 `REPORT_PATH_TOKEN`과 루트 `.env`의 `KAKAO_REPORT_URL` 모두 실제 값으로 채워져 있다(Git 제외).
- `check-report`로 공개 주소가 `data/state.json`의 기준 시각(`2026-09-03T08:38:55+09:00`, 활성 매물 41건)과 일치함을 확인했다.
- `send-report.ps1`로 실제 카카오톡 카드 1통(매물 41건)을 전송해 `전체 매물 보기` 버튼 동작까지 사용자가 휴대폰에서 확인했다.
- 리포트 화면은 관심 단지 6개, 확인 매물 41건, 급매 1건을 정확히 렌더링한다.
- 카카오 이미지는 카카오 이미지 업로드 API를 사용한다(변경 없음).
- 마지막 확인 시 Python 단위 테스트 81개(`real-estate-finder/tests`) 전부 통과, Django 테스트 6개(`report-site/report/tests`) 전부 통과, `manage.py check` 통과.

## Active Work

- Codex Sites 빌드/배포 파이프라인을 완전히 제거하고, `report-site/`(Django)가 `data/state.json`을 즉시 서빙하는 구조로 전환했다. 설정과 종단 확인까지 완료되어 당장 진행 중인 코드 변경은 없다.
- **운영 시 유일한 수동 단계: 리포트를 외부에서 열려면 `report-site/run-site.bat`이 실행 중이어야 한다.** 자동 시작은 의도적으로 등록하지 않았다(아래 Key Decisions 참고). 서버가 꺼져 있으면 카카오 카드는 `전체 매물 보기` 버튼을 자동으로 생략한다.
- 에이전트 없는 수동 실행 절차는 `.agent/docs/RUNBOOK.md`에서 관리하며, Tailscale Funnel 설정 절차를 포함해 갱신했다.
- 향후 수집 결과와 매물 이력을 PostgreSQL에 저장하도록 데이터 계층을 전환한다. 서빙(Django)과 공개 URL 구조는 이미 목표 형태이므로, 그때 바뀌는 것은 `report-site/report/views.py`의 데이터 로딩 부분뿐이다.
- 아키텍처 또는 운영 방식이 바뀌면 이 문서를 즉시 갱신한다.

## Known Issues

- **`report-site/run-site.bat`이 실행 중이 아니면 공개 리포트 주소가 죽는다.** PC 종료·절전도 마찬가지다. 자동 시작을 등록하지 않기로 했으므로(Key Decisions 참고) 리포트를 외부에서 열어야 할 때 사용자가 직접 켜야 한다. 다행히 조용히 깨지지는 않는다 — 서버가 없으면 `is_live()`가 실패해 카카오 카드에서 버튼이 빠진다.
- 예전 Codex Sites 주소(`https://my-property-report-20260902.ssong7988.chatgpt.site`)는 더 이상 갱신되지 않는다. 루트 `.env`의 `KAKAO_REPORT_URL`을 지우면 이 오래된 주소로 폴백하므로 비우지 않는다.
- 휴대전화에서 `127.0.0.1`/`localhost`는 서버 PC를 가리키지 않으며 카카오 웹 도메인으로도 부적합하다(Tailscale Funnel 주소를 써야 하는 이유).
- 토큰 경로(`REPORT_PATH_TOKEN`)는 우발적 노출만 막는다. 주소가 유출되면 인증 없이 누구나 볼 수 있다.
- `state.json` 기반이므로 PostgreSQL 전환은 아직 남은 과제다.
- 루트와 예전 UI(`property-report-site/site-app/`)가 중첩 Git 저장소로 남아 있다. 그 디렉터리를 다시 건드릴 일이 생기면 UI 커밋 누락이나 루트 포인터만 변경되는 실수에 유의한다.
- 마지막 `npm audit` 결과는 취약점 11개(낮음 1, 보통 2, 높음 8)였다(예전 UI 저장소 기준, 더 이상 서빙 경로가 아니므로 우선순위 낮음).
- 공개 리포트에는 매물 정보가 노출되므로 민감한 개인 데이터나 인증 정보를 포함하지 않아야 한다.

## Key Decisions

- **서빙 방식을 Next.js/Codex Sites 빌드·배포에서 Django(`report-site/`) 요청 시 렌더링으로 전환했다.** 이유: 조회할 때마다 UI를 빌드·배포해야 하는 것이 비합리적이었고, `data/state.json`을 그대로 읽는 구조가 목표 아키텍처(`수집기 → 저장소 → Django → 공개 URL → 카카오톡`)에도 더 가깝다.
- 외부 공개는 도메인 구입 없이 Tailscale Funnel을 쓴다. 접근 제어는 로그인이 아니라 추측 불가능한 경로 토큰이다 — 리포트에 담긴 정보가 네이버 부동산 공개 정보 수준이라 판단했기 때문이다.
- **리포트 서버 자동 시작(작업 스케줄러)은 등록하지 않는다.** 필요할 때 `report-site/run-site.bat`을 직접 실행하는 방식을 택했다. 상시 실행 프로세스를 늘리지 않는 대신, 서버가 꺼져 있으면 카카오 카드에서 버튼이 빠지는 것을 정상 동작으로 받아들인다. 나중에 상시 공개가 필요해지면 로그온 트리거로 등록하면 된다.
- 표시 로직(`build_report_payload`, 옛 `write_report_data`)은 `real_estate_finder/report.py`에 그대로 두고 Django 뷰가 이를 가져다 쓴다. 가격/면적 포맷이 카카오 카드와 리포트 사이에서 갈라지지 않게 하기 위함이다.
- `is_live()` 게이트는 유지한다. 이제는 "빌드가 최신인가"가 아니라 "리포트 서버가 살아있고 이번 조회를 서빙 중인가"를 확인하며, PC가 꺼져 있으면 카카오 카드에서 `전체 매물 보기` 버튼이 올바르게 빠진다.
- 스캔이 알림을 보내기 전에 `state.json`을 먼저 저장하도록 순서를 바꿨다. 저장이 늦으면 `is_live()`가 항상 "아직 반영 안 됨"으로 판정해 버튼이 매번 빠지기 때문이다.
- 예전 `property-report-site/site-app/`은 삭제하지 않는다. 별도 중첩 Git 저장소라 삭제는 되돌리기 어렵고, 새 구조가 며칠 안정적으로 돈 뒤 삭제 여부를 별도로 결정한다.
- `KAKAO_REPORT_URL`(루트 `.env`)과 `REPORT_PATH_TOKEN`(`report-site/.env`)은 분리해서 관리한다. 전자는 real-estate-finder와 report-site가 공유하는 공개 URL, 후자는 Django 라우팅에만 쓰는 비밀 토큰이다.
- 고정 도메인이 바뀌면(Tailscale 호스트명 포함) 카카오 개발자 콘솔의 웹 도메인과 `KAKAO_REPORT_URL`을 함께 변경한다.
- 목표 아키텍처는 `수집기 → PostgreSQL → Django 웹 애플리케이션 → 공개 URL → 카카오톡 전달` 흐름이며, 서빙 계층 전환은 이미 끝났으므로 남은 것은 저장 계층(PostgreSQL) 전환뿐이다.
- 토큰, 비밀번호, 쿠키, 인증 코드는 Git 및 상태 문서에 기록하지 않는다.
