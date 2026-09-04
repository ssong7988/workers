# PostgreSQL 데이터와 판정 규칙

## 모델 관계

```text
GlobalRule (항상 pk=1)

SearchCondition
  |-- Observation * ---- Scan
  `-- Listing *          |
                         `-- NotificationFailure *
```

`Observation`과 `Listing`은 추상 모델 `PropertyFields`의 매물 필드를 공유하지만
역할이 다르다. 하나는 당시 본 사실과 판정 이력이고, 다른 하나는 현재 리포트에
보일 상태다.

## 모델별 의미

### `GlobalRule`

애플리케이션 전체에 하나만 존재한다. `save()`가 pk를 1로 고정하고 admin은
두 번째 행 추가와 삭제를 막는다.

- 거래 유형
- 저층으로 볼 숫자 층과 텍스트 표기
- 저층 가격 차감액
- 업무 시간대
- 정기 보고 요일과 시각

스케줄러 시간표는 현재 Dagster 코드에도 정의돼 있다. admin에서 digest 시각을
바꾸는 것만으로 Dagster cron이 자동 변경되는 구조는 아니므로 둘을 함께
확인한다.

### `SearchCondition`

조건 ID, 표시 이름, 지역, 단지명 별칭, 면적 범위, 허용 타입, 조사 상한가,
급매 기준가, 신규 알림 여부, 저층 할인 여부, 활성 여부를 가진다.

검증 규칙:

- 급매 기준가는 조사 상한가보다 높을 수 없다.
- 최소 면적은 최대 면적보다 클 수 없다.
- 검색 URL이 있으면 네이버 HTTPS URL만 허용한다.
- `allowed_types=NULL`은 모든 타입 허용이다.

`properties/seed/searches.yaml`은 최초 `import_searches`에 쓰는 초기값이다.
운영 중 수정은 Django admin에서 하며 YAML을 바꿔도 DB가 자동으로 바뀌지 않는다.

### `Scan`

수집 실행 하나를 나타낸다. 시작·종료 시각, 성공/실패 조건, 수집·통과·급매·제외
개수와 `notification`을 보존한다. 시작 시각은 unique이므로 같은 실행 payload를
그대로 중복 POST하면 충돌한다.

`notification`은 단순 성공 문구가 아니다. 알림 대상이 없거나 수집이 실패한
경우에도 이유를 기록해 조용한 종료와 장애를 구분한다.

### `Observation`

서버가 받은 매물 원본 전량이다. 조건을 통과하지 않아도 저장한다.

- `raw_payload`: 수집기가 실제 보낸 JSON
- `exclusion_reason`: 사람이 읽는 당시 탈락 이유
- `exclusion_code`: 통계와 필터가 쓰는 안정적인 코드
- `scan`, `condition`, `listing_id`: 한 스캔 안에서 unique

제외 코드는 `complex`, `area`, `type`, `floor`, `price`, 빈 문자열(통과)이다.
표시 문구는 바뀔 수 있으므로 통계는 한국어 이유 문자열을 검색하지 않는다.

### `Listing`

조건을 통과한 매물의 현재 행이다. unique 키는 `(condition, listing_id)`다.

- `first_seen_at`: 처음 본 시각, 이후 갱신에서도 보존
- `last_seen_at`, 매물 필드: 성공 스캔에서 다시 보면 갱신
- `active`: 성공 스캔에서 안 보이면 false
- `last_urgent_alert_price_won`: 과거 이관과 admin 가시성을 위한 알림 이력

`is_urgent`는 저장된 가격이 `effective_urgent_price_won` 이하인지 계산하는
속성이다.

### `NotificationFailure`

카카오 전송 실패 시 메시지, URL, 오류, 시도 횟수와 처리 시각을 남긴다.
전송 실패를 삼키지 않고 API에는 502 또는 관리 명령 실패로 올리되, 진단할
내용은 DB에 보존한다.

## `record_scan()` 트랜잭션

`properties/scanning.py`의 이 함수가 상태 변경의 중심이다.

1. 성공 조건 ID가 현재 활성 `SearchCondition`인지 확인한다.
2. 시작·종료 시각을 timezone-aware 값으로 바꾸고 순서를 검증한다.
3. `Scan`을 만든다. 실패 조건이 없고 성공 조건이 하나 이상일 때 성공이다.
4. 관련 기존 `Listing`을 `select_for_update()`로 잠근다.
5. 각 원본을 `Observation`으로 만들고 조건을 판정한다.
6. 탈락이면 이유와 코드를 저장하고 현재 `Listing`에는 넣지 않는다.
7. 통과면 새 `Listing`을 만들거나 기존 행을 갱신·활성화한다.
8. 신규·급매·`notify_new` 정책으로 알림 대상을 결정한다.
9. 성공 조건마다 이번에 보이지 않은 기존 행을 비활성화한다.
10. 집계와 전송 대기 또는 미전송 이유를 `Scan`에 저장하고 커밋한다.

