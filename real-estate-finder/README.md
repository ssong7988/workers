# real-estate-finder

과천 관심 아파트 매물을 매시간 확인하고 급매 및 평일 오전 보고를 본인 카카오톡으로 보내는 Python 프로그램입니다.

## 관심 조건

| 단지 | 일반층 조사/급매 | 1~3층·저층 조사/급매 |
|---|---:|---:|
| 래미안센트럴스위트 84A/B/C | 25억 / 24억 | 24억 / 23억 |
| 과천센트럴파크푸르지오써밋 84 전 타입 | 25.5억 / 24.5억 | 24.5억 / 23.5억 |
| 과천위버필드 84 전 타입 | 26억 / 25억 | 25억 / 24억 |
| 래미안슈르·에코팰리스 84 전 타입 | 22.5억 / 21.5억 | 21.5억 / 20.5억 |
| 광교푸르지오월드마크 전용 84~85㎡ | 가격 제한 없이 전체 | 가격 제한 없이 전체 |

## 설치

```powershell
cd real-estate-finder
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install msedge
Copy-Item config\searches.yaml config\searches.local.yaml
```

수집기는 저장된 매물 URL이나 네이버 부동산 주소를 직접 열지 않습니다. 먼저 네이버 홈을 열고 화면의 `부동산` 링크를 클릭한 뒤, 부동산 검색창에 설정의 단지명을 입력해 화면 검색 결과로 이동합니다. `config/searches.local.yaml`은 선택 사항이며 로컬 설정이 필요할 때만 사용합니다. 기존 `kakao-notifier/.env`와 `kakao-notifier/data/kakao-token.json`도 필요합니다.

## 최초 실행

```powershell
python -m real_estate_finder browser-login
python -m real_estate_finder validate-config
python -m real_estate_finder smoke-test
```

기본 실행은 새 브라우저를 만들지 않고 `http://127.0.0.1:9222`에서 이미 실행 중인 Edge에 연결합니다. 이 연결을 사용하려면 Edge가 처음부터 원격 디버깅 옵션과 함께 실행되어 있어야 하며, 이미 일반 모드로 실행 중인 Edge에는 실행 도중 연결을 추가할 수 없습니다. 연결한 Edge와 탭은 프로그램 종료 후에도 닫지 않습니다.

`smoke-test`는 오전까지 기다리지 않고 세 조건을 즉시 한 번 조회합니다. 조회 성공 여부와 조건 충족 매물을 본인 카카오톡으로 전송하며 정규 급매 발송 이력은 소모하지 않습니다.

기본 모드의 `browser-login`은 CDP로 연결된 기존 Edge에서 네이버 로그인 상태를 확인합니다. 예약 실행 중 로그인 만료가 감지되면 조회를 중단하며, 별도 프로필 방식은 `--edge-cdp ""`를 지정한 경우에만 사용합니다.

## 정규 명령과 테스트

```powershell
python -m real_estate_finder collect-favorites
python -m real_estate_finder scan-once
python -m real_estate_finder scheduled-run
python -m real_estate_finder send-digest
python -m unittest discover -s tests -v
```

`collect-favorites`는 로그인된 Edge에서 네이버 홈의 `부동산` 링크를 클릭한 뒤
`관심부동산`에 저장된 6개 단지의 `매물보기` 화면을 순서대로 확인합니다. 단지
사이에는 8초 간격을 두며, 한 단지에서 최대 120건까지만 읽습니다. 결과는
`data/favorites-latest.json`에 원자적으로 저장됩니다. CAPTCHA, 로그인 만료 또는
접근 제한이 보이면 우회하지 않고 즉시 중단합니다.

각 매물 화면에서는 중개사별 `매물목록 펼치기`를 누르지 않고 화면의 묶음 카드만
읽습니다. 광교푸르지오월드마크는 전용 84~85㎡ 매매만 가격 제한 없이 집계하며, 나머지 단지는
`전체면적` → `유사면적 묶기` → 전체 선택 해제 순서로 연 뒤, 공급면적이
아니라 괄호 안 전용면적 숫자가 83~86인 항목만 선택합니다. 예를 들어
`84~85㎡ (59)`는 제외하고 `116~117㎡ (84)`는 선택합니다.

Windows 작업 스케줄러에서 `scheduled-run`을 매시간 정각, 사용자가 로그인한 상태에서 실행합니다. 평일 오전 8시 실행은 조회 후 전체 보고도 발송합니다. 상세 상태와 PostgreSQL 계획은 `project_state.md`를 참고하세요.
