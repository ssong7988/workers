# 공통 에이전트 지침

이 파일은 이 저장소에서 작업하는 Codex와 Claude를 포함한 모든 코딩 에이전트의 공통 지침이다. Codex는 이 파일을 직접 사용하고, Claude는 루트 `CLAUDE.md`를 통해 이 파일을 불러온다.

## 작업 시작 전에

- 의미 있는 작업을 시작하기 전에 반드시 `.agent/PROJECT_STATE.md`를 끝까지 읽는다.
- 현재 아키텍처, 배포 상태, 진행 중인 일, 알려진 문제, 주요 결정은 `.agent/PROJECT_STATE.md`에 있다. 기억이나 추측보다 이 파일을 우선한다.
- 더 자세한 문서가 필요하면 `.docs/`를 확인한다.
- 사람 또는 자동화가 에이전트 없이 실행하는 방법과 엔트리 포인트는 `.docs/RUNBOOK.md`를 기준으로 한다.
- 아키텍처, 배포 상태, 활성 작업, 알려진 문제 또는 결정이 실질적으로 바뀌면 작업 종료 전에 `.agent/PROJECT_STATE.md`도 갱신한다.
- 비밀번호, 토큰, 쿠키, 인증 코드와 같은 비밀정보는 문서나 Git에 기록하지 않는다.

## 프로젝트 개요

이 프로젝트는 네이버 부동산 매물을 수집하고 조건에 맞는 매물과 급매를 판별한 뒤, 카카오톡 메시지와 웹 화면(매물 리포트 · 가격 통계)으로 전달한다.

**역할이 둘로 갈려 있다. 이 경계를 흐리지 않는다.**

- `real-estate-finder/`: **수집 전용.** 네이버에서 본 매물을 판정 없이 전량 `report-site` API로 넘긴다. 조건 판정, 상태, 표현, 전송 코드가 없다.
- `report-site/`: **애플리케이션.** PostgreSQL에 원본을 전부 저장하고, 조건 필터·급매/신규/알림 판정·상태 갱신을 하고, 웹 리포트와 가격 통계를 렌더링하고, 카카오 메시지를 만들어 보낸다. 내부는 `properties/`(도메인) · `api/`(수집기 전용 경계) · `report/`(공개 화면)으로 나뉜다.
- `kakao-notifier/`: 카카오 인증, 토큰 관리, 메시지 전송
- 공개 리포트는 `report-site/`를 Tailscale Funnel로 노출한 주소를 쓴다. 실제 주소는 `.agent/PROJECT_STATE.md`에서 확인한다.
- 검색 조건은 PostgreSQL의 `SearchCondition`이며 Django admin에서 고친다. `report-site/properties/seed/searches.yaml`은 초기 시드일 뿐 운영 소스가 아니다.
- **스캔은 리포트 서버 실행을 요구한다.** 데이터가 갈 곳이 없기 때문이다. `run-scan.ps1`은 브라우저를 열기 전에 `/api/health/`를 확인하고 실패하면 멈춘다.

세부 운영 상태와 최신 조회 결과는 반드시 `.agent/PROJECT_STATE.md`에서 확인한다.

## 작업 원칙

아래 원칙은 Andrej Karpathy식의 규율 있는 코딩 접근을 이 프로젝트에 맞게 재구성한 것이며, 원문을 그대로 인용한 규칙은 아니다.

1. **코딩 전에 생각한다.** 관련 코드와 상태를 먼저 읽고, 성공 조건과 가정을 명확히 한다. 결과가 달라질 정도의 모호함만 질문한다.
2. **가장 단순한 해법을 선택한다.** 현재 요구를 만족하는 최소 변경을 선호하고, 추측성 추상화나 불필요한 의존성을 추가하지 않는다.
3. **변경 범위를 좁게 유지한다.** 요청과 직접 관련된 파일만 수정하고, 사용자 변경이나 무관한 포맷팅 및 리팩터링을 건드리지 않는다.
4. **목표와 증거로 완료를 판단한다.** 구현 후 실제 동작을 테스트하고, 확인하지 않은 내용을 완료했다고 말하지 않는다.
5. **작은 반복으로 진행한다.** 조사 → 계획 → 최소 수정 → 검증 → diff 검토 순서로 진행하며 각 단계에서 가정을 갱신한다.
6. **실패를 숨기지 않는다.** 테스트 실패, 환경 제약, 불확실성을 구체적으로 기록하고 안전한 대안을 제시한다.

## 프로젝트 작업 규칙

- 검색은 우선 `rg` 또는 `rg --files`를 사용한다.
- 기존 사용자 변경을 보존하고, 변경 전 `git status`를 확인한다.
- 생성 결과물은 소스와 구분하여 `.gitignore`로 관리한다.
- `report-site/`는 빌드·배포 단계가 없다. 요청마다 DB를 읽으므로 스캔 뒤 새로고침만으로 리포트가 갱신된다. 다만 **코드를 바꿨으면 `run-site.bat`을 재시작해야 한다** — 실행 중인 프로세스는 옛 코드를 들고 있다.
- 판정·표현·전송 코드를 `real-estate-finder/`로 되돌려 놓지 않는다. 그런 작업은 `report-site/properties/`에서 한다.
- 카카오톡의 공개 링크에는 `127.0.0.1`이나 `localhost`를 사용하지 않는다.
- 카카오 메시지의 `통계 보기`·`전체 매물 보기` 버튼은 리포트 서버(`report-site/`)가 현재 조회 시각과 일치하는 데이터를 서빙 중일 때만 포함한다. 이미지는 보내지 않는다.
- `report-site/.env`의 `REPORT_PATH_TOKEN`, `FINDER_API_TOKEN`, `POSTGRES_PASSWORD`와 루트 `.env`의 `KAKAO_REPORT_URL`은 Git에 커밋하지 않는다.
- 배포, 외부 메시지 전송, 토큰 갱신, Tailscale Funnel 설정은 대상과 결과를 확인하고 수행한다.
- 지금 개발은 `dev` 브랜치에서 진행한다(`kakao-image-card`는 더 이상 새 작업 대상이 아니다). 저장소 루트의 `VERSION` 파일이 현재 버전(`devX.Y.Z` 형식)을 담고 있으며, `dev` 브랜치에 푸시할 때마다 마지막 숫자를 1 증가시킨다.

## 주요 검증 명령

- 사용자용 메인 엔트리 포인트: `report-site\run-site.bat`을 먼저 켠 뒤 `real-estate-finder\run-scan.bat` 더블클릭
- 수집기 테스트: `real-estate-finder/`에서 `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
- 수집기 ↔ 서버 연결 확인: `real-estate-finder/`에서 `.\.venv\Scripts\python.exe -m real_estate_finder check-api` (읽기 전용)
- 애플리케이션 설정 검사: `report-site/`에서 `..\real-estate-finder\.venv\Scripts\python.exe manage.py check`
- 마이그레이션 누락 검사: `report-site/`에서 `..\real-estate-finder\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run`
- 애플리케이션 테스트: `report-site/`에서 `..\real-estate-finder\.venv\Scripts\python.exe manage.py test` (테스트 DB 생성 권한이 필요하다 — `.agent/PROJECT_STATE.md` 참고)

작업별로 필요한 최소 검증을 실행하고, 실행하지 못한 검증은 인계 내용에 명시한다.
