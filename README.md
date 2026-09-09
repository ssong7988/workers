# workers

관심 대상을 자동으로 수집해 카카오톡으로 알리고 로컬 페이지로 보는 앱들의 모노레포입니다.

## 프로젝트 구조

```text
outputs/
├── kakao-notifier/       # 카카오 인증, 토큰 관리, 메시지 전송
├── real-estate-finder/   # 부동산 매물 탐색 애플리케이션
└── spending-analyzer/    # 삼성카드 명세서 소비 분석
```

## 구성 요소

- `kakao-notifier`: 여러 앱에서 공통으로 사용할 카카오톡 알림 서비스
- `real-estate-finder`: 첫 번째 연동 앱. 조건에 맞는 부동산 매물을 찾고 알림을 요청
- `spending-analyzer`: 두 번째 연동 앱. 삼성카드 이용대금명세서 메일을 파싱해 소비를 분석

각 앱의 설치 및 실행 방법은 해당 폴더의 README에서 관리합니다.

