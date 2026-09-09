from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("portfolio", "0004_instrument_price_source_manualholding")]

    operations = [
        migrations.CreateModel(
            name="HableAccountDailyMetric",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("as_of", models.DateField(db_index=True, verbose_name="기준일")),
                ("market_value", models.DecimalField(decimal_places=2, max_digits=18, verbose_name="평가액")),
                ("deposit", models.DecimalField(decimal_places=2, default=0, max_digits=18, verbose_name="입금")),
                ("withdrawal", models.DecimalField(decimal_places=2, default=0, max_digits=18, verbose_name="출금")),
                ("investment_pl", models.DecimalField(decimal_places=2, max_digits=18, verbose_name="당일 투자손익")),
                ("daily_return", models.DecimalField(decimal_places=8, max_digits=12, verbose_name="일간 수익률")),
                ("account_cumulative_return", models.DecimalField(decimal_places=8, max_digits=12, verbose_name="계좌 누적 수익률")),
                ("imported_at", models.DateTimeField(auto_now=True, verbose_name="가져온 시각")),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="hable_daily_metrics", to="portfolio.investmentaccount")),
            ],
            options={"ordering": ("as_of", "account_id")},
        ),
        migrations.AddConstraint(
            model_name="hableaccountdailymetric",
            constraint=models.UniqueConstraint(fields=("account", "as_of"), name="unique_hable_metric_account_day"),
        ),
    ]
