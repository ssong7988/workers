# 스케줄과 수동 실행

## 하나의 job, 세 가지 시간표

`property_pipeline_job`의 순서는 항상 같다.

```text
ensure_site -> scan_step -> report_step
```

`dg.Nothing` 입력은 데이터를 전달하려는 것이 아니라 앞 단계가 성공한 뒤에만
다음 단계를 시작하도록 순서를 강제한다. 시간대별 차이는 op를 없애는 방식이
아니라 run config로 각 op를 no-op 또는 실제 실행 모드로 바꾸는 방식이다.

| 스케줄 | KST cron | `scan_step.mode` | `report_step.enabled` | 결과 |
|---|---:|---|---:|---|
| `server_only_schedule` | `0 0-6,9-11,13-16,18-23 * * *` | `skip` | `false` | 서버만 확인 |
| `scan_schedule` | `0 7,12,17 * * *` | `run` | `false` | 서버 확인 후 수집 |
| `morning_report_schedule` | `0 8 * * *` | `ensure_fresh` | `true` | 서버 확인, 필요 시 재수집, 전체 리포트 전송 |

모든 시간은 `Asia/Seoul` 기준이며 세 스케줄의 기본 상태는 `RUNNING`이다.

## 각 단계가 실제로 하는 일

### `ensure_site`

`report-site/ensure-site.ps1`을 실행한다. finder의 `check-api`가 성공하면
아무것도 하지 않는다. 실패하면 `report-site/run-site.ps1`을 숨김 프로세스로
띄우고 최대 60초 동안 API가 정상화되는지 기다린다.

`check-api`는 서버 프로세스만 보는 것이 아니라 API 인증과 PostgreSQL 접근도
함께 확인한다. 따라서 잘못된 `FINDER_API_TOKEN`이나 DB 장애도 서버 확인
실패로 나타날 수 있다.

### `scan_step`

- `skip`: 로그만 남기고 성공한다.
- `run`: `real-estate-finder/run-scan.ps1`을 무조건 한 번 실행한다.
- `ensure_fresh`: PostgreSQL에서 오늘 07:00 이후 `success=True`인 `Scan`을
  찾는다. 있으면 수집을 생략하고, 없으면 `run-scan.ps1`을 실행한다.

`ensure_fresh`는 매물 행 개수를 검사하는 것이 아니라 성공한 수집 실행의
존재를 검사한다. 성공 수집의 결과가 활성 매물 0건이어도 “수집은 수행됨”으로
판단한다.

### `report_step`

- `enabled: false`: 로그만 남기고 성공한다.
- `enabled: true`: `real-estate-finder/send-report.ps1`을 실행한다.

이 스크립트는 PostgreSQL의 현재 활성 매물을 `manage.py send_digest`로
카카오톡에 보낸다. 수집을 새로 실행하는 단계는 아니다.

## 7시와 8시의 관계

```text
07:00  ensure_site -> 무조건 scan
          |
          +-- op 실패 시 5분 뒤 한 번 재시도

08:00  ensure_site -> 07:00 이후 성공 Scan 확인
                         | 있음 -> scan 생략 -> report
                         ` 없음 -> scan 실행 -> report
```

따라서 8시 스케줄이 7시 수집의 안전망 역할을 한다. 7시 Dagster run 자체가
아니라 PostgreSQL 기록을 보므로 7시 이후 사람이 실행한 성공 수집도 인정한다.

## Dagster UI에서 수동 실행

1. `/dagster/console/`을 연다.
2. `Deployment` 또는 `Jobs`에서 `property_pipeline_job`을 선택한다.
3. `Launchpad`를 연다.
4. 목적에 맞는 YAML을 넣고 `Launch Run`을 누른다.

수동 실행은 실제 서버 기동, 네이버 수집, 카카오 발송을 일으킬 수 있다.
설정을 확인한 뒤 실행한다.

### 서버만 확인

```yaml
ops:
  scan_step:
    config:
      mode: skip
  report_step:
    config:
      enabled: false
```

### 서버 확인 후 매물 수집

```yaml
ops:
  scan_step:
    config:
      mode: run
  report_step:
    config:
      enabled: false
```

### 최신 수집 확인, 필요 시 수집 후 카카오 발송

8시 스케줄과 같은 동작이다.

```yaml
ops:
  scan_step:
    config:
      mode: ensure_fresh
  report_step:
    config:
      enabled: true
```

### 재수집 없이 현재 DB 내용을 카카오 발송

서버와 DB/API가 정상인지 확인한 뒤 PostgreSQL의 현재 활성 매물을 보낸다.

```yaml
ops:
  scan_step:
    config:
      mode: skip
  report_step:
    config:
      enabled: true
