"""YAML configuration loading and validation."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from .models import AiConfig, AnalysisConfig, AppConfig, MailConfig


def load_config(path: Path) -> AppConfig:
    if not path.exists():
        raise ValueError(f"설정 파일이 없습니다: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    mail_raw = raw.get("mail", {})
    mail = MailConfig(
        host=str(mail_raw.get("host", "imap.gmail.com")),
        port=int(mail_raw.get("port", 993)),
        folder=str(mail_raw.get("folder", "INBOX")),
        senders=tuple(str(v).strip() for v in mail_raw.get("senders", []) if str(v).strip()),
        subject_keywords=tuple(
            str(v).strip() for v in mail_raw.get("subject_keywords", []) if str(v).strip()
        ),
        since=str(mail_raw.get("since", "") or "").strip(),
    )

    analysis_raw = raw.get("analysis", {})
    budgets_raw = analysis_raw.get("budgets") or {}
    analysis = AnalysisConfig(
        fixed_cost_months=int(analysis_raw.get("fixed_cost_months", 3)),
        top_merchants=int(analysis_raw.get("top_merchants", 15)),
        budgets=tuple((str(k), int(v)) for k, v in budgets_raw.items()),
    )

    ai_raw = raw.get("ai", {})
    ai = AiConfig(
        enabled=bool(ai_raw.get("enabled", True)),
        model=str(ai_raw.get("model", "claude-opus-5")),
        batch_size=int(ai_raw.get("batch_size", 200)),
    )

    config = AppConfig(
        mail=mail,
        analysis=analysis,
        ai=ai,
        timezone=str(raw.get("timezone", "Asia/Seoul")),
    )
    validate_config(config)
    return config


def validate_config(config: AppConfig) -> None:
    if not config.mail.senders:
        raise ValueError("mail.senders에 명세서 발신 주소를 하나 이상 넣으세요.")
    if not 1 <= config.mail.port <= 65535:
        raise ValueError(f"mail.port가 범위를 벗어났습니다: {config.mail.port}")
    if config.mail.since:
        try:
            date.fromisoformat(config.mail.since)
        except ValueError as exc:
            raise ValueError(f"mail.since는 YYYY-MM-DD여야 합니다: {config.mail.since}") from exc
    if config.analysis.fixed_cost_months < 2:
        raise ValueError("analysis.fixed_cost_months는 2 이상이어야 합니다.")
    if config.analysis.top_merchants < 1:
        raise ValueError("analysis.top_merchants는 1 이상이어야 합니다.")
    if config.ai.batch_size < 1:
        raise ValueError("ai.batch_size는 1 이상이어야 합니다.")
    for name, amount in config.analysis.budgets:
        if amount < 0:
            raise ValueError(f"예산은 음수일 수 없습니다: {name}")
