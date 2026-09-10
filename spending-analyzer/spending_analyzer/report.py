"""Render the analysis as one self-contained dashboard page.

No external fonts, scripts, or stylesheets — the file opens straight from disk.
`real_estate_finder/card.py` established this constraint in the repository and
it is what keeps the report free of a build step.

The palette follows the reference data-viz instance and was validated for both
modes. Three light-mode categorical slots fall below 3:1 against the surface, so
every segment carries a visible value and the full transaction table is always
present — identity never depends on color alone.
"""

from __future__ import annotations

import json
from pathlib import Path

from .charts import (
    Bar,
    Column,
    Segment,
    column_chart,
    diverging_bars,
    esc,
    format_man,
    format_percent,
    format_won,
    horizontal_bars,
    meter,
    stacked_bar,
)
from .models import UNCATEGORIZED

MONTH_TREND_LIMIT = 12
CATEGORY_LIMIT = 12
DELTA_LIMIT = 10

STYLE = """
:root {
  color-scheme: light;
  --surface-0: #f4f4f1;
  --surface-1: #fcfcfb;
  --border:    #e2e1dc;
  --text-primary:   #0b0b0b;
  --text-secondary: #52514e;
  --text-muted:     #83827c;
  --series-1: #2a78d6;
  --series-2: #eb6834;
  --series-3: #1baf7a;
  --series-4: #eda100;
  --series-5: #e87ba4;
  --seq-mid:  #2a78d6;
  --seq-soft: #9ec5f4;
  --accent-2: #eb6834;
  --diverge-up:   #d03b3b;
  --diverge-down: #2a78d6;
  --status-critical: #d03b3b;
  --status-good:     #0ca30c;
  --track: #e8e7e3;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --surface-0: #111110;
    --surface-1: #1a1a19;
    --border:    #33332f;
    --text-primary:   #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted:     #8f8e85;
    --series-1: #3987e5;
    --series-2: #d95926;
    --series-3: #199e70;
    --series-4: #c98500;
    --series-5: #d55181;
    --seq-mid:  #3987e5;
    --seq-soft: #1c5cab;
    --accent-2: #d95926;
    --diverge-up:   #e66767;
    --diverge-down: #3987e5;
    --status-critical: #d03b3b;
    --status-good:     #0ca30c;
    --track: #2a2a27;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface-0: #111110;
  --surface-1: #1a1a19;
  --border:    #33332f;
  --text-primary:   #ffffff;
  --text-secondary: #c3c2b7;
  --text-muted:     #8f8e85;
  --series-1: #3987e5;
  --series-2: #d95926;
  --series-3: #199e70;
  --series-4: #c98500;
  --series-5: #d55181;
  --seq-mid:  #3987e5;
  --seq-soft: #1c5cab;
  --accent-2: #d95926;
  --diverge-up:   #e66767;
  --diverge-down: #3987e5;
  --status-critical: #d03b3b;
  --status-good:     #0ca30c;
  --track: #2a2a27;
}

* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px 16px 64px;
  background: var(--surface-0); color: var(--text-primary);
  font-family: "Pretendard", "Malgun Gothic", "맑은 고딕", -apple-system, "Segoe UI", sans-serif;
  font-size: 14px; line-height: 1.5;
}
.wrap { max-width: 1100px; margin: 0 auto; }

header.page { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; }
header.page h1 { font-size: 20px; margin: 0; letter-spacing: -0.01em; }
header.page .meta { color: var(--text-muted); font-size: 13px; }
.spacer { flex: 1; }
button.theme {
  border: 1px solid var(--border); background: var(--surface-1);
  color: var(--text-secondary); border-radius: 8px; padding: 6px 12px;
  font: inherit; font-size: 13px; cursor: pointer;
}
button.theme:hover { color: var(--text-primary); }

section {
  background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 12px; padding: 18px 20px; margin-bottom: 16px;
}
section > h2 {
  font-size: 15px; margin: 0 0 4px; letter-spacing: -0.01em;
}
section > p.sub { margin: 0 0 16px; color: var(--text-muted); font-size: 13px; }

.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
.kpi { padding: 4px 0; }
.kpi .label { color: var(--text-muted); font-size: 13px; }
.kpi .value { font-size: 24px; font-weight: 650; letter-spacing: -0.02em; margin-top: 2px; }
.kpi .value.hero { font-size: 40px; line-height: 1.1; }
.kpi .note { color: var(--text-secondary); font-size: 13px; margin-top: 2px; }
.up   { color: var(--diverge-up); }
.down { color: var(--diverge-down); }

svg.chart { width: 100%; height: auto; display: block; overflow: visible; }
.chart .axis, .chart .row-label { fill: var(--text-secondary); font-size: 12px; }
.chart .bar-value, .chart .row-value { fill: var(--text-primary); font-size: 12px; font-variant-numeric: tabular-nums; }
.chart .bar-value { paint-order: stroke; stroke: var(--surface-1); stroke-width: 3px; stroke-linejoin: round; }
.chart .segment-label { fill: #fff; font-size: 12px; font-weight: 600; }
.chart .rule { stroke: var(--text-muted); stroke-width: 1; stroke-dasharray: 4 4; }
.chart .rule-label { fill: var(--text-muted); font-size: 11px; }
.chart .zero { stroke: var(--border); stroke-width: 1; }
.chart .mark path { stroke: var(--surface-1); stroke-width: 0; }
.chart .mark:hover path { opacity: 0.82; }

.legend { display: flex; flex-wrap: wrap; gap: 8px 18px; margin-top: 14px; font-size: 13px; color: var(--text-secondary); }
.legend-item { display: inline-flex; align-items: center; gap: 6px; }
.swatch { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }

.meter { margin-bottom: 14px; }
.meter-head { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; margin-bottom: 6px; }
.meter-value { color: var(--text-secondary); font-variant-numeric: tabular-nums; }
.meter-track { height: 10px; border-radius: 5px; background: var(--track); overflow: hidden; }
.meter-fill { height: 100%; border-radius: 5px; }

.table-tools { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.table-tools input {
  flex: 1; min-width: 200px; padding: 8px 12px; font: inherit;
  border: 1px solid var(--border); border-radius: 8px;
  background: var(--surface-0); color: var(--text-primary);
}
.table-tools .count { color: var(--text-muted); font-size: 13px; }
.scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; }
th { color: var(--text-secondary); font-weight: 600; position: sticky; top: 0; background: var(--surface-1); }
th.sortable { cursor: pointer; user-select: none; }
th.sortable:hover { color: var(--text-primary); }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
tbody tr:hover { background: var(--surface-0); }
.tag {
  display: inline-block; padding: 1px 8px; border-radius: 999px;
  background: var(--surface-0); border: 1px solid var(--border);
  color: var(--text-secondary); font-size: 12px;
}
.tag.warn { border-color: var(--accent-2); color: var(--accent-2); }
.empty { color: var(--text-muted); font-size: 13px; margin: 4px 0; }
.hint { color: var(--text-secondary); font-size: 13px; margin: 12px 0 0; }
"""

