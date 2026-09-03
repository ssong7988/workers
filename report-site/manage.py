#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

from __future__ import annotations

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "report_site.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django를 불러오지 못했습니다. real-estate-finder/.venv를 활성화했는지 확인하세요."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
