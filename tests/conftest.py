"""Pytest bootstrap: Settings() is instantiated at import time in app.core.config."""

from __future__ import annotations

import os

# Required fields with no defaults — CI and bare `pytest` runs have no `.env`.
os.environ.setdefault("OPENAI_COMPAT_API_KEY", "pytest-dummy-openai-key")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://pytest:pytest@localhost:5432/pytest",
)
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "pytest-jwt-secret-key-at-least-32-chars",
)