SCRIPT = """
(function () {
  var root = document.documentElement;
  var button = document.getElementById('theme-toggle');
  if (button) {
    button.addEventListener('click', function () {
      var dark = root.getAttribute('data-theme') === 'dark';
      root.setAttribute('data-theme', dark ? 'light' : 'dark');
    });
  }

  var search = document.getElementById('txn-search');
  var table = document.getElementById('txn-table');
  if (!table) return;
  var body = table.tBodies[0];
  var rows = Array.prototype.slice.call(body.rows);
  var count = document.getElementById('txn-count');

  function refresh() {
    var term = (search && search.value || '').trim().toLowerCase();
    var shown = 0;
    rows.forEach(function (row) {
      var hit = !term || row.textContent.toLowerCase().indexOf(term) !== -1;
      row.hidden = !hit;
      if (hit) shown++;
    });
    if (count) count.textContent = shown + ' / ' + rows.length + '건';
  }
  if (search) search.addEventListener('input', refresh);

  Array.prototype.forEach.call(table.querySelectorAll('th.sortable'), function (th, index) {
    var ascending = true;
    th.addEventListener('click', function () {
      var numeric = th.classList.contains('num');
      var column = Array.prototype.indexOf.call(th.parentNode.cells, th);
      rows.sort(function (a, b) {
        var x = a.cells[column].dataset.sort || a.cells[column].textContent;
        var y = b.cells[column].dataset.sort || b.cells[column].textContent;
        if (numeric) return (ascending ? 1 : -1) * (parseFloat(x) - parseFloat(y));
        return (ascending ? 1 : -1) * String(x).localeCompare(String(y), 'ko');
      });
      ascending = !ascending;
      rows.forEach(function (row) { body.appendChild(row); });
    });
  });

  refresh();
})();
"""


