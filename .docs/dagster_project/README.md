# Dagster 입문과 이 프로젝트의 구성

이 디렉터리는 Dagster를 처음 보는 사람이 현재 스케줄러가 무엇을 실행하고,
어떻게 웹 화면에 연결되며, 어디를 고쳐야 하는지 이해하기 위한 문서다.

- [`CONSOLE.md`](CONSOLE.md): `/common/dagster/` 요약 화면과
  `/common/dagster/console/` 네이티브 UI가 연결되는 원리
- [`OPERATIONS.md`](OPERATIONS.md): 스케줄, 수동 실행 설정, 재시도,
  시작·점검·장애 확인

## 먼저 알아둘 Dagster 용어

| 용어 | 이 프로젝트에서의 의미 |
|---|---|
| asset | 파이프라인이 만들어 내는 **산출물**을 선언한 것. `naver_listings`, `morning_report` 두 개가 이어져 있다. |
| op | 한 단계의 **행동**. 산출물이 없으면 op다 — `ensure_site_op`, `check_naver_login_op`, `keep_hable_awake_op`, `check_hable_ready_op`, `run_scan_op`, `restart_report_site` 여섯. |
| graph_asset | op 여러 개를 묶어 하나의 asset으로 만든 것. `naver_listings`가 `ensure_site_op → run_scan_op`을 품는다. |
| job | 한 번에 실행할 범위. `scan_job`·`morning_report_job`은 asset job, `server_check_job`·`pre_scan_health_job`·`hable_ready_job`·`restart_report_site_job`은 op job이다. |
| schedule | 정해진 시간에 job을 실행한다. 다섯 스케줄이 네 job에 붙는다 — `pre_scan_health_job`은 06시와 그 외 매시 정각 둘을 받는다. |
| run | job을 한 번 실행한 기록. 성공·실패·각 step 로그를 Dagster UI에서 본다. |
| materialization | asset을 한 번 만들어 낸 기록. 수집 수·급매 수 같은 메타데이터가 여기 붙는다. |
| daemon | 시각을 감시하다 schedule을 실제 run으로 만드는 백그라운드 프로세스다. |
| Catalog | Dagster UI의 asset **목록** 화면(`/assets`). 이름·설명·태그가 줄로 나온다. |
| Lineage | 같은 asset들을 **그래프**로 그리는 별도 화면(`/lineage`). 의존 화살표는 여기서 본다. |
| Launchpad | Dagster UI에서 run config를 넣고 job을 수동 실행하는 화면이다. |

Catalog와 Lineage는 좌측 내비게이션의 서로 다른 항목이다 — 같은 asset 집합을
목록으로 볼 거냐, 그래프로 볼 거냐의 차이다.

### 왜 op가 아니라 asset인가 (2026-09-04 전환)

원래는 `property_pipeline_job` 하나에 `ensure_site → scan_step → report_step`
세 op가 있었고, 세 스케줄이 run config로 각 op를 켜고 껐다. 예를 들어 매시
정각 스케줄은 세 단계를 모두 실행하되 뒤 두 개가 "이 시간대에는 아무것도 안
한다"고 로그만 남기고 끝났다.

asset으로 옮기면서 그 방식이 사라졌다. 각 스케줄이 원하는 것은 결국 체인의
**어디까지**이므로, 이제는 selection으로 표현한다. 설정 손잡이가
둘(`scan_step.mode`, `report_step.enabled`)에서 하나(`run_scan_op.mode`)로
줄었고, `skip`·`enabled: false` 같은 가짜 실행이 없어졌고, Catalog와 Lineage에
파이프라인의 산출물이 드러났고, 수집할 때마다 실제 수집 수·급매 수가
머티리얼라이즈에 남는다.

**job을 나눈 것이 lineage를 만든 것은 아니다.** Dagster에서 job끼리는
이어지지 않는다 — 순서를 아는 것은 asset 의존성이고, job은 그 그래프에서
얼마만큼을 실행할지 고르는 창일 뿐이다.

### 서버 확인은 왜 asset이 아닌가

전환 직후에는 `report_site_up`이라는 asset이 하나 더 있었다. 잘못된 선택이라
같은 날 되돌렸다. asset은 끝나고 나서 **남는 것**인데 "서버가 응답했다"는
아무것도 남기지 않는다 — 실제로 셋 중 유일하게 머티리얼라이즈 메타데이터가
영구히 비어 있었다.

지금은 `ensure_site_op`이라는 평범한 op이고, 두 곳에서 재사용된다:
`server_check_job`의 전부이자, `naver_listings` 안의 첫 단계다.
`ensure-site.ps1`이 멱등이라 중복 호출이 안전하다.

이게 가능한 이유가 `@dg.graph_asset`이다. 평범한 op은 asset의 **상류가 될 수
없지만**(`@dg.asset(deps=[some_op])`은 `ParameterCheckError`로 거부된다), asset
**안에서** 순서대로 도는 것은 문제없다. 대가는 서버 확인이 Catalog·Lineage에서
독립 노드로 안 보인다는 것이다 — 대신 모든 런에
`naver_listings.ensure_site_op` step으로 남고, asset 상세의 내부 그래프에서
보인다.

