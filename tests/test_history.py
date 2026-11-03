"""History filters, visibility, detail, and read-only SQLite access."""

import hashlib
from datetime import date
from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest
from streamlit.runtime.context import ContextProxy
from streamlit.testing.v1 import AppTest

from src.approval import Action, Status
from src.permissions import AuthorizationError, Role


APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


@pytest.fixture(autouse=True)
def localhost_context():
    with patch.object(ContextProxy, "url", new_callable=PropertyMock,
                      return_value="http://localhost:8501/"):
        yield


def add_report(repository, report_id, company, department, reporter, topic,
               talk_date="2026-11-03", owner="demo_user"):
    repository.insert_report({
        "report_id": report_id, "talk_date": talk_date, "company": company,
        "department": department, "reporter": reporter, "topic": topic,
        "participants": 1, "evidence_files": "[]", "created_at": "2026-11-03T10:00:00",
    }, owner=owner)


def open_history():
    app = AppTest.from_file(str(APP_PATH)).run()
    next(button for button in app.button if button.key == "menu_ประวัติรายงาน").click().run()
    return app


def test_search_filters_and_detail_ui(isolated_app_database):
    repository = isolated_app_database
    first = "ST-20261101-0001"
    second = "ST-20261102-0001"
    add_report(repository, first, "UBE", "ผลิต", "ผู้สาธิต ก", "อัคคีภัย", "1/11/2026")
    add_report(repository, second, "UBS", "คลังสินค้า", "ผู้สาธิต ข", "เครื่องจักร")
    repository.transition(second, Action.SUBMIT, actor="demo_user", role=Role.USER)
    add_report(repository, "ST-20261103-0001", "UBE", "ผลิต", "คนอื่น", "ไม่ควรเห็น",
               owner="demo_approver")
    app = open_history()
    assert len(app.dataframe[0].value) == 2
    app.text_input(key="history_search").set_value("เครื่องจักร").run()
    assert app.dataframe[0].value["Report ID"].tolist() == [second]
    app.text_input(key="history_search").set_value("").run()
    assert not app.exception, [item.message for item in app.exception]
    app.selectbox(key="history_company").select("UBE").run()
    assert app.selectbox(key="history_department").options == ["ทั้งหมด", "ผลิต"]
    app.selectbox(key="history_status").select("Draft").run()
    app.date_input(key="history_date_from").set_value(date(2026, 11, 1)).run()
    app.date_input(key="history_date_to").set_value(date(2026, 11, 1)).run()
    assert app.dataframe[0].value["Report ID"].tolist() == [first]
    next(button for button in app.button if button.key == "history_open_detail").click().run()
    assert app.session_state.selected_page == "รายละเอียดรายงาน"
    assert any("ST-20261101-0001" in item.value for item in app.subheader)
    assert any("ยังไม่มี Approval History" in item.value for item in app.markdown)
    assert not app.exception


def test_empty_states_for_no_visible_and_no_matching_reports(isolated_app_database):
    app = open_history()
    assert not app.dataframe
    assert any("ไม่พบรายงานที่แสดงได้" in item.value for item in app.markdown)
    add_report(isolated_app_database, "ST-20261103-0001", "UBE", "ผลิต",
               "ผู้สาธิต", "ทดสอบ")
    app.run()
    app.text_input(key="history_search").set_value("ไม่มีคำนี้").run()
    assert not app.exception, [item.message for item in app.exception]
    assert not app.dataframe
    assert any("ไม่พบรายงานที่แสดงได้" in item.value for item in app.markdown)
    assert not app.exception


def test_company_switch_resets_department_and_approver_sees_action_history(isolated_app_database):
    repo = isolated_app_database
    first = "ST-20261101-0001"
    second = "ST-20261102-0001"
    add_report(repo, first, "UBE", "ผลิต", "User", "Fire", owner="demo_user")
    add_report(repo, second, "UBS", "คลังสินค้า", "Other", "Machine",
               owner="demo_approver")
    repo.transition(first, Action.SUBMIT, actor="demo_user", role=Role.USER)
    app = open_history()
    app.selectbox(key="current_demo_user").select("demo_approver").run()
    assert len(app.dataframe[0].value) == 2
    app.selectbox(key="history_company").select("UBE").run()
    app.selectbox(key="history_department").select("ผลิต").run()
    app.selectbox(key="history_company").select("UBS").run()
    assert app.selectbox(key="history_department").value == "ทั้งหมด"
    assert app.selectbox(key="history_department").options == ["ทั้งหมด", "คลังสินค้า"]
    app.selectbox(key="history_company").select("UBE").run()
    app.selectbox(key="history_status").select("Pending").run()
    assert app.dataframe[0].value["Report ID"].tolist() == [first]
    next(button for button in app.button if button.key == "history_open_detail").click().run()
    assert app.session_state.selected_page == "รายละเอียดรายงาน"
    assert any("Pending" in item.value for item in app.markdown)
    assert app.dataframe[0].value["ผู้ทำรายการ"].tolist() == ["demo_user"]
    assert not app.exception


def test_parameterized_search_scope_dates_status_and_read_only(isolated_app_database):
    repo = isolated_app_database
    first = "ST-20261101-0001"
    second = "ST-20261103-0001"
    hidden = "ST-20261104-0001"
    add_report(repo, first, "UBE", "ผลิต", "Alice", "Fire", "1/11/2026")
    add_report(repo, second, "UBS", "คลังสินค้า", "Bob", "Machines")
    add_report(repo, hidden, "UBE", "สโตร์กลาง", "Other", "Secret", owner=None)
    repo.transition(second, Action.SUBMIT, actor="demo_user", role=Role.USER)
    before = hashlib.sha256(repo.db_path.read_bytes()).hexdigest()
    assert [row["report_id"] for row in repo.search_history("demo_user", Role.USER)] == [second, first]
    assert [row["report_id"] for row in repo.search_history("demo_user", Role.USER,
                                                             query="alice")] == [first]
    assert [row["report_id"] for row in repo.search_history("demo_user", Role.USER,
                                                             query="ST-20261103")] == [second]
    assert repo.search_history("demo_user", Role.USER, query="' OR 1=1 --") == []
    assert [row["report_id"] for row in repo.search_history(
        "demo_user", Role.USER, company="UBE", department="ผลิต",
        date_from=date(2026, 11, 1), date_to=date(2026, 11, 1), status="Draft",
    )] == [first]
    assert repo.list_history_departments("demo_user", Role.USER, "UBE") == ["ผลิต"]
    assert repo.get_visible_report_detail(hidden, "demo_user", Role.USER) is None
    assert repo.get_visible_report_detail(second, "demo_user", Role.USER)[0]["status"] == Status.PENDING
    assert len(repo.search_history("demo_approver", Role.APPROVER)) == 3
    with pytest.raises(AuthorizationError):
        repo.search_history("demo_user", Role.ADMIN)
    after = hashlib.sha256(repo.db_path.read_bytes()).hexdigest()
    assert after == before
