# Dagster 입문과 이 프로젝트의 구성

이 디렉터리는 Dagster를 처음 보는 사람이 현재 스케줄러가 무엇을 실행하고,
어떻게 웹 화면에 연결되며, 어디를 고쳐야 하는지 이해하기 위한 문서다.

- [`CONSOLE.md`](CONSOLE.md): `/dagster/` 요약 화면과
  `/dagster/console/` 네이티브 UI가 연결되는 원리
- [`OPERATIONS.md`](OPERATIONS.md): 스케줄, 수동 실행 설정, 재시도,
  시작·점검·장애 확인

## 먼저 알아둘 Dagster 용어

| 용어 | 이 프로젝트에서의 의미 |
|---|---|
| op | 한 단계의 작업. `ensure_site`, `scan_step`, `report_step` 세 개가 있다. |
| job | op를 어떤 순서로 실행할지 정한 그래프. `property_pipeline_job` 하나다. |
| schedule | 정해진 시간에 job을 어떤 설정으로 실행할지 정한다. 세 스케줄이 같은 job을 서로 다른 설정으로 실행한다. |
| run | job을 한 번 실행한 기록. 성공·실패·각 op 로그를 Dagster UI에서 본다. |
| daemon | 시각을 감시하다 schedule을 실제 run으로 만드는 백그라운드 프로세스다. |
| Launchpad | Dagster UI에서 run config를 넣고 job을 수동 실행하는 화면이다. |

## 전체 구조

```text
                         Windows PC

  Dagster daemon
       |
       | schedule 또는 수동 실행
       v
  property_pipeline_job
       |
       +--> ensure_site  ----> report-site/ensure-site.ps1
       |
       +--> scan_step    ----> real-estate-finder/run-scan.ps1
       |                  `--> manage.py scan_status
       |
       `--> report_step  ----> real-estate-finder/send-report.ps1
                                `--> manage.py send_digest

  Dagster webserver (127.0.0.1:3000)
       ^                         ^
       | GraphQL                 | Tailscale Funnel
  Django 요약 화면              | /dagster/console
  (127.0.0.1:8000)              | 외부 브라우저
```

Dagster는 수집·판정·전송 로직을 새로 구현하지 않는다. 이미 검증된 PowerShell
스크립트와 Django 관리 명령을 정해진 순서로 호출하고, 시간표·재시도·실패
기록을 제공하는 조정자다.

## 코드 지도

| 파일 | 책임 |
|---|---|
| `dagster_project/definitions.py` | op, job, schedule, 재시도, 실패 알림 정의 |
| `dagster_project/run-dagster.ps1` | 환경변수와 경로 prefix를 만들고 webserver와 daemon을 함께 기동 |
| `dagster_project/run-dagster.bat` | 사람이 더블클릭할 Windows 진입점 |
| `dagster_project/requirements.txt` | Dagster 전용 Python 의존성 |
| `report-site/ensure-site.ps1` | Django API를 확인하고 죽어 있으면 서버를 숨김 창으로 기동 |
| `report-site/properties/management/commands/scan_status.py` | PostgreSQL에서 지정 시각 이후 성공한 수집이 있는지 종료 코드로 응답 |
| `report-site/report/dagster_client.py` | Django가 Dagster GraphQL에서 최근 run을 읽는 읽기 전용 클라이언트 |
| `report-site/report/views.py` | 로그인 보호된 `/dagster/` 요약 화면 렌더링 |
| `report-site/report_site/settings.py` | Django·Dagster가 공유할 URL prefix와 GraphQL 주소 계산 |

## 하나의 DB, 두 schema

업무 데이터와 스케줄러 메타데이터는 같은 PostgreSQL `property_report` DB에 있지만 schema로 나뉘어 있어 서로 섞이지 않는다.

1. `public` schema (Django가 소유)
   - 매물, 원본 관측, 검색 조건, 수집 성공 여부를 저장한다.
   - `scan_status`와 리포트가 보는 업무 데이터의 원천이다.
2. `dagster` schema
   - Dagster run, schedule, event log 등 스케줄러 자체 이력을 저장한다(2026-09-04부터 — 그 전에는 `dagster_project/data/`의 SQLite 파일이었다).
   - 매물 데이터는 들어 있지 않다. `dagster_project/data/` 자체는 여전히 Git에서 제외되며 `dagster.yaml`과 compute log(op의 stdout/stderr)만 로컬에 남는다.

따라서 8시 작업은 “7시 Dagster run이 성공했는가”가 아니라 PostgreSQL `public`에
07:00 이후 `Scan(success=True)`가 있는지를 확인한다. 사람이 수동으로 수집한
성공 기록도 똑같이 최신 수집으로 인정하기 위해서다. schema를 나눈 뒤에도 이 판단
기준은 바뀌지 않는다 — Dagster run 이력이 아니라 항상 업무 데이터를 본다.

## 설치와 기동

최초 한 번만 Dagster 전용 가상환경을 만들고, `property_report` DB에 `dagster` schema를 만든다(`.docs/RUNBOOK.md`의 "최초 한 번만 준비" 참고 — 소유자 권한만 있으면 되고 superuser는 필요 없다).

```powershell
py -3.11 -m venv dagster_project\.venv
dagster_project\.venv\Scripts\python.exe -m pip install -r dagster_project\requirements.txt
```

평상시에는 다음 파일을 더블클릭한다.

```text
dagster_project\run-dagster.bat
```

이 스크립트는 다음을 수행한다.

1. `dagster_project/data`를 `DAGSTER_HOME`으로 지정한다. (compute log와 `dagster.yaml`만 여기 남는다 — run/schedule 이력은 아래 4번의 PostgreSQL에 있다)
2. `report-site/.env`에서 선택값 `REPORT_PATH_TOKEN`을 읽는다.
3. `DAGSTER_WEBSERVER_PATH_PREFIX`를 `/dagster/console` 또는
   `/<TOKEN>/dagster/console`로 설정한다.
4. `report-site/.env`의 `POSTGRES_PASSWORD`를 읽어 `run/event-log/schedule storage`가 `property_report`의 `dagster` schema를 가리키는 `data/dagster.yaml`을 **매번 다시 쓴다.** 손으로 고쳐도 다음 실행에서 덮어써진다 — 바꾸고 싶으면 이 스크립트의 템플릿을 고친다.
5. `127.0.0.1:3000`에서 `dagster dev`를 실행한다. 이 명령이 개발용
   webserver와 schedule daemon을 함께 띄운다.

현재 의존성 범위는 `dagster>=1.13,<2`, `dagster-webserver>=1.13,<2`, `dagster-postgres>=0.29,<0.30`이며
가상환경은 finder·Django와 분리돼 있다. Dagster의 큰 의존성 트리가 기존
애플리케이션 패키지와 충돌하지 않게 하기 위해서다.

