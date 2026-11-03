"""Approval Queue reads and updates the temporary SQLite repository."""

from pathlib import Path
from unittest.mock import PropertyMock, patch

from streamlit.runtime.context import ContextProxy
from streamlit.testing.v1 import AppTest

from src.approval import Action, Status
from src.permissions import Role


APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def add_pending(repository, report_id, company, department, topic):
    repository.insert_report({
        "report_id": report_id, "talk_date": "2026-11-03", "company": company,
        "department": department, "reporter": "ผู้สาธิต", "topic": topic,
        "participants": 1, "evidence_files": "[]", "created_at": "2026-11-03T10:00:00",
    }, owner="demo_user")
    repository.transition(report_id, Action.SUBMIT, actor="demo_user", role=Role.USER)


def test_queue_filters_approve_and_reject_require_explicit_action(isolated_app_database):
    repository = isolated_app_database
    first = "ST-20261103-0001"
    second = "ST-20261103-0002"
    add_pending(repository, first, "UBE", "ผลิต", "เครื่องจักร")
    add_pending(repository, second, "UBS", "คลังสินค้า", "การเดิน")
    with patch.object(ContextProxy, "url", new_callable=PropertyMock,
                      return_value="http://localhost:8501/"):
        app = AppTest.from_file(str(APP_PATH)).run()
        assert not any(button.key == "menu_Approval Queue" for button in app.button)
        app.selectbox(key="current_demo_user").select("demo_approver").run()
        next(button for button in app.button if button.key == "menu_Approval Queue").click().run()
        assert len(app.dataframe[0].value) == 2
        assert repository.get_status(first) is Status.PENDING
        app.selectbox(key="queue_company").select("UBS").run()
        assert app.dataframe[0].value["บริษัท"].tolist() == ["UBS"]
        assert app.selectbox(key="queue_department").options == ["ทั้งหมด", "คลังสินค้า"]
        app.selectbox(key="queue_company").select("UBE").run()
        app.text_input(key="queue_search").set_value("เครื่องจักร").run()
        assert app.dataframe[0].value["Report ID"].tolist() == [first]
        next(button for button in app.button if button.key == "queue_approve").click().run()
        assert repository.get_status(first) is Status.APPROVED
        assert len(repository.get_history(first)) == 2
        app.text_input(key="queue_search").set_value("").run()
        app.selectbox(key="queue_company").select("UBS").run()
        next(button for button in app.button if button.key == "queue_reject").click().run()
        assert repository.get_status(second) is Status.PENDING
        app.text_area(key=f"queue_reject_reason_{second}").set_value("แก้รายละเอียด").run()
        next(button for button in app.button if button.key == "queue_reject").click().run()
        assert repository.get_status(second) is Status.PENDING
        app.checkbox(key=f"queue_reject_confirm_{second}").check().run()
        next(button for button in app.button if button.key == "queue_reject").click().run()
        assert repository.get_status(second) is Status.REJECTED
        assert repository.get_history(second)[-1]["comment"] == "แก้รายละเอียด"
        assert not repository.list_pending(Role.APPROVER)
        assert not app.exception