입력 검증, Observation 저장, Listing 갱신, 비활성화 중 하나라도 실패하면
전체 트랜잭션이 롤백된다. 카카오 전송은 함수 밖에서 커밋 후 실행한다.

## 성공 조건과 실패 조건

이 구분은 상태 보존에 직접 영향을 준다.

- 성공 조건: 빈 결과도 신뢰한다. 이번에 못 본 기존 매물을 비활성화한다.
- 실패 조건: 결과를 신뢰하지 않는다. 기존 매물 상태를 건드리지 않는다.
- 두 목록은 겹칠 수 없으며 API가 400으로 거부한다.

수집기가 현재 한 관심부동산 스냅샷 전체를 성공 또는 실패로 보내는 이유도 이
계약 때문이다.

## 조건 판정 순서

`explain_condition()`은 첫 탈락 이유를 반환하고 계산 필드를 채운다.

1. 단지명: 공백을 제거하고 어느 별칭이 포함되는지 확인
2. 면적: min/max, 또는 기준 면적의 `-1㎡ ~ +2㎡` 기본 범위
3. 타입: `84`, `84A` 형태로 정규화한 뒤 허용 목록 확인
4. 층: 숫자 또는 저·중·고층 표현 해석
5. 저층 조정: 설정 시 조사 상한가와 급매가에서 공통 차감액을 뺌
6. 가격: 조정된 조사 상한가와 비교

층을 해석하지 못하면 가격 전에 제외한다. 저층 여부와 유효 상한가를
Observation과 Listing에 저장해 당시 판정이 나중에도 설명 가능하게 한다.

## 신규와 급매 알림 정책

현재 알림의 핵심은 “기존 매물이 임계값을 넘었는가”가 아니라 “이번에 처음 본
매물인가”다.

```text
is_new = 기존 (condition, listing_id) 행이 없음
is_urgent = price_won <= effective_urgent_price_won

급매 알림 = is_new and is_urgent
일반 신규 알림 = is_new and condition.notify_new
```

기존 매물이 나중에 급매가 되거나 가격이 더 내려가도 다시 알리지 않는다.
리포트에는 계속 급매로 표시된다. `smoke=True`는 정규 급매 이력을 소모하지
않고 전체 결과 전달 경로를 시험한다.

## 리포트 데이터

매물 리포트는 `active=True`이고 조건도 활성인 `Listing`만 사용한다. 선택한
지역이나 단지로 좁힌 뒤 조건 순서로 묶고 가격 오름차순으로 표시한다.

`build_report_payload()`는 숫자 `listing_id`와 `/articles/` URL이 있는 행만
공개 목록에 넣는다. 묶음 카드의 내부 해시 ID처럼 직접 열 수 없는 행을 링크로
보이지 않게 하기 위한 정책이다.

활성 행이 없으면 최근 성공 조건이 있었던 `Scan` 시각을 리포트 기준 시각으로
사용한다. template의 `data-observed-at`에 이 값이 들어간다.

## 가격 통계의 모집단

통계는 현재 `Listing`이 아니라 과거 `Observation`을 사용한다. 포함 코드는
다음 두 가지다.

```text
""       조건 충족
"price"  면적·타입·층은 맞지만 조사 상한가만 초과
```

가격 상한에서 표본을 자르면 최고가와 3분위가 시장이 아니라 사용자의 예산을
나타내므로 가격만 초과한 매물도 포함한다. 단지·면적·타입·층에서 탈락한 원본은
포함하지 않는다.

하루에 여러 번 수집하므로 `(condition, listing_id, 로컬 날짜)`별 마지막 관측
하나만 센다. 스캔 횟수가 많은 매물이 분포를 과도하게 끌지 않게 하기 위해서다.

하루 표본이 5건 이상이면 inclusive 방식으로 1·3분위를 계산한다. 4건 이하면
보간값을 시세처럼 보여주지 않고 최저·평균·최고만 제공한다. 스캔이 없는 날은
0으로 그리지 않고 차트에서 생략한다.

## 조건 변경과 과거 데이터

admin에서 조건을 바꾸면 다음 스캔부터 새 규칙이 적용된다. 기존 Observation의
판정은 자동 변경되지 않는다. 과거 통계를 새 조건으로 다시 맞출 의도가 있을
때만 다음 순서로 실행한다.

```powershell
cd report-site
..\real-estate-finder\.venv\Scripts\python.exe manage.py reclassify_observations --dry-run
..\real-estate-finder\.venv\Scripts\python.exe manage.py reclassify_observations
```

재분류는 현재 조건으로 과거 원본을 다시 판단하는 작업이다. 과거 당시의 정책을
보존해야 하는 분석이라면 실행하지 않는다.