### Catalog에 무엇이 있어야 하는가

Catalog는 탐지가 아니라 **선언** 기반이다. Dagster는 PostgreSQL을 들여다보지
않으며, `@dg.asset`으로 적어준 것만 목록에 뜬다. 그래서 상태를 Django와
PostgreSQL이 소유하고 있어도 asset 선언은 성립한다 — Dagster가 직접 써야만
asset인 것이 아니다.

다만 선언만으로는 이름과 실행 시각밖에 안 남는다. 값어치는 asset이 산출물의
내용을 **메타데이터로 돌려줄 때** 생기고, 그래서 `run_scan_op`은 수집 후
`manage.py scan_status --json`으로 방금 기록된 `Scan` 행의 숫자를 되읽어
`add_output_metadata()`로 붙인다(graph_asset의 마지막 op 출력이 곧 asset의
출력이다). Django가 소유권을 넘기지 않고 숫자만 알려주는 구조라 경계도
흐려지지 않는다.

## 전체 구조

```text
                         Windows PC

  Dagster daemon
       |
       | schedule 또는 수동 실행
       v
  asset 2개. naver_listings는 op 2개를 품은 graph_asset이다.

  naver_listings                                    <- Catalog/Lineage 노드
    +-- ensure_site_op --> report-site/ensure-site.ps1
    `-- run_scan_op    --> real-estate-finder/run-scan.ps1
                       `-> manage.py scan_status  (ensure_fresh 판단 + 메타데이터)
       |
       v
  morning_report -------> real-estate-finder/send-report.ps1
                      `-> manage.py send_digest

  실행 범위:
  server_check_job        : ensure_site_op 만                (op job, 스케줄 없음)
  pre_scan_health_job     : ensure_site_op -> 네이버 로그인 확인
                            -> H-able 깨우기             (op job, 06시+매시)
  hable_ready_job         : H-able 준비 확인              (op job, 평일 18시)
  scan_job                : naver_listings                   (asset job)
  morning_report_job      : naver_listings -> morning_report (asset job)
  restart_report_site_job : restart_report_site              (op job, 스케줄 없음)
                              `--> report-site/restart-site.ps1

  Dagster webserver (127.0.0.1:3000)
       ^                         ^
       | GraphQL                 | Tailscale Funnel
  Django 공통 요약 화면          | /common/dagster/console
  (127.0.0.1:8000)              | 외부 브라우저
```

Dagster는 수집·판정·전송 로직을 새로 구현하지 않는다. 이미 검증된 PowerShell
스크립트와 Django 관리 명령을 정해진 순서로 호출하고, 시간표·재시도·실패
기록을 제공하는 조정자다.

## 코드 지도

| 파일 | 책임 |
|---|---|
| `dagster_project/definitions.py` | asset, op, job, schedule, 재시도, 실패 알림 정의 |
| `dagster_project/run-dagster.ps1` | 환경변수와 경로 prefix를 만들고 webserver와 daemon을 함께 기동 |
| `dagster_project/run-dagster.bat` | 사람이 더블클릭할 Windows 진입점 |
| `dagster_project/requirements.txt` | Dagster 전용 Python 의존성 |
| `report-site/ensure-site.ps1` | Django API를 확인하고 죽어 있으면 서버를 숨김 창으로 기동 |
| `report-site/properties/management/commands/scan_status.py` | PostgreSQL에서 지정 시각 이후 성공한 수집이 있는지 종료 코드로 응답 |
| `report-site/report/dagster_client.py` | Django가 Dagster GraphQL에서 최근 run을 읽는 읽기 전용 클라이언트 |
| `report-site/report/views.py` | 로그인 보호된 `/common/dagster/` 요약 화면 렌더링 |
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
3. `DAGSTER_WEBSERVER_PATH_PREFIX`를 `/common/dagster/console` 또는
   `/<TOKEN>/common/dagster/console`로 설정한다.
4. `report-site/.env`의 `POSTGRES_PASSWORD`를 읽어 `run/event-log/schedule storage`가 `property_report`의 `dagster` schema를 가리키는 `data/dagster.yaml`을 **매번 다시 쓴다.** 손으로 고쳐도 다음 실행에서 덮어써진다 — 바꾸고 싶으면 이 스크립트의 템플릿을 고친다.
5. `127.0.0.1:3000`에서 `dagster dev`를 실행한다. 이 명령이 개발용
   webserver와 schedule daemon을 함께 띄운다.

현재 의존성 범위는 `dagster>=1.13,<2`, `dagster-webserver>=1.13,<2`, `dagster-postgres>=0.29,<0.30`이며
가상환경은 finder·Django와 분리돼 있다. Dagster의 큰 의존성 트리가 기존
애플리케이션 패키지와 충돌하지 않게 하기 위해서다.