def _delta_class(value: int | None) -> str:
    if not value:
        return ""
    return "up" if value > 0 else "down"


def _kpi(label: str, value: str, note: str = "", note_class: str = "", hero: bool = False) -> str:
    note_html = f'<div class="note {note_class}">{esc(note)}</div>' if note else ""
    return (
        f'<div class="kpi"><div class="label">{esc(label)}</div>'
        f'<div class="value{" hero" if hero else ""}">{esc(value)}</div>{note_html}</div>'
    )


def _section(title: str, subtitle: str, body: str) -> str:
    sub = f'<p class="sub">{esc(subtitle)}</p>' if subtitle else ""
    return f"<section><h2>{esc(title)}</h2>{sub}{body}</section>"


def _summary(data: dict) -> str:
    months = data["months"]
    latest = months[-1] if months else None
    delta = latest["delta"] if latest else None
    percent = latest["percent"] if latest else None
    average = data["trailingAverage"]
    total = data["latestTotal"]
    gap = total - average

    kpis = [
        _kpi("이번 달 청구액", format_won(total), f"결제일 {data['paymentDate']}", hero=True),
        _kpi(
            "전월 대비",
            ("+" if (delta or 0) > 0 else "") + format_won(delta) if delta is not None else "—",
            format_percent(percent) if delta is not None else "직전 달 명세서가 없습니다",
            _delta_class(delta),
        ),
        _kpi(
            "최근 6개월 평균 대비",
            ("+" if gap > 0 else "") + format_won(gap),
            f"평균 {format_won(average)}",
            _delta_class(gap),
        ),
        _kpi("거래 건수", f"{latest['count']:,}건" if latest else "—"),
    ]
    return f'<section><div class="kpis">{"".join(kpis)}</div></section>'


def _trend(data: dict) -> str:
    months = data["months"][-MONTH_TREND_LIMIT:]
    latest = data["latest"]
    columns = [
        Column(
            label=item["month"][2:].replace("-", "."),
            value=item["total"],
            emphasis=item["month"] == latest,
            tooltip=f"{item['month']} {format_won(item['total'])} · {item['count']}건",
        )
        for item in months
    ]
    chart = column_chart(columns, average=data["trailingAverage"], title="월별 청구액")
    note = ""
    if len(months) < 3:
        note = (
            '<p class="hint">명세서가 아직 적어 추세를 보기 어렵습니다. '
            "삼성카드에 과거 명세서 재발송을 요청해 메일함에 쌓으면 그만큼 채워집니다.</p>"
        )
    return _section("월별 청구액 추이", "점선은 최근 6개월 평균입니다.", chart + note)


def _categories(data: dict) -> str:
    rows = [row for row in data["categories"] if row["total"] > 0][:CATEGORY_LIMIT]
    bars = [
        Bar(
            label=row["category"],
            value=row["total"],
            note=f"{row['share'] * 100:.0f}%",
            tooltip=f"{row['category']} {format_won(row['total'])} ({row['share'] * 100:.1f}%)",
        )
        for row in rows
    ]
    return _section(
        "카테고리별 지출", f"{data['latest']} 청구 기준", horizontal_bars(bars, title="카테고리별 지출")
    )


def _category_deltas(data: dict) -> str:
    changed = [row for row in data["categories"] if row["delta"]]
    if not changed:
        return _section(
            "카테고리별 전월 대비", "", '<p class="empty">비교할 직전 달 명세서가 없습니다.</p>'
        )
    changed.sort(key=lambda row: -abs(row["delta"]))
    bars = [
        Bar(
            label=row["category"],
            value=row["delta"],
            tooltip=(
                f"{row['category']} {format_won(row['previous'])} → {format_won(row['total'])}"
            ),
        )
        for row in changed[:DELTA_LIMIT]
    ]
    return _section(
        "카테고리별 전월 대비",
        "오른쪽(빨강)이 늘어난 쪽, 왼쪽(파랑)이 줄어든 쪽입니다.",
        diverging_bars(bars, title="카테고리별 전월 대비 증감"),
    )


def _payment_types(data: dict) -> str:
    rows = data["paymentTypes"][:5]
    segments = [
        Segment(label=row["type"], value=row["total"], slot=index + 1)
        for index, row in enumerate(rows)
    ]
    return _section("결제 유형 구성", f"{data['latest']} 청구 기준", stacked_bar(segments))


