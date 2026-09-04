# real-estate-finder

네이버 부동산 관심단지에서 매물을 **수집**해 `report-site`로 넘기는 프로그램입니다.

여기서 하는 일은 그게 전부입니다. 어떤 매물이 조건에 맞는지, 급매인지, 신규인지, 카카오톡을 보낼지, 화면에 어떻게 보일지는 전부 `report-site`(Django + PostgreSQL)가 결정합니다. 그래서 **스캔하려면 리포트 서버가 켜져 있어야 합니다** — 수집한 데이터가 갈 곳이 없기 때문입니다.

전체 구조는 [`.agent/docs/ARCHITECTURE.md`](../.agent/docs/ARCHITECTURE.md), 운영 절차는 [`.agent/docs/RUNBOOK.md`](../.agent/docs/RUNBOOK.md)를 참고하세요.

## 가장 빠른 실행

```text
1) report-site\run-site.bat    먼저 켭니다
2) real-estate-finder\run-scan.bat
```

`run-scan.bat`은 서버 확인 → Edge 실행 → 네이버 로그인 확인 → 수집 → 서버 전달을 순서대로 처리합니다. 급매나 신규 매물이 없으면 카카오톡을 보내지 않으며, 그때도 **미전송 사유가 창에 출력됩니다.** 조용히 끝나는 것과 실패를 혼동하지 않기 위해서입니다.

급매가 아니어도 지금 전체 결과를 받고 싶으면 `send-report.bat`을 실행합니다. 이 스크립트는 `report-site`의 `manage.py send_digest`를 부르므로 브라우저도, 네이버 로그인도, 웹 서버도 필요 없습니다.

## 설치

```powershell
cd real-estate-finder
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install msedge
```

`report-site`는 이 가상환경을 함께 씁니다. 별도로 만들지 마세요. PostgreSQL 준비와 최초 데이터 이관은 `RUNBOOK.md`를 따릅니다.

## 명령

가상환경을 활성화한 뒤 실행합니다.

| 명령 | 설명 |
|---|---|
| `check-api` | 리포트 서버 연결과 활성 검색 조건을 출력합니다. 읽기 전용 |
| `browser-login` | Edge 로그인 프로필을 준비하고 로그인 상태를 확인합니다 |
| `scan-once` | 수집해서 서버에 넘깁니다. 서버가 급매·신규가 있을 때만 카카오톡을 보냅니다 |
| `smoke-test` | 수집해서 넘기되, 급매 알림 이력을 소모하지 않고 전체 매물을 보냅니다 |
| `collect-favorites` | 브라우저 수집 결과를 `data/favorites-latest.json`에만 저장합니다. 서버 전송 없음 |

```powershell
python -m real_estate_finder check-api
python -m real_estate_finder scan-once
```

옵션은 `--headless`(브라우저 창 숨김), `--edge-cdp`(Edge DevTools 주소), `--api-base`(리포트 서버 주소)입니다.

`scan-once`와 `smoke-test`는 실제 카카오톡 메시지를 보낼 수 있습니다. 코드 확인 목적으로 함부로 실행하지 마세요.

## 설정

이 프로젝트에는 설정 파일이 없습니다. 검색 조건(단지, 가격 상한, 급매가, 전용면적, 저층 할인)은 PostgreSQL에 있고 **Django admin에서 고칩니다**.

```text
http://127.0.0.1:8000/admin/
```

`report-site/.env`의 선택값 `REPORT_PATH_TOKEN`을 나중에 채우면 이 주소는
`/<TOKEN>/admin/`으로 바뀝니다.

수집기가 쓰는 값은 두 개뿐이며 둘 다 환경 변수로 읽습니다.

| 키 | 위치 | 기본값 |
|---|---|---|
| `FINDER_API_BASE` | 루트 `.env` 또는 환경 변수 | `http://127.0.0.1:8000` |
| `FINDER_API_TOKEN` | `report-site/.env` | 없음 (필수) |

토큰은 `report-site/.env`에서 직접 읽습니다. 복사해 두지 않으므로 양쪽이 어긋날 일이 없습니다.

## 동작 방식

```text
cli.scan-once
  -> ReportSiteClient.health()      서버가 없으면 브라우저를 열기 전에 중단
  -> ReportSiteClient.conditions()  어느 단지가 어느 조건인지 받아옴
  -> NaverBrowserCollector.collect_all()
       로그인 확인 -> 관심부동산 -> 단지별 화면 필터 -> 묶음 펼치기/스크롤 -> 매물 파싱
  -> 한 조건 안의 중복 제거
  -> POST /api/scans/               서버가 저장·판정·전송을 모두 수행
  -> 응답의 미전송/전송 사유 출력
```

수집은 로그인된 Edge를 Playwright CDP로 제어합니다. 비공개 API를 직접 호출하거나 접근 제한을 우회하지 않으며, CAPTCHA나 로그인 만료 화면을 만나면 중단합니다. 수집이 실패하면 모든 조건을 실패로 보고해 서버가 기존 매물을 비활성화하지 않게 합니다.

## 파일

| 파일 | 역할 |
|---|---|
| `real_estate_finder/cli.py` | 명령 정의, 실행 잠금, 수집과 전달 |
| `real_estate_finder/api_client.py` | `report-site` API 호출 |
| `real_estate_finder/collector.py` | 네이버 화면 수집 |
| `real_estate_finder/models.py` | 조건과 원본 매물 형식 |
| `real_estate_finder/parsing.py` | 화면 텍스트 → 숫자 |

`data/`는 Git에서 제외됩니다. 브라우저 프로필, 수집 스냅샷, 실행 잠금이 들어갑니다.

## 테스트

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

브라우저도 네트워크도 쓰지 않습니다. 판정·리포트·전송 테스트는 코드와 함께 `report-site`로 옮겨갔습니다.
