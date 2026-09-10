"""Classify the merchants the rules did not recognize.

Only merchant *names* leave this machine — never an amount, a date, or a card
number. The result is cached and can be promoted into `rules.yaml`, so a given
merchant costs one API call ever, not one per month.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .categorize import RuleSet


# Classification is a simple judgement, so it runs at low effort. The categories
# and instructions are stable across months and go in the cached system prefix;
# only the merchant list varies per request.
NO_CREDENTIAL_HINT = (
    "Anthropic 자격증명이 없어 자동 분류를 건너뜁니다.\n"
    "  .env에 ANTHROPIC_API_KEY를 넣으세요 (console.anthropic.com에서 발급).\n"
    "  Claude Code 구독과 API는 별도 결제입니다."
)

SYSTEM_PROMPT = """당신은 한국 신용카드 명세서의 가맹점명을 소비 카테고리로 분류합니다.

입력은 명세서에 찍힌 가맹점명이며, 공백과 법인 표기가 제거되고 영문은 대문자로 통일된 상태입니다.
지점명이나 사업자 형태가 붙어 있을 수 있습니다. 예: "스타벅스과천점", "GS25역삼2호점".

규칙:
- 반드시 주어진 카테고리 목록 안에서만 고릅니다.
- 가맹점명만으로 업종을 알 수 없으면 "기타"를 고릅니다. 추측해서 그럴듯한 답을 만들지 마십시오.
- 이름에 업종 단서가 있으면 그것을 우선합니다. 예: "-의원", "-약국"은 의료, "-주유소"는 주유.
- 온라인 결제대행(PG) 이름이 앞에 붙어 있으면 뒤쪽의 실제 가맹점을 기준으로 판단합니다.
- 입력으로 받은 모든 가맹점에 대해 하나씩 답합니다. 빠뜨리지 마십시오."""


@dataclass
class ClassifyResult:
    assignments: dict[str, str] = field(default_factory=dict)
    requested: int = 0
    skipped_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def ran(self) -> bool:
        return not self.skipped_reason


def _explain(exc: BaseException) -> str:
    """Turn an SDK failure into something the reader can act on.

    A missing credential surfaces as a plain TypeError at call time rather than
    as an auth error class, so the message has to be read, not just the type.
    """
    name = type(exc).__name__
    text = str(exc).lower()
    missing = (
        "authentication" in text
        or "api_key" in text
        or "Authentication" in name
        or "PermissionDenied" in name
    )
    if missing:
        return NO_CREDENTIAL_HINT
    if "RateLimit" in name:
        return f"요청 한도에 걸렸습니다. 잠시 후 다시 실행하세요. ({name})"
    if "Connection" in name or "Timeout" in name:
        return f"네트워크 문제로 분류하지 못했습니다: {name}"
    return f"분류 요청이 실패했습니다: {name}: {exc}"


def _schema(categories: tuple[str, ...]) -> dict:
    return {
        "type": "json_schema",
        "schema": {
            "type": "object",
            "properties": {
                "assignments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "merchant": {"type": "string"},
                            "category": {"type": "string", "enum": list(categories)},
                        },
                        "required": ["merchant", "category"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["assignments"],
            "additionalProperties": False,
        },
    }


def classify_merchants(
    merchants: list[str],
    rules: RuleSet,
    *,
    model: str = "claude-opus-5",
    batch_size: int = 200,
) -> ClassifyResult:
    """Ask Claude for a category per merchant.

    Never raises for a missing key or package — the fallback is optional, and
    the rest of the pipeline is expected to keep working without it, leaving
    those merchants uncategorized.
    """
    result = ClassifyResult(requested=len(merchants))
    if not merchants:
        result.skipped_reason = "분류할 미분류 가맹점이 없습니다."
        return result
    try:
        import anthropic
    except ImportError:
        result.skipped_reason = "anthropic 패키지가 없어 자동 분류를 건너뜁니다."
        return result

    # An unset ANTHROPIC_API_KEY does not mean there are no credentials — the
    # SDK also resolves ANTHROPIC_AUTH_TOKEN and a stored profile. Let it try,
    # and only report a missing key when it actually fails to authenticate.
    try:
        client = anthropic.Anthropic()
    except Exception as exc:
        result.skipped_reason = _explain(exc)
        return result
    allowed = set(rules.categories)
    system = [
        {
            "type": "text",
            "text": f"{SYSTEM_PROMPT}\n\n카테고리 목록:\n" + "\n".join(f"- {c}" for c in rules.categories),
            # The prefix is identical every month, so each run after the first
            # reads it from cache instead of paying for it again.
            "cache_control": {"type": "ephemeral"},
        }
    ]

    for start in range(0, len(merchants), batch_size):
        batch = merchants[start : start + batch_size]
        try:
            response = client.messages.create(
                model=model,
                max_tokens=16000,
                system=system,
                output_config={"effort": "low", "format": _schema(rules.categories)},
                messages=[
                    {
                        "role": "user",
                        "content": "다음 가맹점을 분류하세요:\n" + "\n".join(batch),
                    }
                ],
            )
        except Exception as exc:  # the SDK raises several unrelated error types
            result.skipped_reason = _explain(exc)
            return result

        usage = getattr(response, "usage", None)
        if usage:
            result.input_tokens += getattr(usage, "input_tokens", 0) or 0
            result.output_tokens += getattr(usage, "output_tokens", 0) or 0
            result.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0

        text = next((block.text for block in response.content if block.type == "text"), "")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            result.skipped_reason = "분류 응답을 JSON으로 읽지 못했습니다."
            return result

        requested = set(batch)
        for item in payload.get("assignments", []):
            merchant = str(item.get("merchant", ""))
            category = str(item.get("category", ""))
            # Only keep answers for merchants actually asked about, in a
            # category that exists — a hallucinated pair must not reach the cache.
            if merchant in requested and category in allowed:
                result.assignments[merchant] = category

    return result


def describe_usage(result: ClassifyResult) -> str:
    if not result.ran:
        return result.skipped_reason
    covered = len(result.assignments)
    cached = f", 캐시 재사용 {result.cache_read_tokens:,}토큰" if result.cache_read_tokens else ""
    return (
        f"자동 분류 {covered}/{result.requested}건 "
        f"(입력 {result.input_tokens:,}토큰, 출력 {result.output_tokens:,}토큰{cached})"
    )