def _installments(data: dict) -> str:
    outlook = data["installments"]
    if not outlook["active"]:
        return _section(
            "할부 잔여 부담", "", '<p class="empty">진행 중인 할부가 없습니다.</p>'
        )

    projection = [
        Column(
            label=item["month"][2:].replace("-", "."),
            value=item["total"],
            tooltip=f"{item['month']} 할부 청구 예정 {format_won(item['total'])}",
        )
        for item in outlook["byMonth"]
    ]
    kpis = (
        '<div class="kpis">'
        + _kpi("앞으로 나갈 할부 총액", format_won(outlook["futureTotal"]))
        + _kpi("진행 중인 할부", f"{len(outlook['active'])}건")
        + "</div>"
    )
    rows = "".join(
        f"<tr><td>{esc(row['merchant'])}</td>"
        f'<td class="num" data-sort="{row["totalWon"]}">{esc(format_won(row["totalWon"]))}</td>'
        f"<td>{row['sequence']}/{row['months']}회차</td>"
        f'<td class="num" data-sort="{row["perMonth"]}">{esc(format_won(row["perMonth"]))}</td>'
        f'<td class="num" data-sort="{row["remainingWon"]}">{esc(format_won(row["remainingWon"]))}</td>'
        "</tr>"
        for row in outlook["active"]
    )
    table = (
        '<div class="scroll"><table><thead><tr>'
        "<th>가맹점</th><th class=\"num\">총 이용금액</th><th>회차</th>"
        '<th class="num">월 청구</th><th class="num">남은 금액</th>'
        f"</tr></thead><tbody>{rows}</tbody></table></div>"
    )
    chart = column_chart(projection, title="할부 청구 예정")
    return _section(
        "할부 잔여 부담",
        "이번 달 명세서에 남아 있는 할부가 앞으로 몇 달간 얼마씩 더 나가는지입니다.",
        kpis + chart + table,
    )


def _fixed_costs(data: dict) -> str:
    fixed = data["fixedCosts"]
    if not fixed["available"]:
        return _section(
            "고정비 / 변동비",
            "",
            '<p class="empty">'
            f"판정에는 명세서 {fixed['required']}개월치가 필요합니다 "
            f"(현재 {fixed['months']}개월).</p>",
        )
    segments = [
        Segment(label="고정비", value=fixed["fixedTotal"], slot=1),
        Segment(label="변동비", value=fixed["variableTotal"], slot=2),
    ]
    rows = "".join(
        f"<tr><td>{esc(row['merchant'])}</td><td>{esc(row['category'])}</td>"
        f"<td>{row['monthsSeen']}개월</td>"
        f'<td class="num" data-sort="{row["average"]}">{esc(format_won(row["average"]))}</td>'
        "</tr>"
        for row in fixed["merchants"][:20]
    )
    table = (
        '<div class="scroll"><table><thead><tr>'
        '<th>가맹점</th><th>카테고리</th><th>등장</th><th class="num">월평균</th>'
        f"</tr></thead><tbody>{rows}</tbody></table></div>"
    )
    return _section(
        "고정비 / 변동비",
        f"최근 {fixed['months']}개월 중 과반에 등장한 가맹점을 고정비로 봅니다.",
        stacked_bar(segments) + table,
    )


def _merchants(data: dict) -> str:
    bars = [
        Bar(
            label=row["merchant"],
            value=row["total"],
            note=f"{row['count']}건",
            tooltip=f"{row['example']} · {row['count']}건 · 평균 {format_won(row['average'])}",
        )
        for row in data["topMerchants"]
    ]
    return _section(
        "가맹점 TOP",
        "체인점은 지점을 합쳐 한 곳으로 셉니다.",
        horizontal_bars(bars, title="가맹점별 지출"),
    )


def _budgets(data: dict) -> str:
    if not data["budgets"]:
        return ""
    meters = "".join(
        meter(row["spent"], row["budget"], label=row["category"]) for row in data["budgets"]
    )
    return _section("예산 소진율", f"{data['latest']} 청구 기준", meters)


