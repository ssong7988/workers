"""같은 날짜·수익률 축에 여러 자산분류를 겹쳐 그릴 SVG 좌표."""

from decimal import Decimal

from portfolio.allocation import SLICE_COLORS
from portfolio.display import signed_percent_text


def class_charts(series: list[dict]) -> dict:
    drawable = [row for row in series if len(row["points"]) >= 2]
    for index, row in enumerate(series):
        row["color"] = SLICE_COLORS[index % len(SLICE_COLORS)]
        row["available"] = len(row["points"]) >= 2
        row["observed"] = len(row["points"])
        row["first"] = row["points"][0]["day"] if row["points"] else None
        row["last"] = row["points"][-1]["day"] if row["points"] else None
        for key in ("return", "drawdown", "mdd"):
            value = row["points"][-1][key] if row["available"] else None
            row[f"{key}_text"] = signed_percent_text(value)
    if not drawable:
        return {"series": series, "charts": []}

    first = min(row["first"] for row in drawable)
    last = max(row["last"] for row in drawable)
    charts = []
    for key, title in (
        ("return", "수익률"),
        ("drawdown", "낙폭 · 관측 고점 대비"),
        ("mdd", "최대 낙폭 (MDD)"),
    ):
        values = [point[key] for row in drawable for point in row["points"]]
        values.append(Decimal("0"))
        low, high = min(values), max(values)
        if low == high:
            low, high = low - Decimal("0.01"), high + Decimal("0.01")

        def y_of(value: Decimal) -> float:
            return round(204 - float((value - low) / (high - low)) * 180, 2)

        lines = []
        for row in drawable:
            dots = [
                {
                    "x": round(
                        76 + (point["day"] - first).days / max(1, (last - first).days) * 624,
                        2,
                    ),
                    "y": y_of(point[key]),
                    "label": f'{point["day"]}: {signed_percent_text(point[key])}',
                }
                for point in row["points"]
            ]
            lines.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "color": row["color"],
                    "points": " ".join(f'{point["x"]},{point["y"]}' for point in dots),
                    "dots": dots,
                }
            )
        ticks = [
            {"y": y_of(value), "text": signed_percent_text(value)}
            for value in (low, (low + high) / 2, high)
        ]
        charts.append(
            {
                "key": key,
                "title": title,
                "lines": lines,
                "ticks": ticks,
                "zero": y_of(Decimal("0")),
            }
        )
    return {"series": series, "charts": charts, "first": first, "last": last}
