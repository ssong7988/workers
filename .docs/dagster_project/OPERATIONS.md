# 스케줄과 수동 실행

## 하나의 asset 체인, 세 가지 시간표

```text
naver_listings ──→ morning_report
  ├ ensure_site_op
  └ run_scan_op
```

`naver_listings`는 op 두 개를 품은 `graph_asset`이다. 서버 확인은 별도 asset이
아니라 이 안의 첫 단계다(이유는 README의 "서버 확인은 왜 asset이 아닌가").

시간대별 차이는 op를 no-op으로 만드는 방식이 아니라 **어느 범위를
실행하느냐**로 표현한다.

| 스케줄 | KST cron | job | 실행 범위 | 결과 |
|---|---:|---|---|---|
| `server_only_schedule` | `0 0-6,9-11,13-16,18-23 * * *` | `server_check_job` | `ensure_site_op`만 (op job) | 서버만 확인 |
| `scan_schedule` | `0 7,12,17 * * *` | `scan_job` | `naver_listings` | 서버 확인 후 수집 |
| `morning_report_schedule` | `0 8 * * *` | `morning_report_job` | `naver_listings` → `morning_report` | 서버 확인, 필요 시 재수집, 전체 리포트 전송 |

남은 설정 값은 `run_scan_op.mode` 하나뿐이다 — `scan_schedule`은 `run`,
`morning_report_schedule`은 `ensure_fresh`. `server_only_schedule`은 설정이
아예 없다(수집 op를 실행하지 않으므로 넣을 곳이 없다).

모든 시간은 `Asia/Seoul` 기준이며 세 스케줄의 기본 상태는 `RUNNING`이다.

## 각 단계가 실제로 하는 일

### `ensure_site_op` (op)

`report-site/ensure-site.ps1`을 실행한다. finder의 `check-api`가 성공하면
아무것도 하지 않는다. 실패하면 `report-site/run-site.ps1`을 숨김 프로세스로
띄우고 최대 60초 동안 API가 정상화되는지 기다린다.

`check-api`는 서버 프로세스만 보는 것이 아니라 API 인증과 PostgreSQL 접근도
함께 확인한다. 따라서 잘못된 `FINDER_API_TOKEN`이나 DB 장애도 서버 확인
실패로 나타날 수 있다.

**두 곳에서 같은 op을 재사용한다** — `server_check_job` 전체이자
`naver_listings`의 첫 단계다. 스크립트가 멱등이라 중복 호출이 안전하다.

### `run_scan_op` (op, `naver_listings` 안)

- `mode: run`: 수집기 venv의 `python -m real_estate_finder run-scan`을 실행한다.
- `mode: ensure_fresh`: PostgreSQL에서 오늘 07:00 이후 `success=True`인 `Scan`을
  찾는다. 있으면 수집을 생략하고, 없으면 같은 Python 명령을 실행한다.

`ensure_fresh`는 매물 행 개수를 검사하는 것이 아니라 성공한 수집 실행의
존재를 검사한다. 성공 수집의 결과가 활성 매물 0건이어도 "수집은 수행됨"으로
판단한다. 수집을 생략해도 "매물이 최신이다"라는 결과는 같으므로 두 경우 모두
머티리얼라이즈로 기록된다(생략한 경우 메타데이터에 `재수집: 생략`이 남는다).

예전의 `skip` 모드는 없어졌다. "이 시간대에는 수집하지 않는다"는 이제 이
asset을 실행하지 않는 것으로 표현한다.

**머티리얼라이즈마다 그 수집의 실제 숫자가 붙는다.** Dagster는 의존성이 다른
수집기 venv의 Python을 자식 프로세스로 실행하므로 종료 코드만 받는다. 실행 후
`manage.py scan_status --since=00:00 --json`으로 방금 기록된 `Scan` 행의
수집 수·조건 충족 수·급매 수·제외 수를 되읽어 `add_output_metadata()`로
붙인다. 이 조회가 실패해도 머티리얼라이즈 자체는 성공한다 — 숫자 대신 실패
사유가 남는다.

### `morning_report` (asset)

finder venv의 Python으로 `manage.py send_digest`를 직접 실행해 PostgreSQL의
현재 활성 매물을 카카오톡에 보낸다. 수집을 새로 실행하는 단계는 아니다.

예전의 `enabled` 설정은 없어졌다. "이 시간대에는 리포트를 보내지 않는다"는
이제 이 asset을 선택하지 않는 것으로 표현한다.

## 7시와 8시의 관계

```text
07:00  scan_job            ensure_site_op -> run_scan_op (mode: run)
          |
          +-- 실패 시 5분 뒤 한 번 재시도

08:00  morning_report_job  ensure_site_op -> run_scan_op (mode: ensure_fresh)
                             | 07:00 이후 성공 Scan 있음 -> 수집 생략
                             ` 없음                      -> 수집 실행
                           -> morning_report
