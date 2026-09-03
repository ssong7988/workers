# 수동 실행 매뉴얼

## 메인 엔트리 포인트

에이전트 없이 실행하는 더블클릭 진입점은 세 개다.

```text
report-site\run-site.bat             애플리케이션 서버. 나머지 둘보다 먼저 켠다
real-estate-finder\run-scan.bat      매물 조회. 급매/신규가 있을 때만 카카오톡 전송
real-estate-finder\send-report.bat   현재 조건충족 매물 전체를 카카오톡 1통으로 전송
```

**`run-site.bat`을 먼저 켠다.** 데이터베이스와 판정, 카카오 전송이 모두 그쪽에 있어서 수집 결과가 갈 곳이 필요하다. 서버가 없으면 `run-scan.bat`은 브라우저를 열기 전에 멈추고 무엇을 켜야 하는지 알려준다.

`run-scan.bat`은 급매나 신규 매물이 없으면 카카오톡을 보내지 않는다. 이때도 창에 미전송 사유가 출력되므로, 조용히 끝나는 것과 실패를 혼동하지 않는다. 급매가 아니어도 조사 결과 전체를 지금 받고 싶으면 `send-report.bat`을 실행한다.

PowerShell에서 직접 실행하려면 저장소 루트에서 다음 명령을 사용한다.

```powershell
.\real-estate-finder\run-scan.ps1
```

스크립트는 아래 작업을 한 번에 수행한다.

1. 리포트 서버가 응답하는지 확인한다. 응답하지 않으면 여기서 멈춘다.
2. 디버깅 포트 `9222`를 사용하는 전용 Edge 프로필을 실행한다.
3. 네이버 로그인 상태를 확인하고, 로그인이 필요하면 최대 5분 동안 기다린다.
4. `python -m real_estate_finder scan-once`로 매물을 수집해 서버에 넘긴다.
5. 서버가 조건 판정 후 급매 또는 신규 매물이 있으면 카카오톡을 보낸다. 없으면 미전송 사유가 창에 출력된다.

`send-report.bat`은 `report-site`의 `manage.py send_digest`를 실행한다. 데이터베이스의 활성 매물을 쓰므로 Edge 기동, 네이버 로그인, 웹 서버 실행이 모두 필요 없다.

## 최초 한 번만 준비

PowerShell에서 다음 명령을 실행한다.

```powershell
cd real-estate-finder
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install msedge
```

`report-site`는 이 가상환경을 함께 쓴다. 별도 venv를 만들지 않는다.

데이터베이스는 PostgreSQL이다. 역할과 DB를 만든 뒤 `report-site/.env`를 채우고 마이그레이션을 적용한다.

```powershell
cd ..\report-site
Copy-Item .env.example .env    # REPORT_PATH_TOKEN, FINDER_API_TOKEN, POSTGRES_PASSWORD를 채운다
..\real-estate-finder\.venv\Scripts\python.exe manage.py migrate
..\real-estate-finder\.venv\Scripts\python.exe manage.py createsuperuser
..\real-estate-finder\.venv\Scripts\python.exe manage.py import_searches
```

검색 조건은 이후 Django admin(`.../r/<REPORT_PATH_TOKEN>/admin/`)에서 고친다. `properties/seed/searches.yaml`은 첫 시드일 뿐이다.

카카오톡 전송에는 `kakao-notifier/.env`와 `kakao-notifier/data/kakao-token.json`이 필요하다. 아직 없다면 `kakao-notifier/README.md`의 앱 등록과 최초 인증 절차를 먼저 수행한다. 비밀키와 토큰은 Git에 커밋하지 않는다.

## 자주 쓰는 개별 명령

`real-estate-finder/`에서 가상환경을 활성화한 뒤 실행한다.

```powershell
# 서버 연결과 활성 검색 조건 확인 (읽기 전용)
python -m real_estate_finder check-api

# 정규 급매 발송 이력을 소모하지 않는 시험 조회
python -m real_estate_finder smoke-test

# 한 번 조회하고 필요한 카카오 알림 전송
python -m real_estate_finder scan-once

# 브라우저 수집만 하고 서버에 보내지 않음 (화면 문제 조사용)
python -m real_estate_finder collect-favorites
```

전송과 통계는 `report-site/`에서 다룬다.

```powershell
cd ..\report-site
# 현재 매물 전체 보고를 카카오톡으로 전송 (send-report.bat과 같은 동작)
..\real-estate-finder\.venv\Scripts\python.exe manage.py send_digest

# 저장된 수집 원본을 현재 검색 조건으로 다시 판정 (조건을 바꾼 뒤 통계를 맞출 때)
..\real-estate-finder\.venv\Scripts\python.exe manage.py reclassify_observations --dry-run
```

## 웹 리포트 서버 실행

`report-site/`(Django)가 PostgreSQL을 요청마다 읽어 렌더링한다. 빌드나 배포 단계가 없다 — 매물을 새로 조회하면 서버를 새로고침하는 것만으로 리포트가 갱신된다. 다만 코드를 바꿨다면 이 서버를 재시작해야 한다.

