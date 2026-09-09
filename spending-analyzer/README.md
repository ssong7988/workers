# spending-analyzer

삼성카드 **이용대금명세서** 메일을 Gmail에서 자동으로 받아 파싱하고, 소비를 카테고리별로 분석해 로컬 페이지로 보여주는 프로그램입니다.

## 설계의 두 전제

**청구 기준으로 집계합니다.** 그 달 명세서의 청구액을 그대로 씁니다. 할부는 이번 달 회차 금액만 잡으므로, 합계가 통장에서 실제로 빠진 돈과 일치합니다.

명세서는 **월 단위 스냅샷**입니다. 그래서 한 달치 데이터가 명세서 한 통과 정확히 대응하고, 두 가지가 따라옵니다.

- 거래 단위 중복 판정이 필요 없습니다. 그 달을 통째로 저장하고, 재발송·정정본이 오면 `data/statements/2026-09.json` 하나만 교체됩니다.
- **파싱 정확성을 스스로 검증할 수 있습니다.** 파싱한 거래들의 청구액 합계는 명세서 헤더의 청구총액과 원 단위까지 맞아야 합니다. 어긋나면 표를 놓친 것이고, 그때는 저장하지 않고 실패합니다. 조용히 틀린 소비 분석은 없느니만 못합니다.

## 설치

```powershell
cd spending-analyzer
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

`.env`에 Gmail **앱 비밀번호**를 넣습니다. 계정 비밀번호로는 IMAP이 열리지 않습니다 — Google 계정 > 보안 > 2단계 인증 > 앱 비밀번호에서 발급하세요.

설정을 로컬에서 바꾸려면 `config/settings.yaml`을 `config/settings.local.yaml`로 복사하세요. 그쪽이 있으면 자동으로 먼저 읽히고, 커밋되지 않습니다.

## 시작하기 전에: 명세서 메일을 받아 두세요

삼성카드에서 이용대금명세서를 이메일로 받도록 설정하고, **최소 한 통은 도착한 뒤에** 다음 단계로 가세요. 과거 명세서는 삼성카드에 재발송을 요청해 메일함에 쌓아 두면 그만큼 추이를 볼 수 있습니다.

## 1단계: 진단

```powershell
python -m spending_analyzer validate-config
python -m spending_analyzer scan-mail
```

`scan-mail`은 **메일을 파싱하지 않습니다.** 파서를 쓰기 전에 알아야 할 네 가지만 확인합니다.

1. PDF가 첨부로 오는가, 아니면 "웹에서 확인" 링크뿐인가 — 링크뿐이면 메일 경로로는 상세 내역을 얻을 수 없습니다
2. PDF에 암호가 걸려 있는가 — 걸려 있으면 `.env`의 `SAMSUNG_PDF_PASSWORD`가 필요합니다
3. 텍스트 레이어가 있는가, 스캔 이미지인가 — 이미지면 OCR이 필요해 난이도가 달라집니다
4. 본문 HTML에 이미 상세가 들어 있는가 — 있다면 PDF를 건드릴 필요가 없습니다

출력 끝의 `판정:` 줄이 이 넷을 종합해 다음 단계를 알려줍니다.

메일 포맷을 추측해서 정규식을 먼저 쓰면 거의 확실히 버리게 되므로, 파서는 이 출력을 보고 씁니다.

```powershell
python -m spending_analyzer scan-mail --limit 10          # 최근 10통을 자세히
python -m spending_analyzer scan-mail --since 2026-01-01  # 설정의 기간을 덮어씀
python -m spending_analyzer scan-mail --all-senders       # 제목이 안 맞는 메일까지
python -m spending_analyzer scan-mail --dump 1            # 1번 메일 원문·첨부를 저장
```

`--dump`가 저장하는 `data/samples/`에는 **실제 명세서**가 들어갑니다. 이 폴더는 커밋되지 않으며, 공유하지 마세요.

아무 메일도 안 잡히면 `config/settings.yaml`의 `mail.senders`가 실제 발신 주소와 맞는지, `mail.since`가 첫 명세서보다 앞선 날짜인지, 명세서가 다른 라벨로 분류되지는 않았는지 확인하세요.

## 테스트

```powershell
python -m unittest discover -s tests -t . -v
```

메일 서버도 실제 명세서도 없이 돌아갑니다. 테스트에 쓰는 명세서는 개인정보가 없는 합성 메일입니다.

## 보안

소비 내역은 이 저장소에서 가장 민감한 데이터입니다.

- `data/`와 `config/settings.local.yaml`은 커밋되지 않습니다
- 자격증명은 `.env`에만 둡니다
- 카드번호는 **뒤 4자리만** 저장하고 나머지는 파싱 즉시 버립니다
- 메일함은 **읽기 전용(readonly)** 으로 엽니다 — 진단이 명세서를 읽음 처리하지 않습니다
- 자동 분류에는 **가맹점명만** 보냅니다. 금액·날짜·카드번호는 보내지 않습니다

## 진행 상황

- [x] 1단계 — 골격과 `scan-mail` 진단
- [ ] 2단계 — 명세서 파서 (`scan-mail` 결과를 보고 작성)
- [ ] 3단계 — 분류 (규칙 우선, 미분류만 Claude 폴백)
- [ ] 4단계 — 집계
- [ ] 5단계 — 대시보드 페이지
- [ ] 6단계 — 카카오 월간 요약 카드
