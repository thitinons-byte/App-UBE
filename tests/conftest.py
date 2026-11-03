"""Keep every AppTest run on an isolated SQLite database."""

from pathlib import Path

import pytest

from src.sqlite_storage import SQLiteRepository


@pytest.fixture(autouse=True)
def isolated_app_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database = tmp_path / "safety_talk.sqlite3"
    SQLiteRepository(database).initialize()
    monkeypatch.setattr("src.sqlite_storage.DEFAULT_DB_PATH", database)
    monkeypatch.setattr("src.sqlite_storage.DEFAULT_UPLOADS_PATH", tmp_path / "uploads")
    return SQLiteRepository(database)
