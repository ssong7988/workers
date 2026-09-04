# Project Docs

장기 보존할 설계, 운영 절차, 조사 결과 등 상세 문서를 이 디렉터리에 둔다.

- 프로젝트 구조, 데이터 흐름, 의존 경계와 작업별 최소 읽기 경로는 `ARCHITECTURE.md`를 본다.
- 사람이 설치, 조회, 빌드, 배포하는 절차는 `RUNBOOK.md`를 본다.
- 네이버 화면 수집기, Edge/CDP, 수집 실패 진단과 API 전달은 `real-estate-finder/README.md`부터 본다.
- Django 애플리케이션, PostgreSQL 모델, 판정·통계·카카오 전송은 `report-site/README.md`부터 본다.
- 카카오 OAuth, 토큰 수명주기, 메시지 API와 Django 연동은 `kakao-notifier/README.md`부터 본다.
- Dagster 코드 구조, console 프록시, 스케줄과 수동 실행은 `dagster_project/README.md`부터 본다.
- 현재 상태와 의사결정 요약은 `../.agent/PROJECT_STATE.md`에 유지한다.
- 문서에는 토큰, 비밀번호, 쿠키, 인증 코드 등 비밀정보를 기록하지 않는다.
- 구현과 문서가 달라지면 같은 작업에서 함께 갱신한다.