최초 한 번, `report-site/.env`가 없다면 만든다.

```powershell
cd report-site
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_hex(16))"
# 위에서 나온 값을 .env의 REPORT_PATH_TOKEN=에 붙여넣는다.
```

서버 실행:

```powershell
cd report-site
.\run-site.ps1
```

더블클릭하려면 `run-site.bat`을 쓴다. 실행하면 콘솔에 로컬 주소(`http://127.0.0.1:8000/r/<토큰>/`)와, `KAKAO_REPORT_URL`이 설정돼 있으면 공개 주소도 함께 출력한다. 가격 통계는 그 주소 뒤에 `stats/`를 붙인 곳에 있고, 리포트 헤더의 `가격 통계` 링크로도 간다. 이 로컬 주소는 같은 PC에서만 열린다 — 카카오톡의 공개 링크로는 쓸 수 없다(아래 Tailscale Funnel 절차 필요).

Ctrl+C로 멈춘다. **이 서버가 꺼져 있으면 스캔도 되지 않는다.** 데이터베이스와 판정이 여기 있어서 `run-scan.bat`이 수집 결과를 넘길 곳이 없기 때문이다. 예전에는 스캔이 파일에 저장하고 끝나서 서버 없이도 돌았지만 지금은 그렇지 않다.

## 수집한 데이터 보기: Django admin

검색 조건을 고치거나 "이 매물이 왜 빠졌는지"를 확인하는 곳이다. 주소는 리포트와 같은 토큰 경로 아래에 있다.

```text
http://127.0.0.1:8000/r/<REPORT_PATH_TOKEN>/admin/
```

토큰을 따로 찾을 필요는 없다. `run-site` 창이 뜰 때 `Local admin:` 줄에 완성된 주소를 출력한다. 계정은 최초 설정에서 만든 슈퍼유저이며, 비밀번호를 잊었다면 재설정한다.

```powershell
cd report-site
..\real-estate-finder\.venv\Scripts\python.exe manage.py changepassword admin
```

화면별 쓰임새:

| 화면 | 무엇을 보는가 |
|---|---|
| Search condition | 단지, 가격 상한, 급매가, 전용면적, `notify_new`. 여기서 고치면 다음 스캔부터 적용된다 |
| Observation | 수집한 원본 전량. `exclusion_code` 필터로 조건에서 빠진 이유를 본다(가격/면적/타입/층/단지명) |
| Listing | 현재 매물 상태. `active` 필터, `first_seen_at`, `last_urgent_alert_price_won` |
| Scan | 실행 이력과 카카오 미전송 사유 |

admin은 Tailscale Funnel 공개 주소로도 열린다(같은 토큰 경로 + `/admin/`). 로그인 화면이 인터넷에 노출돼 있으므로 비밀번호는 강하게 둔다.

## 가격 통계 보기

주소는 리포트와 같은 토큰 경로 아래 `stats/`다. 리포트 헤더의 `가격 통계` 링크가 같은 곳으로 간다.

기간은 두 방법 중 하나로 고른다. **월**을 고르면 그 달 전체를 보고, **시작일/종료일**을 채우면 그 구간을 본다. 월이 우선한다. 아무것도 고르지 않으면 **최근 1개월**이다. 범위는 지역(전체/과천/광교) 또는 개별 단지로 좁히며, 기본값은 과천 전체다. 단지를 고르면 지역 선택보다 우선한다.

차트 한 칸이 하루다. 세로선이 그날의 최저~최고, 상자가 1분위~3분위, 붉은 가로선이 평균이다.

**표본이 5건 미만인 날은 1·3분위를 내지 않는다.** 상자 대신 위아래 끝선만 그리고 표에는 `–`를 넣는다. `method="inclusive"`는 1분위를 `(n-1)*0.25` 위치에 놓는데, 이 값이 실제 관측치 위에 정확히 떨어지는 최소 표본이 5건이다. 4건 이하에서는 이웃한 두 값 사이를 보간한 숫자가 나오며, 매물이 2건이면 1분위는 그저 "싼 쪽에서 25% 지점"이라 시세처럼 보이지만 시세가 아니다.

읽을 때 알아야 할 두 가지가 있다.

- **하루에 스캔이 여러 번 돈다.** 통계는 매물마다 그날 마지막 호가 하나만 세므로, 자주 조회된 매물이 분포를 끌고 가지 않는다.
- **모집단이 리포트보다 넓다.** 면적과 타입이 조건에 맞으면 조사 상한가를 넘겨도 분포에 들어간다. 상한가에서 자르면 최고가와 3분위가 시세가 아니라 예산을 나타내게 되기 때문이다. 그래서 표본 수는 리포트의 조건충족 건수보다 많은 것이 정상이다.

admin에서 조건의 면적이나 타입을 바꾸면 **과거 관측은 옛 기준으로 판정된 채 남아 있다.** 통계를 새 기준에 맞추려면 다시 판정한다.

