"""Form retries failed SQLite writes and does not duplicate on rerun."""

from datetime import date
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src.sqlite_storage import SQLiteRepository


APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def fill_form():
    app = AppTest.from_file(str(APP_PATH)).run()
    next(item for item in app.selectbox if item.label == "บริษัท *").select("UBE").run()
    department = next(item for item in app.selectbox if item.label == "หน่วยงาน *")
    department.select(department.options[0])
    app.date_input[0].set_value(date(2026, 11, 2))
    next(item for item in app.text_input if item.label == "ชื่อผู้รายงาน *").set_value("ผู้สาธิต")
    next(item for item in app.text_input if item.label == "หัวข้อ Safety Talk *").set_value("ทดสอบ")
    return app


def save(app):
    next(button for button in app.button if button.label == "บันทึกรายงาน").click().run()


def test_permission_error_allows_retry(isolated_app_database):
    original = SQLiteRepository.create_report
    attempts = []

    def fail_once(self, *args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise PermissionError("locked")
        return original(self, *args, **kwargs)

    with patch.object(SQLiteRepository, "create_report", fail_once):
        app = fill_form()
        save(app)
        assert len(app.error) == 1
        assert "SQLite" in app.error[0].value
        assert not isolated_app_database.list_reports()
        save(app)
    assert len(app.success) == 1
    assert len(isolated_app_database.list_reports()) == 1
    assert len(attempts) == 2


def test_success_and_rerun_do_not_save_twice(isolated_app_database):
    app = fill_form()
    save(app)
    assert not app.exception
    assert "ST-20261102-0001" in app.success[0].value
    assert len(isolated_app_database.list_reports()) == 1
    app.run()
    assert len(isolated_app_database.list_reports()) == 1
