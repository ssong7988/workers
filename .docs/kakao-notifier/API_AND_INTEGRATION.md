# 메시지 API와 Django 연동

## 공통 HTTP 계층

`common.py`는 두 POST 형식을 제공한다.

| 함수 | Content-Type | 사용처 |
|---|---|---|
| `post_form_json()` | `application/x-www-form-urlencoded` | 토큰 발급/갱신, 메시지 템플릿 전송 |
| `post_multipart_json()` | `multipart/form-data` | 이미지 업로드 |

HTTP 성공과 `HTTPError` 모두 `(status, JSON payload)` 형태로 정규화한다. 오류
본문이 JSON이 아니면 `message` 필드로 감싼다. 연결 오류는 잡지 않으므로
호출자까지 올라가고, Django 경로에서는 `DeliveryService`가 이를 기록한다.

multipart 구현은 단순성과 안전성을 위해 업로드 파일명을 ASCII로 제한한다.
원본 파일명이 한글이어도 `_image_parts()`가 `card.png` 또는 `card.jpg`로 바꿔
전송한다.

## 텍스트 전송 API

### `send_to_me(message, link_url)`

카카오 기본 text 템플릿 한 통을 보낸다.

- 본문 200자 초과 시 API 호출 전에 `ValueError`
- 말풍선 링크와 `전체 매물 보기` 단일 버튼 사용
- 기본 링크는 모듈 로드 시 읽은 `KAKAO_REPORT_URL`

### `send_links_to_me(message, buttons)`

현재 Django 운영 경로가 주로 호출하는 함수다.

- 본문은 최대 200자
- 버튼은 최소 1개, 최대 2개
- 각 버튼은 제목과 URL의 튜플
- 첫 버튼 URL을 말풍선 자체 링크에도 사용
- web/mobile URL은 같은 값으로 직렬화

카카오 개발자 콘솔의 `앱 > 제품 링크 관리 > 웹 도메인`에 없는 도메인은
카카오가 에러 대신 앱 기본 도메인으로 조용히 바꿀 수 있다. 전송 성공 여부만
보고 링크가 맞다고 판단하지 말고, 도메인을 바꾼 뒤에는 휴대전화에서 버튼을
실제로 확인한다.

## 이미지 API는 호환 경로다

`probe_image_upload()`, `upload_image()`, `send_image_to_me()`,
`send_card_to_me()`는 여전히 독립적으로 사용할 수 있다.

1. JPEG/PNG를 카카오 이미지 업로드 API에 multipart로 보낸다.
2. 응답의 `infos.original` URL과 크기를 읽는다.
3. 카카오가 `http://` URL을 주면 등록 도메인과 맞도록 `https://`로 바꾼다.
4. feed 템플릿에서 이미지와 첫 버튼은 원본 이미지로 연결한다.
5. `link_url`이 있으면 `전체 매물 보기` 두 번째 버튼을 붙인다.
6. 업로드 실패 시 `KAKAO_IMAGE_BASE_URL`이 설정된 경우에만 공개 파일 URL로
   대체한다. 설정이 없으면 원래 오류를 올린다.

제목과 설명은 각각 180자로 자른다. 현재 `report-site`는 이 이미지 경로를
사용하지 않으며 텍스트 + 링크 버튼만 보낸다. 이미지 코드를 변경해도 현재
운영 리포트가 바뀌었다고 간주하면 안 된다.

## Django 동적 로딩

`report-site/properties/notifier.py`의 `KakaoNotifier`는 이 디렉터리를 Python
패키지 의존성으로 설치하지 않는다. 대신 `kakao_notifier.py` 경로를
`importlib.util.spec_from_file_location()`으로 읽고, 로드하는 동안만 디렉터리를
`sys.path` 앞에 넣어 `common.py` import를 해결한다.

운영 호출은 두 개뿐이다.

| Django 메서드 | 여기서 호출하는 함수 |
|---|---|
| `KakaoNotifier.send(message, link_url)` | `send_to_me()` |
| `KakaoNotifier.send_links(message, buttons)` | `send_links_to_me()` |

테스트에서는 `sender`와 `links_sender` 콜백을 주입해 실제 카카오 API를 부르지
않는다. 동적 import를 피하면서 메시지 계약만 검증할 수 있다.

## `DeliveryService`가 소유하는 정책

카카오 모듈을 직접 고치기 전에 다음 정책은 Django 쪽임을 확인한다.

- 메시지 본문과 통계 한 줄 구성
- 200자 예산 안에서 남은 매물을 `외 N건`으로 접는 규칙
- 급매/신규 이모지와 대상 선택
- 공개 리포트의 `data-observed-at`이 현재 매물 시각과 일치하는지 확인
- 최신일 때만 `통계 보기`, `전체 매물 보기` 버튼 추가
- 전송 실패 시 `NotificationFailure` 생성과 `Scan.notification` 갱신
- Dagster/Airflow 오류의 `⚠️ ` 접두사와 길이 제한

따라서 버튼을 항상 붙이거나 알림 대상을 바꾸는 작업은
`kakao-notifier.py`가 아니라 `report-site/properties/delivery.py`에서 한다.

## 실패 전파

```text
카카오/네트워크 예외
  -> KakaoNotifier가 호출자에게 예외 전달
  -> DeliveryService가 NotificationFailure 저장
  -> Scan 연관 전송이면 Scan.notification도 실패 사유로 갱신
  -> DeliveryError를 상위 API/관리 명령에 전달
```

`kakao-notifier` 단독 CLI는 Django DB를 열지 않으므로 실패 이력을 저장하지
않는다. 운영 점검에서 가능하면 Django 관리 명령을 쓰는 이유다.
