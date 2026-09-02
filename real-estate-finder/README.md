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

Edge를 먼저 띄우고(아래 참고), 그다음 순서대로 실행합니다.

```powershell
python -m real_estate_finder browser-login
python -m real_estate_finder validate-config
python -m real_estate_finder smoke-test
```

### 시작 지점: Edge를 직접 띄우고 거기에 로그인한다

이 프로그램은 브라우저를 새로 만들지 않습니다. **사용자가 띄운 Edge에 붙습니다.** 그래서 모든 실행의 출발점은 아래 명령입니다.

```powershell
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" `
  --remote-debugging-port=9222 --user-data-dir="$env:LOCALAPPDATA\naver-land-edge"
```

이 Edge 창을 **켜 둔 채로** 조회 명령을 실행합니다. 프로그램은 여기 붙어서 화면을 조작하고, 끝나도 창과 탭을 닫지 않습니다.

**`--user-data-dir`는 생략할 수 없습니다.** Chrome 136(Edge도 동일)부터 보안상 기본 프로필에서는 `--remote-debugging-port`가 조용히 무시됩니다. 평소 쓰던 Edge 프로필에는 붙을 수 없다는 뜻입니다. 경로는 **저장소 밖**을 쓰세요 — 저장소 안을 가리키면 프로필 파일 수천 개가 작업 트리에 쌓입니다.

전용 프로필이라 처음에는 네이버에 로그인돼 있지 않습니다. 한 번만 로그인하면 그 프로필에 남습니다.

```powershell
python -m real_estate_finder browser-login
```

Edge 창에서 네이버 로그인을 완료하면 **자동으로 이어집니다**(최대 5분 대기). 이미 로그인돼 있으면 확인만 하고 끝납니다.

이미 다른 Edge가 일반 모드로 실행 중이면 위 명령이 새 창만 띄우고 포트가 열리지 않을 수 있습니다. 그럴 때는 그 Edge를 모두 닫고 다시 실행하세요.

> 참고: `--edge-cdp ""`를 주면 프로그램이 `data/browser-profile`로 Edge를 직접 띄우는 대체 모드로 동작합니다. 사용자가 브라우저를 통제하지 않게 되므로 기본 경로는 아닙니다.

`smoke-test`는 오전까지 기다리지 않고 세 조건을 즉시 한 번 조회합니다. 조회 성공 여부와 조건 충족 매물을 본인 카카오톡으로 전송하며 정규 급매 발송 이력은 소모하지 않습니다.

기본 모드의 `browser-login`은 CDP로 연결된 기존 Edge에서 네이버 로그인 상태를 확인합니다. 예약 실행 중 로그인 만료가 감지되면 조회를 중단하며, 별도 프로필 방식은 `--edge-cdp ""`를 지정한 경우에만 사용합니다.

## 정규 명령과 테스트

```powershell
python -m real_estate_finder collect-favorites
python -m real_estate_finder scan-once
python -m real_estate_finder scheduled-run
python -m real_estate_finder send-digest
python -m real_estate_finder preview-card
python -m unittest discover -s tests -v
```

## 카카오 알림은 이미지 카드로 나갑니다

카카오 기본 텍스트 템플릿은 200자를 넘길 수 없어, 매물이 몇 건만 넘어가도 알림에서 목록이 잘려 나갔습니다. 그래서 `scan-once`의 급매·신규 알림과 `send-digest`의 전체 보고는 매물 목록을 카드 이미지 한 장으로 렌더링해 보냅니다. `send-digest`도 매물당 한 통이 아니라 한 통으로 끝납니다.

렌더링은 `real_estate_finder/card.py`가 담당합니다. 자기완결형 HTML을 만들어 headless Edge로 스크린샷하며, 브라우저 프로필은 OS 임시 폴더에 만들고 끝나면 지웁니다(저장소 안을 가리키면 `edge-shot-profile` 같은 찌꺼기가 남습니다).

`preview-card`는 저장된 매물로 이미지만 만들고 전송하지 않습니다. 디자인을 확인할 때 씁니다.

```powershell
python -m real_estate_finder preview-card --out data\card-preview.png
```

렌더링이나 전송이 실패하면 기존 텍스트 메시지로 자동 대체되므로 알림 자체가 사라지지는 않습니다. 이미지 경로를 아예 끄려면 `--text-only`를 붙입니다.

`collect-favorites`는 로그인된 Edge에서 네이버 홈의 `부동산` 링크를 클릭한 뒤
`관심부동산`에 저장된 6개 단지의 `매물보기` 화면을 순서대로 확인합니다. 단지
사이에는 8초 간격을 두며, 한 단지에서 최대 120건까지만 읽습니다. 결과는
`data/favorites-latest.json`에 원자적으로 저장됩니다. CAPTCHA, 로그인 만료 또는
접근 제한이 보이면 우회하지 않고 즉시 중단합니다.

각 매물 화면에서는 중개사별 `매물목록 펼치기`를 열고 개별 매물을 확인합니다.
묶음 카드의 대표 링크는 가장 저렴한 개별 매물을 선택하며, 가격이 같으면 매물번호가
가장 큰 최신 링크를 선택합니다. 광교푸르지오월드마크는 전용 84~85㎡ 매매만 가격 제한 없이 집계하며, 나머지 단지는
`전체면적` → `유사면적 묶기` → 전체 선택 해제 순서로 연 뒤, 공급면적이
아니라 괄호 안 전용면적 숫자가 83~86인 항목만 선택합니다. 예를 들어
`84~85㎡ (59)`는 제외하고 `116~117㎡ (84)`는 선택합니다.

Windows 작업 스케줄러에서 `scheduled-run`을 매시간 정각, 사용자가 로그인한 상태에서 실행합니다. 평일 오전 8시 실행은 조회 후 전체 보고도 발송합니다. 상세 상태와 PostgreSQL 계획은 `project_state.md`를 참고하세요.
