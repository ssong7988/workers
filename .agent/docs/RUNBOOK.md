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

## 현재 공개 리포트의 제한

매물 조회 스크립트는 UI를 자동 빌드하거나 Codex Sites에 배포하지 않는다. 새 조회 결과를 현재 공개 리포트 URL에 반영하려면 UI 빌드와 Codex Sites 재배포를 별도로 수행해야 한다. 호스팅된 데이터의 조회 시각이 최신 결과와 다르면 카카오 카드의 `전체 매물 보기` 버튼은 생략된다.

향후 PostgreSQL과 Django 웹 애플리케이션으로 전환하면, 조회 데이터가 데이터베이스에 저장되고 Django의 공개 URL에서 바로 조회되도록 이 절차를 대체한다.
