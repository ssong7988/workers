# Real Estate Finder

부동산 매물을 탐색하고 새 매물을 카카오톡으로 알리는 모노레포입니다.

## 프로젝트 구조

```text
outputs/
├── kakao-notifier/       # 카카오 인증, 토큰 관리, 메시지 전송
└── real-estate-finder/   # 부동산 매물 탐색 애플리케이션
```

## 구성 요소

- `kakao-notifier`: 여러 앱에서 공통으로 사용할 카카오톡 알림 서비스
- `real-estate-finder`: 첫 번째 연동 앱. 조건에 맞는 부동산 매물을 찾고 알림을 요청

각 앱의 설치 및 실행 방법은 해당 폴더의 README에서 관리합니다.

## 가장 빠른 실행

에이전트 없이 매물을 한 번 조회하고 카카오톡으로 보내려면 다음 파일을 더블클릭합니다.

```text
real-estate-finder\run-scan.bat
```

PowerShell에서는 저장소 루트에서 다음과 같이 실행할 수 있습니다.

```powershell
.\real-estate-finder\run-scan.ps1
```

이 스크립트가 전용 Edge 실행, 네이버 로그인 확인, 매물 조회, 카카오톡 전송을 순서대로 처리합니다. 최초 설치와 문제 해결, 웹 화면 실행 방법은 [수동 실행 매뉴얼](.agent/docs/RUNBOOK.md)을 참고하세요.
