"""Shared test fixtures: isolate the SQLite DB to a temp file."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def temp_db():
    """Point history storage at a throwaway DB for every test."""
    path = Path(tempfile.gettempdir()) / f"doctor_test_{uuid.uuid4().hex}.db"
    original = settings.db_path
    settings.db_path = str(path)
    yield
    settings.db_path = original
    try:
        path.unlink(missing_ok=True)
    except PermissionError:  # pragma: no cover - Windows may still hold the handle
        pass
