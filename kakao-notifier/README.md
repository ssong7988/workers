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
8. **앱 > 제품 링크 관리 > 웹 도메인**에 메시지 버튼이 열 도메인을 모두 등록합니다. `웹 도메인 수정`을 누르고 입력한 뒤 저장하며, 여러 개는 `+` 버튼으로 추가합니다.

   ```text
   https://k.kakaocdn.net                                       # 카드 원본 이미지
   https://my-property-report-20260902.ssong7988.chatgpt.site    # 매물 리포트
   ```

   > **이 등록을 빠뜨리면 버튼이 엉뚱한 곳으로 갑니다.** 카카오는 위변조 방지를 위해 등록되지 않은 도메인을 앱의 기본 도메인으로 바꿔버립니다. 에러가 나지 않고 조용히 대체되므로 원인을 찾기 어렵습니다. 예전 설정에서 `https://developers.kakao.com`만 등록해 두면 모든 버튼이 카카오 개발자 사이트로 이동합니다. ([관련 데브톡](https://devtalk.kakao.com/t/weburl/147754))
   >
   > 여기서 "도메인 등록"은 DNS 설정이나 도메인 구입과 무관합니다. 카카오가 앱별로 들고 있는 허용 목록에 주소를 적어 넣는 것뿐이며, 소유권 증명 절차도 없습니다.

> 카카오 개발자 화면은 2025년 12월 개편 이후 Redirect URI와 클라이언트 시크릿이 REST API 키 설정 아래에 있습니다.
> `제품 링크 관리 > 웹 도메인`은 `플랫폼 > Web 사이트 도메인`과 다른 메뉴입니다. 버튼 링크에 관여하는 쪽은 전자입니다.

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

## 5. 이미지 카드 전송

기본 텍스트 템플릿은 **200자**를 넘길 수 없어 매물이 많으면 내용이 잘립니다. 매물 목록은 이미지 한 장으로 렌더링해 `feed` 템플릿으로 보냅니다.

```powershell
python kakao_notifier.py --image ..\real-estate-finder\data\cards\card.png "🏠 매물 알림 22건 · 급매 4" --description "최저 21억 5,000만 · 과천위버필드 외 4단지"
```

동작 순서는 이렇습니다.

1. `upload_image()`가 이미지를 카카오에 업로드하고 `infos.original.url`을 받습니다. 카카오는 이 주소를 `http://`로 주는데, 도메인 등록이 `https://` 단위이므로 스킴을 https로 맞춥니다(두 스킴 모두 같은 이미지를 서빙합니다).
2. `send_image_to_me()`가 그 URL로 `feed` 템플릿을 전송합니다. 응답이 알려준 width/height를 그대로 넘겨 비율이 유지됩니다.

`feed` 템플릿의 제목·설명도 자체 길이 제한이 있어 180자로 자릅니다. 상세 정보는 이미지가 전달하므로 제목에는 요약만 담습니다.

### 버튼은 원본 이미지로 연결됩니다

`link_url`을 주지 않으면 카드와 `원본 이미지 보기` 버튼이 **업로드된 원본 이미지 자체**를 엽니다. 채팅방에 보이는 카드는 축소본이라, 전체 해상도(예: 1080×4992)로 보려면 원본을 열어야 하기 때문입니다.

다른 곳으로 보내려면 `--link`를 지정합니다. 이때 버튼 문구는 `전체 매물 보기`로 바뀝니다.

```powershell
python kakao_notifier.py --image card.png "제목" --link https://my-property-report-20260902.ssong7988.chatgpt.site
```

**어떤 주소를 쓰든 그 도메인이 `앱 > 제품 링크 관리 > 웹 도메인`에 등록돼 있어야 합니다** (위 1번 항목 참고). 등록되지 않으면 에러 없이 앱 기본 도메인으로 바뀝니다.

### 업로드 API 확인

업로드 엔드포인트만 호출하고 응답을 그대로 출력합니다. 앱 권한 문제를 진단할 때 씁니다.

```powershell
python kakao_notifier.py --upload-probe some-image.png
```

확인된 동작: `talk_message` 권한만으로 업로드가 되며, 1080×4992 / 341KB PNG도 통과했습니다.

### 업로드 실패 시 폴백 (선택)

`.env`에 `KAKAO_IMAGE_BASE_URL`을 넣어두면 업로드가 실패했을 때 그 주소 아래의 공개 URL(`{BASE}/{파일명}`)로 대신 전송합니다.

```env
KAKAO_IMAGE_BASE_URL=https://my-property-report-20260902.ssong7988.chatgpt.site
```

## 토큰 관리

REST API 액세스 토큰이 만료되어 전송 요청이 `401`을 반환하면 프로그램이 리프레시 토큰으로 한 번 갱신하고 재전송합니다. 카카오가 새로운 리프레시 토큰도 반환하면 토큰 파일에 함께 반영합니다.

리프레시 토큰까지 만료되거나 사용자가 앱 연결을 해제했다면 `python auth.py`로 다시 인증해야 합니다.