def _transactions(data: dict) -> str:
    rows = sorted(data["transactions"], key=lambda item: -item["billed_won"])
    body = "".join(
        f"<tr><td>{esc(item['used_at'])}</td>"
        f"<td>{esc(item['merchant'])}</td>"
        f"<td><span class=\"tag{' warn' if item['category'] == UNCATEGORIZED else ''}\">"
        f"{esc(item['category'])}</span></td>"
        f"<td>{esc(item['payment_type'])}"
        + (
            f" {item['installment_seq']}/{item['installment_months']}"
            if item["installment_months"] > 1
            else ""
        )
        + "</td>"
        f'<td class="num" data-sort="{item["billed_won"]}">{esc(format_won(item["billed_won"]))}</td>'
        "</tr>"
        for item in rows
    )
    tools = (
        '<div class="table-tools">'
        '<input id="txn-search" type="search" placeholder="가맹점, 카테고리로 검색" '
        'autocomplete="off">'
        '<span class="count" id="txn-count"></span></div>'
    )
    table = (
        '<div class="scroll"><table id="txn-table"><thead><tr>'
        '<th class="sortable">이용일</th><th class="sortable">가맹점</th>'
        '<th class="sortable">카테고리</th><th class="sortable">결제</th>'
        '<th class="sortable num">청구액</th>'
        f"</tr></thead><tbody>{body}</tbody></table></div>"
    )
    return _section("전체 거래", "머리글을 누르면 정렬됩니다.", tools + table)


def _uncategorized(data: dict) -> str:
    rows = data["uncategorized"]
    if not rows:
        return _section("미분류 가맹점", "", '<p class="empty">미분류 거래가 없습니다.</p>')
    body = "".join(
        f"<tr><td>{esc(row['example'])}</td>"
        f"<td>{esc(row['merchant'])}</td>"
        f"<td class=\"num\">{row['count']}건</td>"
        f'<td class="num" data-sort="{row["total"]}">{esc(format_won(row["total"]))}</td>'
        "</tr>"
        for row in rows[:30]
    )
    table = (
        '<div class="scroll"><table><thead><tr>'
        '<th>가맹점</th><th>매칭 키</th><th class="num">건수</th><th class="num">합계</th>'
        f"</tr></thead><tbody>{body}</tbody></table></div>"
    )
    hint = (
        '<p class="hint">여기 보이는 이름을 <code>config/rules.yaml</code>의 키워드로 넣으면 '
        "다음부터 자동 분류됩니다. <code>categorize --promote</code>가 자동 분류 결과를 "
        "같은 파일에 넣어 주기도 합니다.</p>"
    )
    return _section(
        "미분류 가맹점", "합계가 큰 순서입니다. 위쪽부터 규칙에 넣는 게 효율적입니다.", table + hint
    )


def render_html(data: dict) -> str:
    if data.get("empty", True):
        inner = (
            "<h1>소비 분석</h1>"
            '<section><p class="empty">아직 저장된 명세서가 없습니다. '
            "<code>python -m spending_analyzer scan-mail</code>로 메일을 확인한 뒤 "
            "<code>fetch</code>를 실행하세요.</p></section>"
        )
        return (
            f"<!doctype html><html lang=ko><head><meta charset=utf-8>"
            f'<meta name=viewport content="width=device-width,initial-scale=1">'
            f"<title>소비 분석</title><style>{STYLE}</style></head>"
            f'<body><div class="wrap">{inner}</div></body></html>'
        )

    header = (
        '<header class="page">'
        f"<h1>소비 분석 · {esc(data['latest'])}</h1>"
        f'<span class="meta">생성 {esc(data["generatedAt"][:16].replace("T", " "))}</span>'
        '<span class="spacer"></span>'
        '<button class="theme" id="theme-toggle" type="button">라이트 / 다크</button>'
        "</header>"
    )

    sections = "".join(
        [
            _summary(data),
            _trend(data),
            _categories(data),
            _category_deltas(data),
            _payment_types(data),
            _installments(data),
            _fixed_costs(data),
            _merchants(data),
            _budgets(data),
            _transactions(data),
            _uncategorized(data),
        ]
    )

    return (
        "<!doctype html><html lang=ko><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>소비 분석 {esc(data['latest'])}</title>"
        f"<style>{STYLE}</style></head>"
        f'<body><div class="wrap">{header}{sections}</div>'
        f"<script>{SCRIPT}</script></body></html>"
    )


def write_report(data: dict, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".html.tmp")
    temporary.write_text(render_html(data), encoding="utf-8")
    temporary.replace(output)
    return output


def load_analysis(path: Path) -> dict:
    if not path.exists():
        raise ValueError(f"분석 결과가 없습니다: {path}\n먼저 analyze를 실행하세요.")
    return json.loads(path.read_text(encoding="utf-8"))