```powershell
cd report-site
..\real-estate-finder\.venv\Scripts\python.exe manage.py reclassify_observations --dry-run
..\real-estate-finder\.venv\Scripts\python.exe manage.py reclassify_observations
```

## 카카오톡이 오지 않을 때

대부분 정상이다. 전송 조건은 둘뿐이다.

- **급매** — 유효 급매가 이하이고, 이전에 알린 적이 없거나 그때보다 더 내려간 경우
- **신규** — `notify_new`가 켜진 조건에서 처음 보는 매물. 현재 이 설정이 켜진 조건은 광교푸르지오월드마크 하나뿐이라, 과천 단지들은 신규 매물이 나와도 알리지 않는다

보내지 않은 이유는 항상 `run-scan` 창 마지막에 출력되고 admin의 `Scan.notification`에도 남는다. 조용히 끝나는 것과 실패를 구분할 수 있게 하려고 그렇게 만들었다. 급매가 아니어도 지금 전체를 받고 싶으면 `send-report.bat`을 실행한다.

## 외부에서 접속 가능하게 만들기: Tailscale Funnel (최초 1회)

카카오톡 메시지의 `통계 보기`·`전체 매물 보기` 버튼은 휴대전화에서도 열리는 고정 HTTPS 주소가 있어야 한다. 도메인을 사지 않고 이를 얻는 방법이 Tailscale Funnel이다.

1. [Tailscale for Windows](https://tailscale.com/download/windows)를 설치하고 로그인한다.
2. Tailscale 관리 콘솔에서 이 기기에 HTTPS 인증서와 Funnel을 켠다. 콘솔이나 CLI가 필요한 링크를 안내해준다.
3. `report-site\run-site.ps1`을 실행해 서버를 켜 둔 상태에서, 새 PowerShell 창을 열고:

   ```powershell
   tailscale funnel --bg 8000
   ```

   `https://<이 PC 이름>.<tailnet 이름>.ts.net` 형태의 주소가 출력된다. 이 주소는 PC를 재부팅해도 바뀌지 않는다. 상태 확인은 `tailscale funnel status`.

4. 카카오 개발자 콘솔 → 내 애플리케이션 → 플랫폼 → Web에 위 주소를 등록한다. 등록되지 않은 도메인은 카카오가 조용히 다른 주소로 치환할 수 있다.
5. 루트 `.env`(`.env.example`을 복사해 만든다)에 다음을 채운다.

   ```text
   KAKAO_REPORT_URL=https://<이 PC 이름>.<tailnet 이름>.ts.net/r/<report-site/.env의 REPORT_PATH_TOKEN>/
   ```

   `run-scan.ps1`, `send-report.ps1`, `report-site/run-site.ps1`이 `load-env.ps1`을 통해 이 값을 공유한다.

**주의할 제약**

- Tailscale Funnel은 공개 443/8443/10000 포트만 지원한다. `--bg 8000`은 공개 443을 로컬 8000으로 프록시하는 것이다.
- **`run-site.bat`이 실행 중이고 PC가 절전에 들어가지 않아야** 공개 주소가 응답한다. 자동 시작은 일부러 등록하지 않았으므로, 리포트를 외부에서 열어야 할 때 직접 켠다. 서버가 꺼져 있으면 카카오 메시지는 두 버튼을 조용히 빼고 텍스트만 보내므로 깨진 링크가 나가지는 않는다.
- 나중에 상시 공개로 바꾸고 싶으면 Windows 작업 스케줄러에 "로그온할 때" 트리거로 `report-site/run-site.ps1`을 등록하면 된다. Tailscale 서비스(`tailscaled`)는 별도 등록 없이 자동으로 뜨고, `funnel --bg` 설정도 재부팅 후 알아서 복구된다.
- 토큰 경로(`REPORT_PATH_TOKEN`)는 우발적 노출만 막는다. 주소 자체가 유출되면 인증 없이 누구나 리포트를 볼 수 있다.

## 리포트가 최신인지 확인하기

```powershell
cd report-site
..\real-estate-finder\.venv\Scripts\python.exe manage.py check_report
```

데이터베이스의 활성 매물 기준 시각과, `KAKAO_REPORT_URL`이 실제로 서빙 중인 시각을 비교해 출력한다. 리포트 서버나 Tailscale Funnel이 꺼져 있으면 실패로 끝난다(종료 코드 1). 이 명령은 확인 전용이며 아무것도 쓰거나 보내지 않는다.

## 현재 공개 리포트의 제한

- `run-site.bat`이 꺼져 있거나 PC가 절전/종료 상태면 공개 리포트 주소가 응답하지 않는다. 이 구조의 본질적 제약이다.
- 루트 `.env`의 `KAKAO_REPORT_URL`을 비우면 카카오 메시지가 이전에 쓰던 Codex Sites 주소로 폴백한다. 그 주소는 더 이상 갱신되지 않으므로 비우지 않는다.
- Django admin도 같은 공개 주소의 토큰 경로 아래에 있다(`.../admin/`). 로그인 화면이 인터넷에 열려 있는 셈이므로 관리자 비밀번호는 강해야 한다.
