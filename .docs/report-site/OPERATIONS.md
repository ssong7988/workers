# report-site 설치와 운영

## 필요한 구성

- `real-estate-finder/.venv`: Django까지 설치된 공유 Python 환경
- PostgreSQL과 `property_report` DB/역할
- `report-site/.env`: API 토큰, DB 비밀번호, 선택 경로 설정
- 루트 `.env`: 공개 `KAKAO_REPORT_URL`
- 카카오 발송 시 `kakao-notifier` 인증 상태
- 외부 공개 시 Tailscale Funnel

실제 비밀번호, 토큰, 쿠키, 인증 코드는 이 문서나 Git에 기록하지 않는다.

## 환경변수

`report-site/.env.example`을 `.env`로 복사하고 값을 채운다.

| 값 | 필수 | 기본/역할 |
|---|---:|---|
| `FINDER_API_TOKEN` | 필수 | finder가 `/api/`에 보내는 추측 불가 Bearer 토큰 |
| `POSTGRES_PASSWORD` | 필수 | 애플리케이션 DB 역할 비밀번호 |
| `REPORT_PATH_TOKEN` | 선택 | 비우면 명시적 최상위 경로, 값이 있으면 비-API 앞에 prefix |
| `POSTGRES_DB` | 선택 | 기본 `property_report` |
| `POSTGRES_USER` | 선택 | 기본 `property_report` |
| `POSTGRES_HOST` | 선택 | 기본 `127.0.0.1` |
| `POSTGRES_PORT` | 선택 | 기본 `5432` |
| `DJANGO_SECRET_KEY` | 선택 | session/admin을 장기 운영하면 별도 강한 값 권장 |
| `DAGSTER_GRAPHQL_URL` | 선택 | 기본 로컬 3000의 현재 prefix GraphQL |
| `DAGSTER_TIMEOUT_SECONDS` | 선택 | 기본 5초 |

루트 `.env`의 `KAKAO_REPORT_URL`은 공개 리포트의 완성된 `/report/` URL이다.
두 `.env`는 Git에서 제외된다. `settings.py`는 site `.env`를 먼저, 루트 `.env`를
다음에 읽되 이미 존재하는 프로세스 환경변수는 덮어쓰지 않는다.

## PostgreSQL 최초 준비

정확한 설치와 데이터 이관 절차는 상위 `RUNBOOK.md`를 기준으로 한다. 준비 뒤
최소 흐름은 다음과 같다.

```powershell
cd report-site
..\real-estate-finder\.venv\Scripts\python.exe manage.py migrate
..\real-estate-finder\.venv\Scripts\python.exe manage.py import_searches
```

이전 JSON 상태를 이관하는 경우에만 `import_state`를 실행한다. 두 import 명령은
반복 실행해도 중복을 만들지 않도록 설계됐지만, 운영 원천은 이관 후 DB다.

## 서버 실행

사람은 다음 파일을 더블클릭한다.

```text
report-site\run-site.bat
```

PowerShell에서는 다음과 같다.

```powershell
cd report-site
.\run-site.ps1
```

스크립트는 순서대로 실행한다.

1. 공유 Python 환경 존재 확인
2. `manage.py check`
3. `manage.py migrate --check` — 누락 migration을 자동 적용하지 않음
4. `collectstatic` — waitress가 못 주는 admin 정적 파일을 whitenoise용으로 수집
5. 현재 report, statistics, Dagster, admin URL 출력
6. waitress를 `127.0.0.1:8000`에 바인딩

migration이 누락되면 안전하게 멈추고 적용 명령을 안내한다. 서버는 loopback에만
열리며 외부 공개는 Funnel이 별도로 담당한다.

데이터는 요청마다 DB에서 읽으므로 스캔 후 서버 재시작은 필요 없다. 코드를
바꿨다면 waitress 프로세스를 재시작해야 한다.

## 스케줄러용 `ensure-site.ps1`

`run-site.ps1`은 마지막에 waitress를 계속 실행하므로 스케줄러 단계로 직접
호출하면 끝나지 않는다. `ensure-site.ps1`은 다음처럼 동작한다.

1. finder `check-api`로 프로세스, 인증, DB를 함께 확인한다.
2. 정상이면 즉시 0으로 끝난다.
3. 실패하면 `run-site.ps1`을 숨김 PowerShell 프로세스로 시작한다.
4. 3초 간격으로 최대 60초 health를 확인한다.
5. 정상화되지 않으면 종료 코드 1을 반환한다.

`run-site.bat`은 실패 시 사람이 읽도록 `pause`하므로 백그라운드 기동에는 쓰지
않는다.

## Django admin

기본 주소는 `http://127.0.0.1:8000/admin/`이며 선택 토큰을 쓰면
`/<TOKEN>/admin/`으로 이동한다. `run-site`가 현재 완성 주소를 출력한다.

| 화면 | 운영 용도 |
|---|---|
| Global rule | 저층 규칙, 시간대와 보고 설정 |
| Search condition | 단지 별칭, 지역, 면적, 타입, 가격, 알림, 활성 상태 수정 |
| Scan | 실행 집계와 전송·미전송 이유 확인 |
| Observation | 원본과 `exclusion_code`별 탈락 원인 확인 |
| Listing | 현재 활성 상태, 급매, 최초·최근 확인 시각 확인 |
| Notification failure | 카카오 실패 원문과 처리 상태 확인 |

Observation과 Scan은 admin에서 새로 만들지 못하며 수집 이력으로 읽는다. admin
비밀번호를 잊었다면 값 자체를 문서에 적지 말고 재설정한다.

```powershell
..\real-estate-finder\.venv\Scripts\python.exe manage.py changepassword admin
```

Funnel 사용 시 admin 로그인 화면도 공개 호스트에 노출되므로 강한 비밀번호가
필요하다.

