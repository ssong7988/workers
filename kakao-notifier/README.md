# Kakao Notifier

카카오 공식 REST API를 통해 인증된 사용자의 카카오톡 `나와의 채팅`으로
메시지를 보내는 작은 어댑터다. Python 표준 라이브러리만 사용한다.

현재 운영에서 메시지 내용, 급매·신규 여부, 전송 시점, 공개 링크 포함 여부는
`report-site/properties/`가 결정한다. 이 디렉터리는 다음 책임만 가진다.

- 최초 OAuth 인증과 토큰 파일 저장
- 만료된 액세스 토큰의 1회 자동 갱신
- 텍스트, 최대 2개 버튼, 호환용 이미지 메시지 API 호출
- 단독 연결 시험용 CLI

전체 시스템에서의 위치와 상세 동작은
[`../.docs/kakao-notifier/README.md`](../.docs/kakao-notifier/README.md)에서 시작한다.

## 최초 설정

1. Kakao Developers에서 앱을 만들고 카카오 로그인을 활성화한다.
2. 동의항목에서 `talk_message` 권한을 설정한다.
3. Redirect URI에 `http://localhost:4000/oauth/callback`을 등록한다.
4. 메시지 버튼이 여는 Tailscale Funnel 호스트를 `앱 > 제품 링크 관리 > 웹 도메인`에 등록한다. 등록되지 않은 링크는 오류 없이 앱 기본 도메인으로 치환될 수 있다.
5. 이 디렉터리에서 `.env.example`을 `.env`로 복사하고 실제 REST API 키와 클라이언트 시크릿을 채운다.

```powershell
cd kakao-notifier
Copy-Item .env.example .env
notepad .env
```

비밀값과 생성되는 `data/kakao-token.json`은 Git에 커밋하지 않는다.

## 최초 인증

반드시 이 디렉터리에서 실행한다.

```powershell
cd kakao-notifier
..\real-estate-finder\.venv\Scripts\python.exe auth.py
```

브라우저에서 로그인하고 메시지 전송 권한에 동의하면 로컬 콜백 서버가 인가
코드를 받아 `data/kakao-token.json`을 만든다. 자세한 흐름과 재인증 조건은
[`AUTH_AND_TOKENS.md`](../.docs/kakao-notifier/AUTH_AND_TOKENS.md)를 본다.

## 단독 연결 시험

아래 명령은 실제 카카오 메시지를 보낸다.

```powershell
cd kakao-notifier
..\real-estate-finder\.venv\Scripts\python.exe kakao_notifier.py "연결 테스트입니다."
```

정상 운영 발송은 이 CLI보다 `report-site`의 `send_digest`, `send_alert`, 스캔
API 경로를 사용한다. 그래야 공개 링크 최신성 검사와 실패 기록이 유지된다.

코드/API 설명은 [`API_AND_INTEGRATION.md`](../.docs/kakao-notifier/API_AND_INTEGRATION.md),
설치·점검·장애 대응은 [`OPERATIONS.md`](../.docs/kakao-notifier/OPERATIONS.md)를 본다.
