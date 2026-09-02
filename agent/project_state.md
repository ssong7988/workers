# Real Estate Finder 프로젝트 상태

최종 갱신: 2026-09-02 (Asia/Seoul)

## 목적

네이버 부동산의 관심 단지 매물을 주기적으로 수집하고, 조건에 맞는 매물과 급매를
판별하여 카카오톡 카드로 전송한다. 전체 매물은 웹 리포트에서도 확인할 수 있다.

## 프로젝트 구조

- `real-estate-finder/`: 매물 수집, 필터링, 상태 저장, 카드 생성과 전송을 담당하는
  Python 애플리케이션
- `kakao-notifier/`: 카카오 인증, 토큰 관리, 텍스트·이미지 메시지 전송 모듈
- `property-report-site/site-app/`: 웹 리포트 UI. 상위 저장소 안의 별도 Git 저장소
  형태로 관리됨

## 현재 실행 구조

### 매물 조회

- 기본 진입점: `real-estate-finder/run-scan.bat` 또는 `run-scan.ps1`
- Edge CDP 주소: `http://127.0.0.1:9222`
- 검색 설정: `real-estate-finder/config/searches.yaml`
- 런타임 상태와 수집 결과: `real-estate-finder/data/` 아래에 저장되며 Git에서 제외됨
- 스캔은 `app/report-data.json`을 갱신할 수 있지만 UI 빌드나 배포를 자동 실행하지
  않는다.

### 카카오톡

- 공개 리포트 기본 주소:
  `https://my-property-report-20260902.ssong7988.chatgpt.site`
- `KAKAO_REPORT_URL` 환경변수로 주소를 덮어쓸 수 있다.
- 카드 이미지는 카카오 이미지 업로드 API로 전송된다.
- 공개 리포트에 현재 조회 시각이 반영된 경우에만 `전체 매물 보기` 버튼을 붙인다.
- 로컬 주소 `127.0.0.1:3000`은 카카오 메시지 버튼에 사용하지 않는다. 휴대폰에서
  접근할 수 없고 카카오 제품 링크의 등록 도메인과 일치하지 않아 기본 개발자
  페이지로 연결될 수 있다.

## 웹 리포트 배포 방식

현재 기본 방식은 **Codex Sites 배포**다.

- Sites 프로젝트 ID: `appgprj_6a9769c089308191b155c20de009e2b2`
- 활성 공개 주소: `https://my-property-report-20260902.ssong7988.chatgpt.site`
- 현재 배포 버전: 5
- Sites 빌드: `npm run build` (`vinext build`)
- 개발 미리보기: `npm run dev`
- `app/page.tsx`가 `report-data.json`을 빌드 시점에 포함하므로, 공개 리포트의
  데이터를 바꾸려면 명시적인 빌드와 배포가 필요하다.
- 빈번한 매물 스캔에서는 빌드하지 않는다. 공개 리포트를 갱신하기로 결정했을 때만
  빌드·배포한다.

### 보존한 로컬 방식

향후 고정 DNS와 Cloudflare Tunnel 또는 Tailscale Funnel을 준비하면 로컬 UI를
다시 기본 방식으로 전환할 수 있도록 다음 명령을 유지한다.

- `npm run dev:local`
- `npm run build:local`
- `npm run start:local`
- `property-report-site/site-app/run-local.ps1`
- `property-report-site/site-app/run-local.bat`

로컬 명령은 필요할 때 `next@16.3.4`를 실행하며, 현재 기본 Sites 의존성과 분리돼
있다.

## 최신 조회 및 배포 상태

- 조회 시각: `2026-09-02T19:32:19+09:00`
- 원본 수집: 119건
- 조건 충족: 41건
- 대상 단지: 6개
- 조회 실패: 0개
- 이번 스캔에서 새로 발송할 급매 알림: 0건
- 현재 리포트에서 급매 조건에 해당하는 매물: 1건
- 최신 41건으로 Codex Sites 버전 5 배포 완료
- 배포 후 동일한 41건 전체 매물 카드를 카카오톡으로 전송 완료
- 공개 페이지의 `data-observed-at` 값이 최신 조회 시각과 일치함을 확인함

## 빌드 및 테스트

- Codex Sites용 `vinext build` 성공
- Python 단위 테스트 78개 통과
- 복원한 Sites 패키지 잠금 파일 기준 `npm ci` 성공
- 현재 npm 감사 결과는 취약점 11건(낮음 1, 보통 2, 높음 8)을 보고한다.
  `npm audit fix --force`는 Vinext/Vite 호환성을 깨뜨릴 수 있으므로 검증 없이
  실행하지 않는다.

## 주요 커밋

### 상위 저장소 (`kakao-image-card` 브랜치)

- `5f8d536` Restore hosted property report workflow
- `2f97b84` Update local UI revision
- `2c4b5cf` Run property report UI locally

### UI 저장소 (`property-report-site/site-app`, `main` 브랜치)

- `7170035` Restore Codex Sites deployment workflow
- `4d563ce` Ignore generated report previews
- `2977cc2` Replace Sites deployment with local Next.js UI

## 향후 작업

1. 개인 고정 도메인을 준비한다.
2. Cloudflare Tunnel 또는 Tailscale Funnel로 로컬 포트 3000을 공개 HTTPS 주소에
   연결한다.
3. 해당 주소를 카카오 개발자 콘솔의 `[앱] > [제품 링크 관리] > [웹 도메인]`에
   등록한다.
4. `KAKAO_REPORT_URL`을 새 고정 주소로 변경한다.
5. 그때 기본 UI 실행 방식을 로컬 Next.js로 전환하고, 매물 JSON을 실행 중에 읽도록
   변경하여 데이터 갱신만으로 화면에 반영되게 한다.
6. Sites 의존성 취약점은 호환되는 새 Vinext/Sites 버전이 확인될 때 함께 갱신한다.

## 주의사항

- `kakao-notifier/.env`와 `data/kakao-token.json`의 값은 비밀 정보이므로 문서나
  Git에 기록하지 않는다.
- `property-report-site/site-app`은 별도 Git 저장소다. UI 변경은 UI 저장소에서 먼저
  커밋한 뒤, 상위 저장소에서 변경된 Git 포인터를 다시 커밋해야 한다.
- 생성된 리포트 미리보기 이미지 `public/property-report.png`와
  `public/property-report-compact.png`는 `.gitignore`에 등록돼 있다.
