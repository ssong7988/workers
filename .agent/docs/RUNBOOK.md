# 수동 실행 매뉴얼

## 메인 엔트리 포인트

에이전트 없이 매물을 한 번 조회하고 카카오톡으로 보내는 가장 간단한 방법은 다음 파일을 더블클릭하는 것이다.

```text
real-estate-finder\run-scan.bat
```

PowerShell에서 직접 실행하려면 저장소 루트에서 다음 명령을 사용한다.

```powershell
.\real-estate-finder\run-scan.ps1
```

스크립트는 아래 작업을 한 번에 수행한다.

1. 디버깅 포트 `9222`를 사용하는 전용 Edge 프로필을 실행한다.
2. 네이버 로그인 상태를 확인하고, 로그인이 필요하면 최대 5분 동안 기다린다.
3. `python -m real_estate_finder scan-once`로 매물을 조회한다.
4. 조건에 맞는 결과를 카카오톡으로 전송한다.

## 최초 한 번만 준비

PowerShell에서 다음 명령을 실행한다.

```powershell
cd real-estate-finder
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install msedge
Copy-Item config\searches.yaml config\searches.local.yaml
```

카카오톡 전송에는 `kakao-notifier/.env`와 `kakao-notifier/data/kakao-token.json`이 필요하다. 아직 없다면 `kakao-notifier/README.md`의 앱 등록과 최초 인증 절차를 먼저 수행한다. 비밀키와 토큰은 Git에 커밋하지 않는다.

## 자주 쓰는 개별 명령

`real-estate-finder/`에서 가상환경을 활성화한 뒤 실행한다.

```powershell
# 설정 확인
python -m real_estate_finder validate-config

# 정규 발송 이력을 소모하지 않는 시험 조회
python -m real_estate_finder smoke-test

# 한 번 조회하고 필요한 카카오 알림 전송
python -m real_estate_finder scan-once

# 저장된 현재 매물 전체 보고를 카카오톡으로 전송
python -m real_estate_finder send-digest
```

## 웹 화면을 로컬에서 보기

```powershell
cd property-report-site\site-app
.\run-local.ps1
```

브라우저에서 `http://127.0.0.1:3000`을 연다. 이 주소는 해당 PC에서만 접근할 수 있으므로 카카오톡의 공개 링크로 사용할 수 없다.

## Codex에서 UI 빌드·배포하기

현재 공개 리포트는 Codex Sites 프로젝트에 배포된다. UI 소스가 변경됐거나 `property-report-site/site-app/app/report-data.json`의 새 조회 결과를 공개해야 할 때만 빌드·배포한다. 단순 매물 조회 때마다 실행하지 않는다.

Codex에 아래처럼 요청하면 된다.

```text
.agent/PROJECT_STATE.md와 .agent/docs/RUNBOOK.md를 읽고,
property-report-site/site-app의 최신 report-data.json 기준으로 UI를 빌드한 뒤
기존 Codex Sites 프로젝트에 배포해줘.
배포 후 공개 사이트의 observedAt이 report-data.json과 같은지 검증해줘.
```

배포 후 전체 매물 링크가 포함된 카카오톡 카드까지 보내려면 마지막 줄을 추가한다.

```text
검증에 성공하면 저장된 전체 매물을 send-digest로 카카오톡에 보내줘.
```

Codex가 수행해야 하는 실제 순서는 다음과 같다.

1. `property-report-site/site-app/app/report-data.json`의 `observedAt`과 변경 내용을 확인한다.
2. `real-estate-finder/`에서 아래 명령으로 Codex Sites용 빌드를 만든다.

   ```powershell
   .\.venv\Scripts\python.exe -m real_estate_finder publish-report
   ```

   이 명령은 내부적으로 `property-report-site/site-app/`에서 `npm run build`를 실행하지만 배포까지 하지는 않는다.
3. `property-report-site/site-app/.openai/hosting.json`의 기존 `project_id`를 사용해 Codex Sites에 새 버전을 저장하고 배포한다.
4. 배포가 성공하면 `real-estate-finder/`에서 아래 명령으로 공개 페이지의 기준 시각을 검증한다.

   ```powershell
   .\.venv\Scripts\python.exe -m real_estate_finder publish-report --verify-only
   ```

5. 링크가 포함된 전체 결과를 다시 보낼 필요가 있으면 다음 명령을 실행한다.

   ```powershell
   .\.venv\Scripts\python.exe -m real_estate_finder send-digest
   ```

### 사람이 직접 할 수 있는 범위

에이전트 없이도 다음 명령으로 배포용 UI 빌드까지는 할 수 있다.

```powershell
cd property-report-site\site-app
npm run build
```

하지만 현재 저장소에는 Codex Sites 배포 전체를 대신하는 고정된 로컬 명령이 없다. 실제 버전 저장과 배포는 Codex의 Sites 기능을 사용해야 한다. `sites` Git remote에 임의로 직접 push하지 말고 위 요청문으로 Codex에 배포를 맡긴다.

## 현재 공개 리포트의 제한

매물 조회 스크립트는 UI를 자동 빌드하거나 Codex Sites에 배포하지 않는다. 새 조회 결과를 현재 공개 리포트 URL에 반영하려면 위 절차로 UI 빌드와 Codex Sites 재배포를 별도로 수행해야 한다. 호스팅된 데이터의 조회 시각이 최신 결과와 다르면 카카오 카드의 `전체 매물 보기` 버튼은 생략된다.

향후 PostgreSQL과 Django 웹 애플리케이션으로 전환하면, 조회 데이터가 데이터베이스에 저장되고 Django의 공개 URL에서 바로 조회되도록 이 절차를 대체한다.
