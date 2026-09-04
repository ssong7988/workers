# 네이버 관심부동산 수집 구조

## 브라우저 연결 방식

기본 주소는 `http://127.0.0.1:9222`다. `runtime.ensure_edge_debugging()`은 이 주소의
`/json/version`을 먼저 확인한다. 열려 있지 않으면 Microsoft Edge를 다음과
같은 개념의 인자로 시작한다.

```text
--remote-debugging-port=9222
--user-data-dir=%LOCALAPPDATA%\naver-land-edge
```

최신 Edge는 기본 프로필에서 원격 디버깅 인자를 무시할 수 있어 저장소 밖의
전용 프로필을 쓴다. 이 프로필은 로그인 쿠키를 유지하지만 Git 관리 대상이
아니다. `collector.py`는 `connect_over_cdp()`로 이미 실행 중인 Edge에 붙으며,
외부 브라우저를 소유하지 않으므로 종료할 때 Edge 자체를 닫지 않는다.

`--edge-cdp ''`로 실행하면 collector가 전용 persistent context를 직접 여는
대체 경로를 사용할 수 있지만, 일상 운영은 외부 Edge CDP가 기준이다.

## 로그인과 차단 감지

`browser-login`은 네이버 로그인 페이지를 열고 현재 로그인 상태를 확인한다.
로그인이 필요하면 사용자 입력을 기다린다. 수집 중에도 `_verify_login()`과
`_raise_if_blocked()`가 로그인 만료, CAPTCHA, 비정상 접근 화면을 감지한다.

Edge 창을 최소화하거나 완전히 뒤로 보내면 Chromium이 페이지 렌더링을
지연시켜 로그인 화면이 덜 그려진 상태를 로그아웃으로 오인할 수 있다.
수집 중에는 창을 보이는 상태로 둔다. 차단 감지 직전 `bring_to_front()`를
호출하지만 OS 수준의 완전한 최소화까지 항상 복구하지는 못한다.

## 관심단지 스냅샷

`collect_favorites_snapshot()`의 순서는 다음과 같다.

1. Playwright를 로드하고 CDP 또는 persistent context로 브라우저에 연결한다.
2. 네이버 홈을 거쳐 부동산과 관심부동산 화면을 연다.
3. 관심단지 탭이 표시한 예상 단지 수를 읽는다.
4. `_favorite_complexes()`로 단지명과 이동 주소를 읽는다.
5. 예상 수와 읽은 수가 다르면 실패한다.
6. 각 단지를 `_collect_favorite_complex()`로 순서대로 방문한다.
7. 화면 필터, 카드 스크롤, 묶음 펼치기, 원본 텍스트 파싱 결과를 반환한다.

단지 목록의 하드코딩된 개수는 없다. 관심단지를 추가하거나 제거하면 다음
수집부터 화면의 개수를 따라간다. 다만 무한 스크롤 오류를 막는 방어 한계는
있으며, 표시 개수와 실제 목록이 일치해야 한다.

## 단지 한 곳을 읽는 과정

```text
단지 URL 열기
  -> 매매 탭 선택
  -> 전용면적 80~86㎡ 범위 선택
  -> 화면이 안정될 때까지 카드 수 확인
  -> 카드 목록을 위에서 아래까지 스크롤
  -> 중개사 묶음 카드 펼치기
  -> DOM 행 병합
  -> 대표 매물번호·URL 선택
  -> 카드 텍스트를 원본 Listing으로 변환
```

화면 필터는 매매와 전용면적 80~86㎡로 고정된 1차 범위 축소다. 기준 84㎡
조건의 서버 기본 허용 범위가 `-1㎡ ~ +2㎡`이므로 화면에서 85㎡까지만 고르면
필요한 행을 먼저 잃을 수 있어 상단을 86㎡로 둔다. 이 값은 조건별 최종 판정이
아니다. 정확한 면적 허용 범위, 타입, 저층 할인, 가격 상한은 서버가 다시
판정한다. 화면 필터가 넓게 잡히더라도 원본을 서버에 보내는 것이 맞다.

## 스크롤과 카드 완전성

네이버 목록은 보이는 영역만 DOM에 두는 가상 스크롤일 수 있다.
`_collect_complex_cards()`는 스크롤 위치와 카드 행을 반복해서 읽고,
새 행이 더 이상 나오지 않을 때까지 병합한다. `_settled_list_card_count()`와
`_wait_for_list_card_count()`는 필터 적용 직후의 일시적인 숫자를 확정값으로
쓰지 않게 한다.