```

이 모드는 데이터가 최신인지 검사하지 않는다. 최신성까지 보장하려면 바로 위의
`ensure_fresh + enabled` 구성을 사용한다.

## 재시도와 실패 알림

세 op 모두 다음 정책을 사용한다.

```python
RetryPolicy(max_retries=1, delay=300)
```

첫 실패 5분 뒤 한 번 더 시도한다. 재시도까지 실패하면 `alert_on_failure`
hook이 `manage.py send_alert`를 호출해 실패한 job/op와 예외를 카카오톡으로
보낸다. 실패 알림 자체가 실패해도 원래 실패 기록을 덮지 않으며 Dagster run이
최종 진단 원천이다.

주요 제한 시간은 다음과 같다.

| 호출 | 제한 시간 |
|---|---:|
| `ensure-site.ps1` | 90초 |
| `scan_status` | 30초 |
| `run-scan.ps1` | 20분 |
| `send-report.ps1` | 3분 |
| 실패 카카오 알림 | 30초 |

## 상태 확인 명령

```powershell
# 정의가 로드되는지
cd dagster_project
.\.venv\Scripts\python.exe -c "import definitions; print([j.name for j in definitions.defs.resolve_all_job_defs()])"

# 스케줄 목록과 RUNNING 여부
$env:DAGSTER_HOME = (Resolve-Path .\data)
.\.venv\Scripts\dagster.exe schedule list -f definitions.py

# 프로세스가 3000번 포트에서 듣는지
Get-NetTCPConnection -LocalPort 3000 -State Listen

# 공개 proxy 상태
& 'C:\Program Files\Tailscale\tailscale.exe' funnel status

# 업무 DB에서 오늘 07시 이후 성공 수집 여부만 확인
cd ..\report-site
..\real-estate-finder\.venv\Scripts\python.exe manage.py scan_status --since=07:00

# Dagster 테이블이 dagster schema에만 있고 public(Django)에는 없는지
# (psql이 PATH에 없어 manage.py dbshell 대신 Django ORM 연결을 직접 쓴다)
..\real-estate-finder\.venv\Scripts\python.exe -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'report_site.settings')
django.setup()
from django.db import connection
with connection.cursor() as c:
    c.execute(\"select table_schema, count(*) from information_schema.tables where table_name in ('runs','event_logs','job_ticks') group by 1\")
    print(c.fetchall())
"
```

마지막 두 명령은 읽기 전용이지만 `scan_status`는 성공한 수집이 없으면 의도적으로
종료 코드 1을 반환한다.

## 흔한 장애

| 증상 | 우선 확인할 것 |
|---|---|
| `/dagster/console/`이 열리지 않음 | `run-dagster.bat`, 3000 포트, Funnel status, prefix 세 값 일치 |
| `/dagster/`에 연결 실패 표시 | `DAGSTER_GRAPHQL_URL`, Dagster 프로세스, `/dagster/console/graphql` |
| 스케줄이 자동 실행되지 않음 | `run-dagster.bat` 창이 계속 떠 있는지, schedule이 RUNNING인지 |
| `ensure_site` 실패 | report-site 로그, `check-api`, `FINDER_API_TOKEN`, PostgreSQL 서비스 |
| scan이 로그인 만료로 실패 | Edge를 로그인된 상태로 열고 최소화하지 않았는지 |
| 8시에 재수집됨 | DB에 오늘 07:00 이후 `Scan(success=True)`가 있는지 |
| 실행 로그가 UI에 부족함 | Windows stdout/stderr compute log 제한이 있다. `.logs/dagster_project/<날짜>.log`(전체 콘솔, 프로세스 종료 시점에 기록)와 `data/storage/<run_id>/compute_logs/`(op별 stdout/stderr, storage 설정과 무관하게 항상 로컬 파일)도 함께 확인 |
| 메타데이터가 안 보임 / 재시작해도 run 이력이 없음 | `dagster` schema가 실제로 있는지, `data/dagster.yaml`의 `storage.postgres`가 맞게 쓰였는지, `POSTGRES_PASSWORD`가 `report-site/.env`에 있는지 확인 |

`dagster dev`는 현재 환경에서 검증된 간단한 단일 PC 실행 방식이지만 장기
운영용 배포 명령은 아니다. PC 종료·절전 또는 해당 콘솔 창 종료 시 webserver와
daemon이 함께 멈추며, 부팅 자동 시작도 아직 등록하지 않았다.
