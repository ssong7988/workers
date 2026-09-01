# real-estate-finder

과천 관심 아파트 매물을 매시간 확인하고 급매 및 평일 오전 보고를 본인 카카오톡으로 보내는 Python 프로그램입니다.

> 네이버 이용약관은 사전 허락 없는 자동 검색·수집을 제한합니다. 본 프로젝트는 CAPTCHA, 접근 제한 또는 비공개 API를 우회하지 않으며, 차단이 감지되면 조회를 중단합니다. 운영 전 관련 약관과 사용 권한을 직접 확인하세요.

## 관심 조건

| 단지 | 일반층 조사/급매 | 1~3층·저층 조사/급매 |
|---|---:|---:|
| 래미안센트럴스위트 84A/B/C | 25억 / 24억 | 24억 / 23억 |
| 과천센트럴파크푸르지오써밋 84 전 타입 | 25.5억 / 24.5억 | 24.5억 / 23.5억 |
| 과천위버필드 84 전 타입 | 26억 / 25억 | 25억 / 24억 |

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
python -m real_estate_finder scan-once
python -m real_estate_finder scheduled-run
python -m real_estate_finder send-digest
python -m unittest discover -s tests -v
```

Windows 작업 스케줄러에서 `scheduled-run`을 매시간 정각, 사용자가 로그인한 상태에서 실행합니다. 평일 오전 8시 실행은 조회 후 전체 보고도 발송합니다. 상세 상태와 PostgreSQL 계획은 `project_state.md`를 참고하세요.
