import unittest
from pathlib import Path
from unittest.mock import PropertyMock, patch

from streamlit.runtime.context import ContextProxy
from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parent.parent / "app.py"
USERS = ["demo_user · USER", "demo_approver · APPROVER", "demo_admin · ADMIN"]


class DemoUserSwitcherTests(unittest.TestCase):
    def test_local_switcher_keeps_user_when_changing_menus(self):
        with patch.object(ContextProxy, "url", new_callable=PropertyMock, return_value="http://localhost:8501/"):
            app = AppTest.from_file(str(APP_PATH)).run()
            switcher = app.selectbox(key="current_demo_user")
            self.assertEqual(switcher.options, USERS)
            self.assertEqual(app.session_state.current_demo_user, "demo_user")
            self.assertTrue(any("DEMO MODE" in item.value and "NO AUTHENTICATION" in item.value for item in app.markdown))

            switcher.select("demo_approver").run()
            self.assertEqual(app.session_state.current_demo_user, "demo_approver")
            next(button for button in app.button if button.key == "menu_Dashboard").click().run()
            self.assertEqual(app.session_state.selected_page, "Dashboard")
            self.assertEqual(app.session_state.current_demo_user, "demo_approver")

            app.selectbox(key="current_demo_user").select("demo_admin").run()
            next(button for button in app.button if button.key == "menu_ประวัติรายงาน").click().run()
            self.assertEqual(app.session_state.selected_page, "ประวัติรายงาน")
            self.assertEqual(app.session_state.current_demo_user, "demo_admin")
            self.assertEqual(len(app.exception), 0)

    def test_nonlocal_url_has_no_switcher(self):
        with patch.object(ContextProxy, "url", new_callable=PropertyMock, return_value="http://192.0.2.10:8501/"):
            app = AppTest.from_file(str(APP_PATH)).run()
        self.assertFalse(any(item.key == "current_demo_user" for item in app.selectbox))
        self.assertNotIn("current_demo_user", app.session_state)
        self.assertEqual(len(app.exception), 0)


if __name__ == "__main__":
    unittest.main()
