# workers

관심 대상을 자동으로 수집해 카카오톡으로 알리고 로컬 페이지로 보는 앱들의 모노레포입니다.

## 프로젝트 구조

```text
outputs/
├── .docs/                # 아키텍처, 운영 절차, 구성요소별 상세 문서
├── real-estate-finder/   # 수집기. 네이버에서 본 매물을 그대로 넘긴다
├── report-site/          # 애플리케이션. DB, 판정, 웹 리포트, 가격 통계, 카카오 전송
├── dagster_project/      # 스캔 스케줄 실행기. report-site 스캔 API를 정해진 시각에 호출
├── spending-analyzer/    # 삼성카드 이용대금명세서 메일을 파싱해 소비를 분석
└── kakao-notifier/       # 카카오 인증, 토큰 관리, 메시지 전송
```

부동산 쪽은 역할이 둘로 갈려 있습니다. `real-estate-finder`는 **수집만** 합니다. 어떤 매물이 조건에 맞는지, 급매인지, 신규인지, 카카오톡을 보낼지, 화면에 어떻게 보일지는 전부 `report-site`(Django + PostgreSQL)가 결정합니다.

화면은 셋입니다. **매물 리포트**(`/property/report/`)는 지금 조건에 맞는 매물을, **가격 통계**(`/property/statistics/`)는 그동안 수집한 원본으로 만든 날짜별 호가 분포를, **공통 Dagster 운영 요약**(`/common/dagster/`)은 스캔 스케줄 실행 현황을 보여줍니다.

`spending-analyzer`는 별도 앱입니다. 삼성카드 이용대금명세서 메일을 읽어 소비를 분류하고 리포트를 만듭니다.

각 앱의 설치 및 실행 방법은 해당 폴더의 README에서 관리합니다.

## 운영 실행

정기 실행과 수동 job 실행은 공통 Dagster UI(`/common/dagster/console/`)가 기본입니다.
`scan_job`은 매물 수집, `morning_report_job`은 최신 수집 확인 후 전체 리포트
전송을 수행합니다. 서버 코드 재시작도 `restart_report_site_job`으로 실행합니다.

PC를 처음 켠 뒤에는 Dagster와 애플리케이션 서버만 시작합니다.

```text
1) report-site\run-site.bat       애플리케이션 서버
2) dagster_project\run-dagster.bat 스케줄러와 운영 UI
```

PowerShell에서는 저장소 루트에서 다음과 같이 실행할 수 있습니다.

```powershell
.\report-site\run-site.ps1
.\dagster_project\run-dagster.ps1
```

`run-scan.bat`과 `send-report.bat`은 Dagster를 쓸 수 없을 때의 수동 호환
진입점으로 남아 있습니다. 실제 스캔 흐름은 Python 함수가 소유하며 Dagster는
`.bat`/`.ps1`을 거치지 않고 각 앱의 Python 명령을 직접 실행합니다.

최초 설치와 문제 해결, 외부 공개 설정은 [수동 실행 매뉴얼](.docs/RUNBOOK.md)을, 코드 구조는 [아키텍처 문서](.docs/ARCHITECTURE.md)를 참고하세요. 구성요소별 상세 설명은 [문서 색인](.docs/README.md)에서 찾을 수 있습니다.
