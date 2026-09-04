# real-estate-finder 설치와 운영

## 최초 설치

저장소 루트에서 다음 가상환경을 만든다. `report-site`도 이 환경을 공유한다.

```powershell
cd real-estate-finder
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install msedge
```

주요 의존성은 Playwright, Django, waitress, psycopg, whitenoise다. 수집기만
고립된 패키지가 아니라 사이트까지 같은 환경을 사용하므로 requirements를
나눠 설치하지 않는다.

## 평상시 실행

평상시에는 Dagster UI에서 `scan_job`을 Launch Run 한다. 아래는 Dagster를 쓸
수 없을 때의 수동 호환 경로다.

```text
1. report-site\run-site.bat
2. real-estate-finder\run-scan.bat
```

`run-scan.bat`은 PowerShell 실행 정책을 우회해 `run-scan.ps1`을 부르는
더블클릭 진입점이다. PowerShell은 Python `run-scan` 명령만 호출하며, 그
명령의 `run_scan_workflow()` 함수가 네 단계를 수행한다.

1. `check-api`: 서버, Bearer 토큰, DB, 활성 조건 확인
2. Edge의 9222 디버깅 포트 확인 또는 전용 프로필로 새 Edge 시작
3. `browser-login`: 네이버 로그인 확인
4. `scan-once`: 수집, API 전달, 전송 또는 미전송 사유 출력

급매·신규가 없으면 카카오가 오지 않는 것이 정상이다. 마지막 출력과 Django
admin의 `Scan.notification`에서 이유를 확인한다.

## 명령별 부작용

모든 명령은 `real-estate-finder/`에서 실행한다.

| 명령 | 브라우저 | DB 쓰기 | 카카오 가능성 |
|---|---:|---:|---:|
| `check-api` | 없음 | 없음 | 없음 |
| `browser-login` | 사용 | 없음 | 없음 |
| `collect-favorites` | 사용 | 없음 | 없음 |
| `run-scan` | 사용 | 있음 | 신규 급매 또는 `notify_new` 신규가 있으면 전송 |
| `scan-once` | 사용 | 있음 | 신규 급매 또는 `notify_new` 신규가 있으면 전송 |
| `smoke-test` | 사용 | 있음 | 전체 매물 또는 실패 요약을 전송 |

```powershell
.\.venv\Scripts\python.exe -m real_estate_finder check-api
.\.venv\Scripts\python.exe -m real_estate_finder collect-favorites
.\.venv\Scripts\python.exe -m real_estate_finder run-scan
```

공통 옵션은 서브명령 **앞**에 둔다.

```powershell
.\.venv\Scripts\python.exe -m real_estate_finder --headless --edge-cdp http://127.0.0.1:9222 check-api
```

일상 수집은 화면 렌더링 지연을 진단하기 쉬운 headed 모드를 권장한다.

## 전체 리포트 즉시 전송

`send-report.bat`은 수집 명령이 아니다. 현재 PostgreSQL의 활성 매물을 Django
관리 명령으로 보낸다.

```text
send-report.bat
  -> send-report.ps1
       -> report-site/manage.py send_digest
```

브라우저, 네이버 로그인, 실행 중인 웹 서버는 필요하지 않지만 PostgreSQL과
카카오 인증은 필요하다. 공개 리포트가 현재 DB 시각을 서빙하지 않으면 링크
버튼을 빼고 텍스트만 보낸다.

## 설정을 읽는 위치

| 값 | 원천 | 설명 |
|---|---|---|
| `FINDER_API_BASE` | 루트 `.env` 또는 환경변수 | 기본 `http://127.0.0.1:8000` |
| `FINDER_API_TOKEN` | `report-site/.env` | 모든 `/api/` 요청에 쓰는 필수 Bearer 토큰 |
| `KAKAO_REPORT_URL` | 루트 `.env` | finder가 직접 쓰지는 않지만 `send-report.ps1`이 Django에 전달 |
| Edge 프로필 | `%LOCALAPPDATA%\naver-land-edge` | 로그인 상태를 보존하는 저장소 밖 디렉터리 |

API 클라이언트는 루트 `.env`를 읽은 다음 `report-site/.env`를 읽고, 이미 설정된
프로세스 환경변수를 덮어쓰지 않는다. 토큰을 finder 쪽에 복사하지 않는다.

## 로컬 수집 결과

`collect-favorites`는 `data/favorites-latest.json`에 임시 파일을 쓴 뒤 원자적으로
교체한다. `data/run.lock`은 동시 실행 방지 파일이다. 정상 종료 시 자동 삭제된다.
비정상 종료 뒤 프로세스가 정말 없는데 잠금만 남았다면 그 파일만 지운다.

`data/`와 브라우저 프로필 등 런타임 결과는 Git에 추가하지 않는다.

## 대표 장애 진단

`run-scan.ps1`·`send-report.ps1`의 전체 콘솔 출력은 `.logs/real-estate-finder/<날짜>.log`에도 남는다(두 스크립트가 같은 폴더를 쓴다). 창을 이미 닫았다면 여기서 다시 본다.

### `리포트 서버가 응답하지 않습니다`

`report-site/run-site.bat`을 먼저 켠다. 이미 켰다면 다음을 확인한다.

```powershell
cd real-estate-finder
.\.venv\Scripts\python.exe -m real_estate_finder check-api
```

- 연결 자체 실패: 8000 포트와 waitress 프로세스
- 401: `report-site/.env`의 `FINDER_API_TOKEN`
- 503/database: PostgreSQL 서비스와 DB 설정
- 활성 조건 0개: Django admin에서 조건의 `enabled`

### Edge가 떴지만 9222 포트가 열리지 않음

이미 실행 중인 일반 Edge가 새 인자를 흡수했을 수 있다. 모든 Edge 창을 닫고
`run-scan.bat`을 다시 실행한다. 다음 주소가 JSON을 내는지도 확인할 수 있다.

```powershell
Invoke-WebRequest http://127.0.0.1:9222/json/version -UseBasicParsing
```

### 로그인 만료로 보임

전용 프로필의 Edge에서 네이버에 다시 로그인한다. 수집 중 창을 최소화하지
않고 보이는 상태로 둔다. CAPTCHA나 비정상 접근 화면이면 자동 우회하지 말고
브라우저에서 정상 상태를 회복한 뒤 다시 실행한다.

### `이전 실행이 아직 진행 중입니다`

먼저 Python/Edge 수집 프로세스가 실제로 진행 중인지 확인한다. 없고 이전
비정상 종료가 확실할 때만 `real-estate-finder/data/run.lock`을 삭제한다.

### 조건 중복 또는 400 오류

서버가 반환한 한국어 오류가 콘솔에 그대로 표시된다. `observations` 배열,
`successful_conditions`, `failed_conditions`의 겹침, 같은 조건의 중복
`listing_id`를 확인한다. 응답을 무시하고 재전송하기보다 원본 생성 지점을
고친다.

## 검증

수집기 단위 테스트는 브라우저와 네트워크를 사용하지 않는다.

```powershell
cd real-estate-finder
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

서버 연결 계약은 읽기 전용으로 따로 확인한다.

```powershell
.\.venv\Scripts\python.exe -m real_estate_finder check-api
```

DOM 변경은 단위 테스트만으로 증명할 수 없다. 실제 수집이 필요한 경우에는
사용자 계정과 외부 메시지에 영향을 준다는 점을 확인하고 실행하며, 최소한
단지 예상 수, 카드 수, 매물 수, 실패 조건, 최종 `Scan.notification`을 함께
기록한다.
