"""Submitting a Draft changes its SQLite status without creating another report."""

from datetime import date
from pathlib import Path
from unittest.mock import PropertyMock, patch

from streamlit.runtime.context import ContextProxy
from streamlit.testing.v1 import AppTest

from src.approval import Status
from src.sqlite_storage import SQLiteRepository


APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def test_form_creates_owned_draft_and_submit_survives_refresh(isolated_app_database):
    with patch.object(ContextProxy, "url", new_callable=PropertyMock,
                      return_value="http://localhost:8501/"):
        app = AppTest.from_file(str(APP_PATH)).run()
        next(item for item in app.selectbox if item.label == "บริษัท *").select("UBE").run()
        department = next(item for item in app.selectbox if item.label == "หน่วยงาน *")
        department.select(department.options[0])
        app.date_input[0].set_value(date(2026, 11, 3))
        next(item for item in app.text_input if item.label == "ชื่อผู้รายงาน *").set_value("ผู้สาธิต")
        next(item for item in app.text_input if item.label == "หัวข้อ Safety Talk *").set_value("ทดสอบ")
        next(button for button in app.button if button.label == "บันทึกรายงาน").click().run()
        assert not app.exception
        rows = isolated_app_database.list_reports()
        assert len(rows) == 1
        report_id = rows[0]["report_id"]
        assert report_id == "ST-20261103-0001"
        assert isolated_app_database.get_owner(report_id) == "demo_user"
        assert isolated_app_database.get_status(report_id) is Status.DRAFT
        next(button for button in app.button if button.key == "menu_ประวัติรายงาน").click().run()
        next(button for button in app.button if button.key == "history_open_detail").click().run()
        next(button for button in app.button if button.label == "ส่งขออนุมัติ").click().run()
        refreshed = SQLiteRepository(isolated_app_database.db_path)
        assert refreshed.get_status(report_id) is Status.PENDING
        assert len(refreshed.get_history(report_id)) == 1
        assert len(refreshed.list_reports()) == 1
        assert any(report_id in item.value for item in app.success)