수집 결과에는 두 개수가 따로 남는다.

- `card_count`: 화면에서 읽은 카드 수
- `listing_count`: 파싱 후 실제 매매 매물 행 수

카드에는 매매 외 거래형이 섞이거나 파싱에서 제외되는 행이 있을 수 있으므로
둘은 같지 않아도 된다. 묶음 카드에 여러 중개사 매물번호가 있어도 대표 하나의
원본 매물로 만든다. `expected_count`는 화면 필터가 말한 예상 카드 수이며
완전성 검사에 쓴다.

## 묶음 매물 병합

같은 집이 여러 중개사 카드로 묶여 있거나 펼친 뒤 여러 행으로 나타날 수 있다.
`_merge_article_rows()`는 화면에서 읽은 그룹을 합치고,
`_pick_representative_article()`은 다음 순서로 대표 링크를 고른다.

1. 가격이 가장 낮은 행
2. 가격이 같으면 숫자 매물번호가 가장 큰 행

숫자 매물번호와 `/articles/` URL이 없으면 화면 내부 식별자로 해시 기반 ID를
만들 수 있다. 이 원본 관측은 통계에 남을 수 있지만, 현재 웹 매물 리포트는
직접 열 수 있는 숫자 매물번호와 article URL만 노출한다.

## 텍스트 파싱

`_parse_favorite_listing_text()`와 하단 `_extract_*` 함수가 카드 문자열에서
다음을 뽑는다.

- 가격: `parse_price_won()`으로 원 단위 정수
- 전용면적: 카드에 표시된 ㎡ 숫자
- 타입: `84`, `84A`처럼 정규화 가능한 이름
- 층: 원문 `floor_text` 그대로
- 동, 방향, 설명, 단지명, 원본 URL

층이 저층인지, 층 문구가 유효한지는 여기서 판정하지 않는다. 서버의
`properties/matching.py`가 공통 규칙과 함께 판정해야 과거 재분류가 가능하다.

## 조건으로 매핑

한 번 만든 스냅샷을 각 `SearchCondition.complex_names`에 매핑한다. 별칭은
공백을 제거해 비교하며, 같은 단지가 여러 조건에 속하면 각각의
`condition_id`를 가진 별도 `Listing`이 된다.

조건 안에서 별칭이 겹쳐 같은 매물이 두 번 생길 수 있으므로 CLI의
`_deduplicate()`가 `condition_id:listing_id` 기준으로 마지막 POST 전에 제거하고
제거 개수를 출력한다.

## 전체 실패를 보고하는 이유

현재 스냅샷 하나가 모든 조건을 공급한다. 탐색 중 예외가 나면 이미 읽은 일부
단지만 서버에 성공으로 보내지 않는다. 모든 조건을 실패로 보내면 서버가
`Scan`에는 실패를 기록하되 기존 활성 매물은 유지한다.

부분 성공을 도입하려면 단지별 실패가 어느 조건에 영향을 미치는지 정확히
추적하고, 성공 조건만 안전하게 비활성화할 수 있는 별도 설계가 먼저 필요하다.
현재 코드에서 예외 처리 한 줄만 바꿔 부분 성공처럼 만드는 것은 데이터 손실을
일으킬 수 있다.

## 변경 지점 빠르게 찾기

| 증상 | 먼저 볼 메서드 |
|---|---|
| 로그인 대기·만료 오인 | `open_login`, `_wait_for_login`, `_verify_login`, `_raise_if_blocked` |
| 관심단지 탭을 못 찾음 | `_open_favorites`, `_favorite_complexes` |
| 단지 하나가 안 열림 | `_collect_favorite_complex` |
| 매매·면적 필터 오류 | `_apply_screen_filters`, `_select_trade_type`, `_select_similar_exclusive_area` |
| 일부 카드 누락 | `_collect_complex_cards`, `_listing_scroll_state`, `_visible_listing_rows` |
| 묶음 개수·링크 오류 | `_expand_listing_groups`, `_settled_bundle_articles`, `_merge_article_rows` |
| 가격·면적·층 파싱 오류 | `_parse_favorite_listing_text`, 파일 하단 `_extract_*` |
| 서버가 중복을 거부 | CLI `_deduplicate`, `Listing.key` |

DOM 선택자를 바꿀 때는 눈에 보이는 한 카드만 맞추지 말고 빈 목록, 묶음 카드,
스크롤 뒤 재사용된 DOM, 필터 적용 직후 로딩 상태를 함께 확인한다.
