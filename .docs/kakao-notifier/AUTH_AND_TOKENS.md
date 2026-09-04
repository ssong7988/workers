# OAuth와 토큰 수명주기

## 최초 인증에 필요한 설정

Kakao Developers 앱에서 카카오 로그인을 활성화하고 `talk_message` 동의항목을
설정한다. 코드의 기본 Redirect URI는 다음과 같다.

```text
http://localhost:4000/oauth/callback
```

개발자 콘솔에 등록한 값과 `KAKAO_REDIRECT_URI`가 문자 단위로 같아야 한다.
`auth.py`는 보안을 위해 콜백 호스트가 `localhost` 또는 `127.0.0.1`이 아니면
실행을 거부한다.

설정 파일은 `kakao-notifier/.env.example`을 복사해 만든다.

```env
KAKAO_REST_API_KEY=<REST API 키>
KAKAO_CLIENT_SECRET=<클라이언트 시크릿>
KAKAO_REDIRECT_URI=http://localhost:4000/oauth/callback
KAKAO_TOKEN_FILE=data/kakao-token.json
```

실제 값은 Git과 문서에 기록하지 않는다. `KAKAO_TOKEN_FILE`을 상대 경로로
둘 때 `auth.py`는 현재 작업 디렉터리를 기준으로 해석하므로 반드시
`kakao-notifier/`에서 실행한다.

## `auth.py` 실행 흐름

1. `.env`를 읽고 REST API 키와 클라이언트 시크릿이 있는지 검사한다.
2. 예측하기 어려운 OAuth `state` 값을 생성한다.
3. Redirect URI의 포트에 `HTTPServer`를 `127.0.0.1`로 연다.
4. `scope=talk_message`가 포함된 카카오 인가 URL을 기본 브라우저로 연다.
5. 콜백 한 건을 기다리고 `state`, `error`, `code`를 검증한다.
6. 인가 코드를 `https://kauth.kakao.com/oauth/token`에 전송한다.
7. 성공 payload 전체를 UTF-8 JSON으로 토큰 파일에 저장한다.

`state`가 다르거나 사용자가 동의를 취소했거나 인가 코드가 없으면 토큰 교환을
하지 않고 실패한다. 로컬 HTTP 서버는 요청 한 건을 처리한 뒤 닫힌다.

## 평상시 액세스 토큰 사용

모든 메시지 API 호출은 `_with_token_retry()`를 지난다.

```text
토큰 파일 읽기
  -> access_token으로 API 1회 호출
  -> 200이면 결과 반환
  -> 401이면 refresh_token으로 갱신
  -> 새 access_token으로 같은 API 1회 재시도
  -> 그 외 상태 또는 재시도 실패는 예외
```

401일 때만 자동 갱신한다. 권한 부족, 잘못된 템플릿, 등록되지 않은 설정처럼
다른 원인의 오류에 무의미한 갱신을 반복하지 않는다.

## 리프레시 토큰 갱신

`refresh_access_token()`은 기존 토큰 객체를 다음처럼 갱신한다.

- `access_token`과 `expires_in`은 새 응답으로 교체한다.
- 카카오가 새 `refresh_token`을 반환한 경우에만 기존 값을 교체한다.
- 새 리프레시 토큰이 있으면 `refresh_token_expires_in`도 함께 저장한다.
- 갱신된 JSON은 같은 토큰 파일에 다시 기록한다.

응답에 새 리프레시 토큰이 없다고 기존 값을 지우면 안 된다. 카카오가 매번 새
리프레시 토큰을 주는 것은 아니기 때문이다.

## 재인증이 필요한 경우

다음 경우에는 자동 복구가 불가능하므로 `auth.py`를 다시 실행한다.

- 토큰 파일이 없음
- JSON이 손상됨
- `refresh_token`이 없음
- 리프레시 토큰이 만료됨
- 사용자가 앱 연결 또는 메시지 동의를 해제함
- 앱 키/시크릿을 교체함

재인증은 토큰 파일을 덮어쓰는 외부 계정 작업이다. 자동화 에이전트가 임의로
실행하지 않고 사용자가 브라우저에서 동의 내용을 확인한다.

## 보안 주의사항

- 토큰 파일은 비밀번호와 같은 비밀정보다. 채팅이나 이슈에 붙이지 않는다.
- 오류를 공유할 때 카카오 응답 전체에 토큰이 포함되지 않았는지 먼저 확인한다.
- `.env`와 `data/kakao-token.json`은 현재 `.gitignore`로 제외된다.
- 토큰 값을 테스트 fixture에 복사하지 않는다. HTTP 호출을 mock 처리한다.
- 로컬 콜백 포트를 다른 프로세스가 점유하면 인증이 시작되지 않는다. 점유
  프로세스를 확인한 뒤 종료하거나 Redirect URI와 콘솔 등록값을 함께 바꾼다.
