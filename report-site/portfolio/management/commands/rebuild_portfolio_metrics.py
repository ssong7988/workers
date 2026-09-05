"""일별 성과를 처음부터 다시 계산한다.

admin에서 자산분류를 옮기거나, 뒤늦게 도착한 하루치를 넣은 뒤에 돌린다.
수집 API는 새 완전 수집일이 생길 때 자동으로 부르므로 평소에는 필요 없다.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from portfolio.importing import latest_complete_date
from portfolio.performance import rebuild_metrics


class Command(BaseCommand):
    help = "완전 수집일 전체의 수익률·투자손익·MDD를 다시 계산합니다."

    def handle(self, *args, **options) -> None:
        days = rebuild_metrics()
        latest = latest_complete_date()
        if not days:
            self.stdout.write("완전한 수집 결과가 없어 계산할 것이 없습니다.")
            return
        self.stdout.write(
            self.style.SUCCESS(f"{days}일치 성과를 계산했습니다. 최신 기준일 {latest}")
        )
