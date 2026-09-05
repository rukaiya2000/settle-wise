"""The Vercel entrypoint must not fall back to SQLite."""

import importlib
import sys

import pytest


def _fresh_import():
    sys.modules.pop("api.index", None)
    return importlib.import_module("api.index")


def test_entrypoint_refuses_to_start_without_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    with pytest.raises(RuntimeError, match="no SQLite fallback"):
        _fresh_import()


def test_entrypoint_exposes_the_app_when_configured(monkeypatch):
    # Any postgres URL: nothing connects at import time, so this only proves
    # the guard passes and the app object is exported.
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:6543/db")
    monkeypatch.setenv("SKIP_DB_INIT", "true")
    monkeypatch.setenv("ENABLE_VOICE", "false")
    mod = _fresh_import()
    assert hasattr(mod, "app")
