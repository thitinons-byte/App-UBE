"""Business permissions and UI role gates remain enforced with SQLite."""

from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest
from streamlit.runtime.context import ContextProxy
from streamlit.testing.v1 import AppTest

from src.approval import Action, Status
from src.permissions import AuthorizationError, Permission, Role, has_permission, require_permission


APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def test_role_matrix_and_unknown_values():
    assert {permission for permission in Permission if has_permission(Role.USER, permission)} == {
        Permission.VIEW_DASHBOARD, Permission.CREATE_REPORT, Permission.SUBMIT_REPORT,
    }
    assert {permission for permission in Permission if has_permission(Role.APPROVER, permission)} == {
        Permission.VIEW_DASHBOARD, Permission.CREATE_REPORT, Permission.SUBMIT_REPORT,
        Permission.APPROVE_REPORT,
    }
    assert all(has_permission(Role.ADMIN, permission) for permission in Permission)
    assert not has_permission("unknown", Permission.APPROVE_REPORT)
    with pytest.raises(AuthorizationError):
        require_permission(Role.USER, Permission.VIEW_ADMIN)


def test_user_cannot_approve_in_repository(isolated_app_database):
    repository = isolated_app_database
    repository.insert_report({
        "report_id": "ST-20261103-0001", "talk_date": "2026-11-03", "company": "UBE",
        "department": "ผลิต", "reporter": "ผู้สาธิต", "topic": "Safety Talk",
        "participants": 1, "evidence_files": "[]", "created_at": "2026-11-03T10:00:00",
    }, owner="demo_user")
    repository.transition("ST-20261103-0001", Action.SUBMIT, actor="demo_user", role=Role.USER)
    with pytest.raises(AuthorizationError):
        repository.transition("ST-20261103-0001", Action.APPROVE, actor="demo_user", role=Role.USER)
    assert repository.get_status("ST-20261103-0001") is Status.PENDING


def test_app_admin_gate_and_approver_queue(isolated_app_database):
    with patch.object(ContextProxy, "url", new_callable=PropertyMock,
                      return_value="http://localhost:8501/"):
        app = AppTest.from_file(str(APP_PATH)).run()
        assert not any(button.key == "menu_Admin (DEMO)" for button in app.button)
        app.session_state.selected_page = "Admin (DEMO)"
        app.run()
        assert any("ไม่มีสิทธิ์" in error.value for error in app.error)
        app.session_state.selected_page = "บันทึก Safety Talk"
        app.run()
        app.selectbox(key="current_demo_user").select("demo_approver").run()
        assert any(button.key == "menu_Approval Queue" for button in app.button)
        app.selectbox(key="current_demo_user").select("demo_admin").run()
        next(button for button in app.button if button.key == "menu_Admin (DEMO)").click().run()
        assert app.session_state.selected_page == "Admin (DEMO)"
        assert not app.exception
