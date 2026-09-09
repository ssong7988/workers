"""Isolated settings for local tests when the app DB user cannot create databases."""

from .settings import *  # noqa: F403

DATABASES = {  # noqa: F405
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
}
