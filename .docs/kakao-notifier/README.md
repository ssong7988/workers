# kakao-notifier 상세 가이드

`kakao-notifier/`는 카카오 OAuth와 REST API 호출만 담당하는 독립 어댑터다.
현재 애플리케이션에서 “무엇을 언제 누구에게 보낼지”는
`report-site/properties/`가 결정하고, 이 모듈은 이미 결정된 텍스트와 링크를
카카오 `나와의 채팅` API에 전달한다.

## 역할 경계

```text
report-site/properties/scanning.py
        |  급매·신규 후보와 DB 상태 결정
        v
report-site/properties/delivery.py
        |  메시지 본문, 버튼, 전송 시점, 실패 기록 결정
        v
report-site/properties/notifier.py
        |  kakao-notifier를 동적으로 로드하는 어댑터
        v
kakao-notifier/kakao_notifier.py
        |  토큰 로드/갱신 + Kakao REST API 호출
        v
카카오톡 나와의 채팅
```

다음 책임은 이 디렉터리에 두지 않는다.

- 급매·신규 판정
- 발송 대상 매물 선택과 중복 알림 방지
- PostgreSQL 상태 변경
- 통계/리포트 URL의 최신성 판정
- `NotificationFailure` 기록

이 책임은 모두 `report-site/properties/`에 있다. 반대로 카카오 OAuth 엔드포인트,
토큰 파일 형식, 401 갱신 재시도와 메시지 API 직렬화는 `kakao-notifier/`가
소유한다.

## 코드 지도

| 파일 | 책임 | 주로 확인할 때 |
|---|---|---|
| `auth.py` | 브라우저 OAuth, 로컬 콜백, 인가 코드 교환, 최초 토큰 저장 | 첫 설치, 동의 취소, 리프레시 토큰 만료 |
| `kakao_notifier.py` | 토큰 갱신, 템플릿 직렬화, 텍스트/버튼/이미지 전송, 단독 CLI | 전송 포맷, 401, 카카오 API 오류 |
| `common.py` | `.env` 로딩, form/multipart POST, JSON/HTTP 오류 응답 정규화 | 네트워크 요청이나 업로드 문제 |
| `test_kakao_notifier.py` | 이미지 링크와 버튼 계약의 단위 테스트 | 호환용 이미지 경로 수정 |
| `.env.example` | 비밀값 없는 설정 키 목록 | 최초 설정 |
| `.gitignore` | `.env`, venv, 토큰 파일 제외 | 비밀정보 추적 여부 확인 |

`requirements.txt`에 외부 패키지가 없는 것은 의도적이다. HTTP, OAuth 콜백
서버, URL 인코딩, multipart 생성까지 Python 표준 라이브러리로 처리한다.

## 현재 운영 경로

현재 리포트 발송은 이미지 카드가 아니다. `DeliveryService`가 200자 이내
텍스트 한 통을 만들고, 공개 리포트가 현재 DB 시각을 서빙하는 경우에만
`통계 보기`와 `전체 매물 보기` 버튼을 붙인다. 공개 사이트가 없거나 오래된
데이터를 서빙하면 버튼 없이 텍스트만 보낸다.

`kakao_notifier.py`의 이미지 업로드와 feed 템플릿 함수는 단독 호환 API로
남아 있지만 `report-site`의 현재 전송 경로에서는 호출하지 않는다. 새 기능을
만들 때 이 코드를 현 운영 방식으로 오인하지 않는다.

## 설정의 위치

| 위치 | 값 | 소비자 |
|---|---|---|
| `kakao-notifier/.env` | `KAKAO_REST_API_KEY`, `KAKAO_CLIENT_SECRET`, `KAKAO_REDIRECT_URI`, `KAKAO_TOKEN_FILE` | `auth.py`, `kakao_notifier.py` |
| `kakao-notifier/data/kakao-token.json` | 액세스/리프레시 토큰 | `kakao_notifier.py` |
| 루트 `.env` | `KAKAO_REPORT_URL` | 실행 스크립트, Django 설정, 카카오 링크 |
| `report-site/.env` | Django/API/DB 설정 | `report-site` |

`.env` 로더는 이미 존재하는 프로세스 환경변수를 덮어쓰지 않는다. 따라서
Django에서 동적으로 로드할 때는 실행 프로세스에 먼저 들어온 값이 우선하고,
단독 CLI에서는 `kakao-notifier/.env` 값이 사용된다.

## 상세 문서

- [OAuth와 토큰 수명주기](AUTH_AND_TOKENS.md)
- [메시지 API와 Django 연동](API_AND_INTEGRATION.md)
- [설치, 점검과 장애 대응](OPERATIONS.md)
- [프로젝트 전체 운영 매뉴얼](../RUNBOOK.md)
- [전체 아키텍처](../ARCHITECTURE.md)

## 반드시 지킬 불변 조건

- 키, 시크릿, 토큰 파일 내용을 문서·로그·Git에 남기지 않는다.
- 401 외 오류를 토큰 갱신으로 덮지 않는다. 갱신은 한 번만 시도한다.
- 텍스트 본문은 200자를 넘기지 않는다.
- 다중 버튼은 1~2개만 허용한다.
- 카카오 버튼의 도메인은 개발자 콘솔 허용 목록과 일치해야 한다.
- 운영 메시지는 가능하면 Django 경로로 보낸다. 그래야 링크 최신성 검사,
  전송 결과 기록, `NotificationFailure` 저장이 유지된다.
