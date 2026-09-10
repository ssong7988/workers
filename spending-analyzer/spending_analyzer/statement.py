"""Turn a decrypted 삼성카드 statement page into a `Statement`.

The detail list renders ten rows at a time behind a 더보기 control, so the page
must be paged to the end before anything is read. Two row shapes exist:

  일반 가맹점    div.name > p.store_word[title]   이용일 / 가맹점명
  교통 정산 묶음  div.name > p.store_N > span     청구일 / "교통-하이패스 N건 (기간)"

`div.name p` matches both, which is why the extractor keys on it rather than on
`p.store_word` — keying on the latter silently dropped the transit rows.

Each section carries its own 소계 with `#totEcnD*` (건수) and `#totSumAmD*`
(금액). Those are the yardstick: the rows this module returns must match them
exactly, or the statement is rejected rather than stored half-read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .categorize import normalize_merchant
from .models import Statement, Transaction, iso_now
from .securemail import SecureMailError, open_decrypted

# Section headings, mapped to the payment types the models use.
SECTION_TYPES = {
    "일시불": "일시불",
    "할부": "할부",
    "할부금융": "할부",
    "단기카드대출(현금서비스)": "현금서비스",
    "장기카드대출(카드론)": "현금서비스",
    "연회비/기타수수료": "연회비",
    "해외이용": "해외",
}

MORE_BUTTON = "a:has-text('더보기'), button:has-text('더보기')"
ROW_SELECTOR = "p.store_word"
SETTLE_QUIET_SECONDS = 1.5
SETTLE_TIMEOUT_SECONDS = 30.0

# Reads every section's 소계 and rows in one pass.
EXTRACT_JS = """
() => {
  const KNOWN = %s;
  const clean = s => (s || '').replace(/\\s+/g, ' ').trim();

  const sectionName = (ul) => {
    // The heading sits outside the list; walk ancestors and look back through
    // their earlier siblings for an exact section title.
    let node = ul;
    for (let depth = 0; node && depth < 6; depth++, node = node.parentElement) {
      let sib = node.previousElementSibling;
      for (let steps = 0; sib && steps < 8; steps++, sib = sib.previousElementSibling) {
        const text = clean(sib.textContent);
        for (const name of KNOWN) if (text === name) return name;
        const inner = [...sib.querySelectorAll('h2,h3,strong,p,span')]
          .map(e => clean(e.textContent));
        for (const name of KNOWN) if (inner.includes(name)) return name;
      }
    }
    return '';
  };

  const sections = [];
  for (const total of document.querySelectorAll('li.top_total')) {
    const ul = total.parentElement;
    if (!ul) continue;
    const countEl = total.querySelector('[id^=totEcnD]');
    const sumEl = total.querySelector('[id^=totSumAmD]');

    const rows = [];
    for (const li of ul.children) {
      if (li === total) continue;
      const name = li.querySelector('div.name p');
      if (!name) continue;
      const label = clean(name.getAttribute('title') || name.textContent);
      if (!label || label.includes('{{')) continue;
      const amount = li.querySelector('p.abs_em strong');
      const date = li.querySelector('p.td.date');
      const card = li.querySelector('p.td.clr');
      rows.push({
        merchant: label,
        amount: clean(amount && amount.textContent),
        // The label span (이용일 / 청구일) is hidden but still in textContent.
        date: clean(date && date.textContent),
        card: clean(card && card.textContent),
      });
    }

    sections.push({
      name: sectionName(ul),
      count: clean(countEl && countEl.textContent),
      sum: clean(sumEl && sumEl.textContent),
      rows: rows,
    });
  }

  // The page heads with "2026년 9월 총 결제금액 …원" and states the due date
  // separately as "결제일 26. 9. 13".
  const body = clean(document.body.textContent);
  const month = body.match(/(\\d{4})년\\s*(\\d{1,2})월\\s*총\\s*결제금액/);
  const paid = body.match(/총\\s*결제금액\\s*([\\d,]+)\\s*원/);
  const due = body.match(/결제일\\s*(\\d{2})\\.\\s*(\\d{1,2})\\.\\s*(\\d{1,2})/);
  return {
    sections,
    paidTotal: paid ? paid[1] : '',
    monthRaw: month ? month.slice(1, 3) : null,
    dueRaw: due ? due.slice(1, 4) : null,
  };
}
"""


class StatementParseError(RuntimeError):
    """The statement was opened but could not be read into rows that add up."""


def parse_won(text: str) -> int:
    """Read an amount as printed on the statement.

    Refunds print with a leading minus, and an empty cell means zero rather
    than a parse failure.
    """
    cleaned = (text or "").replace(",", "").replace("원", "").strip()
    if not cleaned:
        return 0
    match = re.search(r"-?\d+", cleaned)
    if not match:
        raise StatementParseError(f"금액을 읽지 못했습니다: {text!r}")
    return int(match.group())


def parse_used_at(text: str, billing_month: str) -> str:
    """Read a row's date, printed as `26. 8. 1` after a hidden 이용일/청구일 label."""
    match = re.search(r"(\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})", text or "")
    if not match:
        return f"{billing_month}-01"
    year, month, day = (int(part) for part in match.groups())
    return f"20{year:02d}-{month:02d}-{day:02d}"


def parse_card_last4(text: str) -> str:
    digits = re.findall(r"\d{4}", text or "")
    return digits[-1] if digits else ""