```

따라서 8시 스케줄이 7시 수집의 안전망 역할을 한다. 7시 Dagster run 자체가
아니라 PostgreSQL 기록을 보므로 7시 이후 사람이 실행한 성공 수집도 인정한다.

## Dagster UI에서 수동 실행

수동 실행은 실제 서버 기동, 네이버 수집, 카카오 발송을 일으킬 수 있다.
무엇을 선택했는지 확인한 뒤 실행한다.

### 방법 1 — Catalog에서 asset을 직접 머티리얼라이즈 (권장)

1. `/common/dagster/console/`에서 `Catalog`를 연다(의존 그래프를 보려면 `Lineage`).
2. 실행할 asset을 고르고 `Materialize`를 누른다. 상류까지 함께 돌리려면
   상류를 포함해 선택한다.

YAML 없이 고를 수 있어서 아래 Launchpad 방식보다 간단하다. 특히 **재수집 없이
현재 DB 내용만 카카오로 보내려면** `morning_report` 하나만 선택해
머티리얼라이즈한다 — 예전에 `scan_step.mode: skip` + `report_step.enabled:
true`로 표현하던 조합이다. 이 방식은 데이터가 최신인지 검사하지 않는다.
최신성까지 보장하려면 `morning_report_job`을 실행한다.

### 방법 2 — Launchpad에서 job 실행

1. `/common/dagster/console/`을 연다.
2. `Jobs`에서 목적에 맞는 job을 선택한다.
3. `Launchpad`를 열고 `Launch Run`을 누른다.

| 목적 | job | run config |
|---|---|---|
| 서버만 확인 | `server_check_job` | 없음 |
| 서버 확인 후 매물 수집 | `scan_job` | 아래 `run` |
| 최신 수집 확인, 필요 시 수집 후 발송 (8시와 동일) | `morning_report_job` | 아래 `ensure_fresh` |
| report-site 재시작 | `restart_report_site_job` | 없음 |

`scan_job`과 `morning_report_job`의 run config는 이 한 블록뿐이고, `mode`만
바뀐다. 비워두면 기본값 `run`이 쓰인다.

```yaml
ops:
  naver_listings:
    ops:
      run_scan_op:
        config:
          mode: run          # 또는 ensure_fresh
```

`naver_listings`가 `graph_asset`이라 **`ops:`가 두 번 나온다** — 바깥은 asset을
실행하는 op, 안쪽은 그 asset이 품은 op다. 평범한 asset이라면 한 겹뿐이다.
경로를 틀리면 실행 시각이 아니라 Launch 시점에 `DagsterInvalidConfigError`로
거부된다.

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
| Python `real_estate_finder run-scan` | 20분 |
| Django `send_digest` | 3분 |
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

# 오늘 마지막 성공 수집의 실제 숫자 (Dagster가 머티리얼라이즈에 붙이는 값과 동일)
..\real-estate-finder\.venv\Scripts\python.exe manage.py scan_status --since=00:00 --json

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
| `/common/dagster/console/`이 열리지 않음 | `run-dagster.bat`, 3000 포트, Funnel status, prefix 세 값 일치 |
| `/common/dagster/`에 연결 실패 표시 | `DAGSTER_GRAPHQL_URL`, Dagster 프로세스, `/common/dagster/console/graphql` |
| 스케줄이 자동 실행되지 않음 | `run-dagster.bat` 창이 계속 떠 있는지, schedule이 RUNNING인지 |
| `ensure_site_op` 실패 | report-site 로그, `check-api`, `FINDER_API_TOKEN`, PostgreSQL 서비스 |
| scan이 로그인 만료로 실패 | Edge를 로그인된 상태로 열고 최소화하지 않았는지 |
| 8시에 재수집됨 | DB에 오늘 07:00 이후 `Scan(success=True)`가 있는지 |
| 실행 로그가 UI에 부족함 | Windows stdout/stderr compute log 제한이 있다. `.logs/dagster_project/<날짜>.log`(전체 콘솔, 프로세스 종료 시점에 기록)와 `data/storage/<run_id>/compute_logs/`(op별 stdout/stderr, storage 설정과 무관하게 항상 로컬 파일)도 함께 확인 |
| 메타데이터가 안 보임 / 재시작해도 run 이력이 없음 | `dagster` schema가 실제로 있는지, `data/dagster.yaml`의 `storage.postgres`가 맞게 쓰였는지, `POSTGRES_PASSWORD`가 `report-site/.env`에 있는지 확인 |

`dagster dev`는 현재 환경에서 검증된 간단한 단일 PC 실행 방식이지만 장기
운영용 배포 명령은 아니다. PC 종료·절전 또는 해당 콘솔 창 종료 시 webserver와
daemon이 함께 멈추며, 부팅 자동 시작도 아직 등록하지 않았다.
