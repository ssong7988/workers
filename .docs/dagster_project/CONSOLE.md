# Dagster console 연결 구조

## 결론부터 보기

현재 공개 호스트에서 두 화면은 서로 다른 서버가 만든다.

| 공개 경로 | 실제 처리자 | 용도 | 인증 |
|---|---|---|---|
| `/dagster/` | Django, `127.0.0.1:8000` | 최근 실행을 간단히 보여주는 프로젝트 전용 요약 | Django staff 로그인 |
| `/dagster/console/` | Dagster, `127.0.0.1:3000` | Dagster가 제공하는 전체 UI, 로그와 수동 실행 | 현재 별도 인증 없음 |

`console`은 “원본(raw) 응답”이 아니라 사람이 조작하는 완전한 운영 UI이므로
`raw`보다 역할을 잘 드러내는 이름으로 선택했다.

## 브라우저 요청이 어디로 가는가

현재 Tailscale Funnel 설정은 다음과 같다.

```text
https://desktop-477.tailf8d9d1.ts.net (Funnel on)
|-- /                proxy http://127.0.0.1:8000
|-- /dagster/console proxy http://127.0.0.1:3000/dagster/console
```

Funnel은 더 구체적인 `/dagster/console` 규칙을 먼저 적용한다.

```text
GET https://.../dagster/
  -> Funnel의 / 규칙
  -> Django :8000
  -> staff_member_required
  -> 프로젝트 전용 요약 HTML

GET https://.../dagster/console/runs
  -> Funnel의 /dagster/console 규칙
  -> Dagster :3000/dagster/console/runs
  -> Dagster 네이티브 UI
```

두 경로가 비슷해 보여도 `/dagster/console/` 요청은 Django를 전혀 지나지
않는다. 그래서 Django의 로그인 장식자도 적용되지 않는다.

## Dagster 자체에도 같은 prefix가 필요한 이유

프록시 규칙만 `/dagster/console`로 잡고 Dagster를 `/` 기준으로 실행하면
첫 HTML은 보일 수 있어도 JS, CSS, GraphQL 요청이 `/assets/...` 또는
`/graphql`로 생성돼 다른 서버로 빠질 수 있다.

`run-dagster.ps1`은 이를 막기 위해 다음 환경변수를 설정한다.

```powershell
$env:DAGSTER_WEBSERVER_PATH_PREFIX = '/dagster/console'
```

그러면 Dagster가 모든 내부 URL을 이 prefix 아래에 만든다.

```text
/dagster/console/runs
/dagster/console/graphql
/dagster/console/assets/...
```

즉, 아래 세 값은 항상 같은 prefix여야 한다.

1. 브라우저가 사용하는 공개 경로
2. Tailscale Funnel의 `--set-path`와 프록시 대상 경로
3. Dagster의 `DAGSTER_WEBSERVER_PATH_PREFIX`

현재 Funnel 등록 명령은 다음 형태다.

```powershell
tailscale funnel --https=443 --set-path=/dagster/console --bg http://127.0.0.1:3000/dagster/console
```

Windows에서 `tailscale`이 PATH에 없다면 실행 파일의 전체 경로를 쓴다.

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' funnel status
```

## Django 요약 화면은 어떻게 Dagster 상태를 읽는가

Django의 `/dagster/`는 네이티브 UI를 iframe으로 감싼 화면이 아니다.
`report-site/report/dagster_client.py`가 서버 내부에서 다음 로컬 GraphQL로
최근 run을 조회하고 별도 HTML을 렌더링한다.

```text
http://127.0.0.1:3000/dagster/console/graphql
```

흐름은 다음과 같다.

```text
사용자 -> /dagster/ -> Django view
                         |
                         `-> 로컬 Dagster GraphQL -> 최근 run JSON
                         |
                         `-> report/dagster.html 렌더링
```

이 조회는 읽기 전용이다. 요약 화면에서는 run을 시작하거나 중단하지 못하며,
실제 조작은 네이티브 console에서 한다. Dagster GraphQL 스키마 중 상대적으로
단순한 `runsOrError`만 사용하고, 스케줄 설명은 `definitions.py`와 맞춘 정적
요약을 사용한다.

## 선택 경로 토큰을 켤 때

`report-site/.env`의 값이 비어 있으면 현재 경로를 사용한다.

```text
REPORT_PATH_TOKEN=
/dagster/
/dagster/console/
```

예를 들어 값을 `example-token`으로 바꾸면 코드가 다음 경로를 계산한다.

```text
/example-token/dagster/
/example-token/dagster/console/
```

이때 다음을 한 세트로 바꿔야 한다.

1. `report-site/.env`의 `REPORT_PATH_TOKEN`
2. 루트 `.env`의 `KAKAO_REPORT_URL`
3. Funnel의 console mount 경로와 대상 경로
4. report-site와 Dagster 프로세스 재시작

토큰을 문서나 Git에 실제 값으로 남기지 않는다.

## 중요한 보안 경계

`/dagster/` 요약은 Django staff 로그인을 요구하지만, 현재
`/dagster/console/`은 Funnel이 Dagster에 직접 연결하므로 Django 인증을
우회한다. Dagster console에서는 수집과 카카오 발송을 포함한 job을 수동으로
실행할 수 있다.

현재처럼 토큰도 비어 있고 Funnel을 사용하는 구성에서는 URL을 아는 외부
사용자가 console에 접근할 수 있다. 운영 편의보다 접근 제한이 중요해지면
console을 Funnel에서 제거하고 Tailscale 사설망의 Serve로만 열거나, 인증을
제공하는 별도 reverse proxy 뒤에 두어야 한다.

## 연결 확인

```powershell
# 1. 로컬 Dagster UI
Invoke-WebRequest http://127.0.0.1:3000/dagster/console/runs -UseBasicParsing

# 2. Funnel 규칙
& 'C:\Program Files\Tailscale\tailscale.exe' funnel status

# 3. 공개 UI
Invoke-WebRequest https://desktop-477.tailf8d9d1.ts.net/dagster/console/runs -UseBasicParsing

# 4. Django 요약은 비로그인 요청이면 admin 로그인으로 302가 정상
curl.exe -I https://desktop-477.tailf8d9d1.ts.net/dagster/
```

