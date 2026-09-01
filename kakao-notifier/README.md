# 카카오톡 나에게 보내기 테스트

카카오 공식 REST API를 이용해 본인의 카카오톡 `나와의 채팅`으로 메시지를 보냅니다.

## 1. 카카오 개발자 앱 설정

1. [Kakao Developers](https://developers.kakao.com/)에 로그인합니다.
2. **앱**에서 새 앱을 생성합니다.
3. 앱의 **카카오 로그인 > 일반**에서 카카오 로그인을 활성화합니다.
4. **카카오 로그인 > 동의항목**에서 `카카오톡 메시지 전송`(`talk_message`)을 설정합니다.
5. **앱 > 플랫폼 키 > REST API 키**로 이동합니다.
6. Redirect URI에 아래 주소를 정확히 등록합니다.

   ```text
   http://localhost:4000/oauth/callback
   ```

7. 같은 화면에서 REST API 키와 클라이언트 시크릿을 확인합니다.
8. **앱 > 제품 링크 관리 > 웹 도메인**에 테스트 메시지 링크로 사용할 아래 도메인을 등록합니다.

   ```text
   https://developers.kakao.com
   ```

> 카카오 개발자 화면은 2025년 12월 개편 이후 Redirect URI와 클라이언트 시크릿이 REST API 키 설정 아래에 있습니다.

## 2. 로컬 실행 준비

PowerShell에서 프로젝트 폴더로 이동한 다음 실행합니다.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
notepad .env
```

`.env`에 카카오 개발자 화면에서 확인한 값을 입력합니다.

```env
KAKAO_REST_API_KEY=실제_REST_API_키
KAKAO_CLIENT_SECRET=실제_클라이언트_시크릿
KAKAO_REDIRECT_URI=http://localhost:4000/oauth/callback
KAKAO_TOKEN_FILE=data/kakao-token.json
```

키와 토큰은 채팅, GitHub 또는 공개 저장소에 올리지 마세요.

## 3. 최초 1회 사용자 인증

```powershell
python auth.py
```

브라우저에서 카카오 로그인 후 메시지 전송 권한에 동의합니다. 성공하면 `data/kakao-token.json`이 생성됩니다.

## 4. 테스트 메시지 전송

```powershell
python kakao_notifier.py
```

원하는 메시지도 보낼 수 있습니다.

```powershell
python kakao_notifier.py "오늘의 포트폴리오 테스트입니다."
```

메시지는 본인의 카카오톡 **나와의 채팅**에 도착합니다.

## 토큰 관리

REST API 액세스 토큰이 만료되어 전송 요청이 `401`을 반환하면 프로그램이 리프레시 토큰으로 한 번 갱신하고 재전송합니다. 카카오가 새로운 리프레시 토큰도 반환하면 토큰 파일에 함께 반영합니다.

리프레시 토큰까지 만료되거나 사용자가 앱 연결을 해제했다면 `python auth.py`로 다시 인증해야 합니다.