def parse_installment(label: str) -> tuple[int, int]:
    """Read `3/6회차` out of a row label, when it is an instalment."""
    match = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})\s*회", label or "")
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


@dataclass
class SectionResult:
    name: str
    payment_type: str
    declared_count: int
    declared_sum: int
    transactions: list[Transaction]

    @property
    def parsed_sum(self) -> int:
        return sum(item.billed_won for item in self.transactions)

    @property
    def matches(self) -> bool:
        return (
            len(self.transactions) == self.declared_count
            and self.parsed_sum == self.declared_sum
        )

    def describe(self) -> str:
        return (
            f"{self.name or '(구분 미상)'}: {len(self.transactions)}/{self.declared_count}건, "
            f"{self.parsed_sum:,}/{self.declared_sum:,}원"
        )


def _settle(page) -> int:
    """Wait until the rendered row count stops changing."""
    import time

    last = page.evaluate(f"() => document.querySelectorAll('{ROW_SELECTOR}').length")
    quiet_since = time.monotonic()
    started = time.monotonic()
    while time.monotonic() - quiet_since < SETTLE_QUIET_SECONDS:
        if time.monotonic() - started > SETTLE_TIMEOUT_SECONDS:
            break
        page.wait_for_timeout(300)
        now = page.evaluate(f"() => document.querySelectorAll('{ROW_SELECTOR}').length")
        if now != last:
            last, quiet_since = now, time.monotonic()
    return last


def _load_every_page(page, max_clicks: int = 60) -> int:
    """Click 더보기 until it is gone, so every row exists in the DOM."""
    more = page.locator(MORE_BUTTON)
    _settle(page)
    clicks = 0
    for _ in range(max_clicks):
        visible = [more.nth(i) for i in range(more.count()) if more.nth(i).is_visible()]
        if not visible:
            return clicks
        before = page.evaluate(f"() => document.querySelectorAll('{ROW_SELECTOR}').length")
        visible[0].click()
        after = _settle(page)
        clicks += 1
        if after == before:
            # The control is still there but adds nothing; stop rather than spin.
            return clicks
    raise StatementParseError(
        f"더보기를 {max_clicks}번 눌러도 목록이 끝나지 않았습니다."
    )


def _billing_month(month_raw, fallback: str) -> str:
    """The month the statement bills for, printed as `2026년 9월 총 결제금액`."""
    if not month_raw:
        return fallback
    year, month = (int(part) for part in month_raw)
    return f"{year:04d}-{month:02d}"


def _payment_date(due_raw) -> str:
    """The due date, printed with a two-digit year as `결제일 26. 9. 13`."""
    if not due_raw:
        return ""
    year, month, day = (int(part) for part in due_raw)
    return f"20{year:02d}-{month:02d}-{day:02d}"


def parse(
    content: bytes,
    password: str,
    *,
    source_ref: str = "",
    fallback_month: str = "",
) -> Statement:
    """Open, page through, and read one statement attachment."""
    known = "[" + ",".join(f'"{name}"' for name in SECTION_TYPES) + "]"
    with open_decrypted(content, password) as page:
        _load_every_page(page)
        data = page.evaluate(EXTRACT_JS % known)

    billing_month = _billing_month(data.get("monthRaw"), fallback_month)
    if not billing_month:
        raise StatementParseError(
            "청구월을 찾지 못했습니다. 명세서 서식이 바뀌었을 수 있습니다."
        )

    sections: list[SectionResult] = []
    for raw in data["sections"]:
        declared_count = int(re.sub(r"\D", "", raw["count"]) or 0)
        declared_sum = parse_won(raw["sum"])
        if not declared_count and not declared_sum and not raw["rows"]:
            continue  # a section with nothing in it

        payment_type = SECTION_TYPES.get(raw["name"], "기타")
        transactions = []
        for row in raw["rows"]:
            sequence, months = parse_installment(row["merchant"])
            billed = parse_won(row["amount"])
            transactions.append(
                Transaction(
                    billing_month=billing_month,
                    used_at=parse_used_at(row["date"], billing_month),
                    merchant=row["merchant"],
                    merchant_norm=normalize_merchant(row["merchant"]),
                    billed_won=billed,
                    total_won=billed * months if months > 1 else billed,
                    payment_type=payment_type,
                    installment_seq=sequence,
                    installment_months=months,
                    card_last4=parse_card_last4(row["card"]),
                )
            )
        sections.append(
            SectionResult(
                name=raw["name"],
                payment_type=payment_type,
                declared_count=declared_count,
                declared_sum=declared_sum,
                transactions=transactions,
            )
        )

    mismatched = [section for section in sections if not section.matches]
    if mismatched:
        detail = "\n  ".join(section.describe() for section in mismatched)
        raise StatementParseError(
            "명세서의 소계와 읽어낸 행이 맞지 않습니다. 저장하지 않았습니다.\n  " + detail
        )

    transactions = [item for section in sections for item in section.transactions]
    declared_total = parse_won(data.get("paidTotal", "")) or sum(
        section.declared_sum for section in sections
    )

    return Statement(
        billing_month=billing_month,
        payment_date=_payment_date(data.get("dueRaw")),
        total_billed_won=declared_total,
        transactions=transactions,
        source_ref=source_ref,
        parsed_at=iso_now(),
    )


__all__ = [
    "SecureMailError",
    "SectionResult",
    "Statement",
    "StatementParseError",
    "parse",
    "parse_card_last4",
    "parse_installment",
    "parse_used_at",
    "parse_won",
]
