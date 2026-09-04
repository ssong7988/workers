# 설치, 점검과 장애 대응

## 전제 조건

- Kakao Developers 앱과 REST API 키
- 카카오 로그인 활성화와 `talk_message` 동의항목
- 등록된 Redirect URI
- 메시지 링크 호스트가 등록된 제품 링크 관리의 웹 도메인
- 프로젝트 공유 Python (`real-estate-finder/.venv`)

외부 Python 패키지는 없다. `requirements.txt`는 표준 라이브러리만 쓴다는
사실을 명시하는 파일이다.

## 최초 준비

```powershell
cd kakao-notifier
Copy-Item .env.example .env
notepad .env
```

필수값은 `KAKAO_REST_API_KEY`, `KAKAO_CLIENT_SECRET`이다. Redirect URI와
토큰 경로는 기본값을 그대로 쓸 수 있다. `KAKAO_IMAGE_BASE_URL`은 현재 운영
경로에 필요하지 않으며 호환용 이미지 업로드 폴백을 쓸 때만 채운다.

최초 인증:

```powershell
..\real-estate-finder\.venv\Scripts\python.exe auth.py
```

성공 기준은 브라우저 동의 완료와 `data/kakao-token.json` 생성이다. 파일 내용을
콘솔에 출력하거나 공유하지 않는다.

## 부작용 없는 자동 검증

```powershell
cd kakao-notifier
..\real-estate-finder\.venv\Scripts\python.exe -m unittest -v test_kakao_notifier.py
```

현재 테스트는 `_send_template`을 mock하여 이미지 메시지의 링크/버튼 구성을
검사한다. 실제 네트워크 요청, 토큰 갱신, 메시지 발송은 하지 않는다.

문법과 import만 빠르게 확인하려면 다음을 사용할 수 있다.

```powershell
..\real-estate-finder\.venv\Scripts\python.exe -m py_compile auth.py common.py kakao_notifier.py
```

## 실제 연결 시험

아래 명령은 `나와의 채팅`에 실제 메시지 한 통을 보낸다. 사용자 확인 없이
자동 검증으로 실행하지 않는다.

```powershell
cd kakao-notifier
..\real-estate-finder\.venv\Scripts\python.exe kakao_notifier.py "카카오 연결 테스트"
```

운영 전체 보고는 단독 CLI 대신 다음 경로를 쓴다.

```powershell
cd report-site
..\real-estate-finder\.venv\Scripts\python.exe manage.py send_digest
```

이 경로는 PostgreSQL의 활성 매물, 공개 리포트 최신성, 버튼 정책과 실패 기록을
모두 적용한다. `real-estate-finder/send-report.bat`도 같은 관리 명령을 감싼다.

## 자주 발생하는 문제

| 증상 | 먼저 확인할 것 | 조치 |
|---|---|---|
| `토큰 파일이 없습니다` | `kakao-notifier/data/kakao-token.json` 존재 | 해당 디렉터리에서 `auth.py` 재실행 |
| REST API 키/시크릿 오류 | `kakao-notifier/.env` 필수값 | 개발자 콘솔 값과 맞추되 값을 로그에 출력하지 않음 |
| 토큰 갱신 실패 | 리프레시 토큰 만료/앱 연결 해제 | 브라우저 최초 인증 재실행 |
| 콜백 서버를 열 수 없음 | 로컬 4000 포트 점유 | 점유 프로세스를 확인하거나 Redirect URI/콘솔 값을 함께 변경 |
| 메시지 401 후에도 실패 | 앱 키, 동의 상태, 리프레시 토큰 | 재인증 후 단독 연결 시험 |
| 메시지는 왔지만 버튼이 다른 곳으로 이동 | 제품 링크 관리의 웹 도메인 | Funnel 호스트 등록 후 휴대전화에서 재확인 |
| 메시지에 버튼이 없음 | 공개 사이트가 꺼졌거나 DB 기준 시각과 불일치 | `manage.py check_report`, `run-site.bat`, Funnel 상태 확인 |
| 본문 200자 오류 | 호출자가 길이 제한을 지키지 않음 | Django의 포맷터를 사용하거나 전송 전 축약 |
| 이미지 업로드 실패 | 파일, 권한, 응답 payload | 현재 운영은 이미지 미사용; 호환 기능이면 `--upload-probe`를 사용자 승인 후 실행 |
| `NotificationFailure` 생성 | 카카오/네트워크 실제 실패 | admin에서 오류를 확인하고 원인 해결 후 필요한 메시지만 재전송 |

## 버튼이 빠지는 것은 정상일 수 있다

`DeliveryService._buttons()`는 다음 조건을 모두 만족해야 버튼을 만든다.

1. 보낼 매물이 하나 이상 있다.
2. `KAKAO_REPORT_URL`이 설정돼 있다.
3. HTTPS이며 localhost/loopback 주소가 아니다.
4. 공개 URL의 `data-observed-at`이 보낼 매물 중 최신 관측 시각과 같다.

하나라도 실패하면 깨진 링크를 보내지 않고 텍스트만 전송한다. 카카오 API나
토큰 문제와 구분하려면 `manage.py check_report`로 공개 사이트 상태를 먼저
확인한다.

## 변경 체크리스트

- OAuth/토큰 변경: `auth.py`, `refresh_access_token()`, 토큰 보존 규칙 확인
- 템플릿 변경: 200자 제한, 버튼 2개 제한, 등록 도메인 확인
- 운영 본문/대상 변경: `report-site/properties/delivery.py`와 테스트 수정
- 공개 링크 변경: 루트 `.env`, Tailscale Funnel, Kakao 웹 도메인을 함께 수정
- 실패 처리 변경: `NotificationFailure`와 `Scan.notification` 계약 유지
- 코드 수정 뒤 Django 경로에 영향이 있으면 `report-site/run-site.bat` 재시작

실제 인증, 토큰 갱신, 메시지 전송은 외부 상태를 바꾸므로 대상과 결과를
확인한 뒤 수행한다.