## 관리 명령

| 명령 | 쓰기/외부 영향 | 용도 |
|---|---|---|
| `check_report` | 읽기 전용, 공개 HTTP 조회 | DB 기준 시각과 공개 리포트 시각 비교 |
| `scan_status --since=07:00` | 읽기 전용 | 오늘 지정 시각 이후 성공 Scan 존재를 종료 코드로 반환 |
| `import_searches` | DB 쓰기 | seed YAML을 초기 설정으로 이관 |
| `import_state` | DB 쓰기 | 예전 JSON/JSONL 상태 이관 |
| `reclassify_observations --dry-run` | 읽기 전용 | 현재 규칙으로 재판정할 변화 미리 보기 |
| `reclassify_observations` | DB 쓰기 | 과거 Observation의 제외 사유·코드 갱신 |
| `send_digest` | 카카오 전송 | 현재 활성 매물 전체 전송 |
| `send_alert <text>` | 카카오 전송 | 스케줄러 등 운영 오류 전송 |

`scan_status`는 성공 수집이 없으면 정상적인 판단 결과로 종료 코드 1을 낸다.
명령 자체의 장애와 혼동하지 않는다.

## 웹 화면

### 매물 리포트

기본 `/report/`. 활성 매물을 전체로 보여 주며 지역 또는 개별 단지로 좁힐 수
있다. 기본 범위는 전체다. 급매 섹션과 조건별 매물을 같은 DB 조회에서 만든다.

응답은 `Cache-Control: no-store`다. 최신성 검사의 기준인
`data-observed-at`이 HTML에 포함된다.

### 가격 통계

기본 `/statistics/`. 기간은 `month=YYYY-MM` 또는 `from`, `to`를 사용하고,
월이 우선한다. 아무 값이 없으면 최근 1개월이다. 잘못된 문자열은 500을 내지
않고 기본값으로 돌아가며 화면에 이유를 표시한다.

범위는 `region` 또는 `condition`이며 단지가 지역보다 우선한다. 기본 지역은
현재 조건에 과천이 있으면 과천, 없으면 전체다. 차트는 서버가 좌표를 계산한
inline SVG이고 JavaScript 의존성이 없다.

### Dagster 요약

기본 `/dagster/`. staff 로그인이 필요하고 로컬 Dagster GraphQL을 읽어 최근
run을 요약한다. Dagster가 꺼져도 500 대신 연결 실패 상태를 보여 준다. 실제
네이티브 UI `/dagster/console/`은 Funnel이 3000 포트로 직접 보내므로 Django
로그인 보호를 받지 않는다. 자세한 내용은 `../dagster_project/CONSOLE.md`를 본다.

## 선택 경로 토큰 변경

`REPORT_PATH_TOKEN`을 바꾸면 다음을 한 세트로 맞춘다.

1. `report-site/.env`
2. 루트 `.env`의 `KAKAO_REPORT_URL`
3. Dagster console의 Funnel mount와 target prefix
4. report-site와 Dagster 프로세스 재시작
5. 공개 report, statistics, Dagster summary/console 확인

API 경로는 바뀌지 않는다. 토큰은 인증을 완전히 대체하지 않으며 URL을 아는
사람은 공개 리포트를 볼 수 있다.

## 외부 공개와 최신성 확인

루트 `/`를 로컬 8000으로 보내는 Tailscale Funnel 구성이 필요하다. 설치와
등록 명령은 상위 `RUNBOOK.md`를 따른다. 현재 상태 확인:

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' funnel status
```

공개 리포트가 현재 DB를 보여주는지 확인:

```powershell
cd report-site
..\real-estate-finder\.venv\Scripts\python.exe manage.py check_report
```

이 명령은 카카오를 보내거나 DB를 수정하지 않는다. 서버·Funnel이 꺼졌거나
시각이 다르면 종료 코드 1이다.

## 검증

코드 변경 시 최소 검사:

```powershell
cd report-site
..\real-estate-finder\.venv\Scripts\python.exe manage.py check
..\real-estate-finder\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

전체 테스트:

```powershell
..\real-estate-finder\.venv\Scripts\python.exe manage.py test
```

테스트 DB를 만들기 위해 운영 DB 역할에 일시적인 `CREATEDB` 권한이 필요할 수
있다. 권한을 줄 수 없다면 별도 테스트 설정을 사용하고, 실행하지 못한 검증을
명시한다. 실제 PostgreSQL 데이터, 카카오 메시지, 공개 Funnel을 단위 테스트와
혼동하지 않는다.

## 대표 장애

| 증상 | 우선 확인 |
|---|---|
| 서버 시작 전 `check` 실패 | `.env`, `FINDER_API_TOKEN`, Django 설정 오류 |
| migration check 실패 | PostgreSQL 서비스·자격증명, `manage.py migrate` |
| admin CSS 없음 | `collectstatic`, `staticfiles/`, whitenoise middleware |
| finder 401 | 양쪽이 읽는 `report-site/.env`의 API 토큰 |
| finder database 503 | PostgreSQL 서비스와 DB/role 설정 |
| 스캔 400 | API 오류 본문, 조건 목록 겹침, 중복 ID, 시각·가격 형식 |
| 저장됐지만 finder는 502 | NotificationFailure와 카카오 인증/도메인 |
| 카카오 버튼이 없음 | `KAKAO_REPORT_URL`, `check_report`, `data-observed-at` |
| 새 데이터가 화면에 없음 | scope 필터, Listing active, 실행 중 서버가 새 코드인지 |
| 통계 표본이 리포트보다 많음 | 정상 정책: 가격만 초과한 Observation도 포함 |
| 통계가 옛 조건 기준 | 필요성 확인 후 `reclassify_observations --dry-run` |
