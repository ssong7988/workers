# Real Estate Finder

부동산 매물을 수집해 웹 리포트로 보여주고 카카오톡으로 알리는 모노레포입니다.

## 프로젝트 구조

```text
outputs/
├── real-estate-finder/   # 수집기. 네이버에서 본 매물을 그대로 넘긴다
├── report-site/          # 애플리케이션. DB, 판정, 웹 리포트, 가격 통계, 카카오 전송
└── kakao-notifier/       # 카카오 인증, 토큰 관리, 메시지 전송
```

역할이 둘로 갈려 있습니다. `real-estate-finder`는 **수집만** 합니다. 어떤 매물이 조건에 맞는지, 급매인지, 신규인지, 카카오톡을 보낼지, 화면에 어떻게 보일지는 전부 `report-site`(Django + PostgreSQL)가 결정합니다.

화면은 둘입니다. **매물 리포트**는 지금 조건에 맞는 매물을, **가격 통계**는 그동안 수집한 원본으로 만든 날짜별 호가 분포를 보여줍니다.

각 앱의 설치 및 실행 방법은 해당 폴더의 README에서 관리합니다.

## 가장 빠른 실행

더블클릭 순서가 중요합니다. 서버가 데이터를 받는 쪽이라 먼저 켜야 합니다.

```text
1) report-site\run-site.bat        애플리케이션 서버
2) real-estate-finder\run-scan.bat 매물 조회
```

PowerShell에서는 저장소 루트에서 다음과 같이 실행할 수 있습니다.

```powershell
.\report-site\run-site.ps1
.\real-estate-finder\run-scan.ps1
```

`run-scan`이 서버 확인, 전용 Edge 실행, 네이버 로그인 확인, 매물 수집, 서버 전달을 순서대로 처리합니다. 급매나 신규 매물이 있으면 서버가 카카오톡 1통을 `통계 보기`·`전체 매물 보기` 두 버튼과 함께 보내고, 없으면 그 사유를 창에 출력합니다.

급매가 아니어도 지금 전체 결과를 받고 싶으면 `real-estate-finder\send-report.bat`을 실행합니다.

최초 설치와 문제 해결, 외부 공개 설정은 [수동 실행 매뉴얼](.agent/docs/RUNBOOK.md)을, 코드 구조는 [아키텍처 문서](.agent/docs/ARCHITECTURE.md)를 참고하세요.
