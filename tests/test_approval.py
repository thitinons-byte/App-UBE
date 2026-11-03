import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from src.approval import Action, ApprovalService, Status
from src.permissions import AuthorizationError, Role


REPORT_ID = "ST-20261103-0001"


class ApprovalServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state_path = Path(self.temporary.name) / "approval_state.json"
        self.service = ApprovalService(
            state_path=self.state_path,
            reports_reader=lambda: [{"report_id": REPORT_ID}],
        )

    def test_submit_and_approve_preserve_report_id_and_history(self):
        self.assertEqual(self.service.get_status(REPORT_ID), Status.DRAFT)
        self.assertFalse(self.state_path.exists())
        self.service.register_draft(REPORT_ID, "demo_user", Role.USER)
        self.assertEqual(self.service.get_owner(REPORT_ID), "demo_user")
        self.assertEqual(
            self.service.transition(REPORT_ID, Action.SUBMIT, Role.USER, "demo_user"),
            Status.PENDING,
        )
        self.assertEqual(
            self.service.transition(REPORT_ID, Action.APPROVE, Role.APPROVER, "demo_approver"),
            Status.APPROVED,
        )
        reloaded = ApprovalService(self.state_path, lambda: [{"report_id": REPORT_ID}])
        self.assertEqual(reloaded.get_status(REPORT_ID), Status.APPROVED)
        history = reloaded.get_history(REPORT_ID)
        self.assertEqual(len(history), 2)
        self.assertEqual([item["action"] for item in history], ["Submit", "Approve"])
        self.assertEqual([item["actor"] for item in history], ["demo_user", "demo_approver"])
        self.assertEqual(
            [(item["old_status"], item["new_status"]) for item in history],
            [("Draft", "Pending"), ("Pending", "Approved")],
        )
        self.assertTrue(all(set(item) == {
            "actor", "timestamp", "old_status", "new_status", "action", "comment"
        } for item in history))
        self.assertTrue(all(datetime.fromisoformat(item["timestamp"]).tzinfo for item in history))
        self.assertEqual(list(json.loads(self.state_path.read_text(encoding="utf-8"))), [REPORT_ID])

    def test_reject_requires_reason_then_revise(self):
        self.service.register_draft(REPORT_ID, "demo_user", Role.USER)
        self.service.transition(REPORT_ID, Action.SUBMIT, Role.USER, "demo_user")
        before = self.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "เหตุผล"):
            self.service.transition(REPORT_ID, Action.REJECT, Role.APPROVER, "demo_approver", "  ")
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertEqual(
            self.service.transition(REPORT_ID, Action.REJECT, Role.APPROVER, "demo_approver", "  กรุณาแก้ไข  "),
            Status.REJECTED,
        )
        self.assertEqual(self.service.get_history(REPORT_ID)[-1]["comment"], "กรุณาแก้ไข")
        self.assertEqual(
            self.service.transition(REPORT_ID, Action.REVISE, Role.USER, "demo_user"),
            Status.DRAFT,
        )
        self.assertEqual(self.service.get_history(REPORT_ID)[-1]["action"], "Revise")

    def test_rejects_wrong_role_status_or_report_without_writing(self):
        with self.assertRaises(AuthorizationError):
            self.service.transition(REPORT_ID, Action.APPROVE, Role.USER, "demo_user")
        with self.assertRaisesRegex(ValueError, "สถานะ"):
            self.service.transition(REPORT_ID, Action.APPROVE, Role.APPROVER, "demo_approver")
        with self.assertRaisesRegex(ValueError, "Report ID"):
            self.service.transition("ST-UNKNOWN", Action.SUBMIT, Role.USER, "demo_user")
        with self.assertRaisesRegex(ValueError, "ผู้ดำเนินการ"):
            self.service.transition(REPORT_ID, Action.SUBMIT, Role.USER, " ")
        self.assertFalse(self.state_path.exists())

        self.service.register_draft(REPORT_ID, "demo_user", Role.USER)
        self.service.transition(REPORT_ID, Action.SUBMIT, Role.USER, "demo_user")
        before = self.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "สถานะ"):
            self.service.transition(REPORT_ID, Action.SUBMIT, Role.USER, "demo_user")
        with self.assertRaises(AuthorizationError):
            self.service.transition(REPORT_ID, Action.REJECT, Role.USER, "demo_user", "เหตุผล")
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_submit_requires_registered_owner_and_keeps_one_history_event(self):
        self.assertIsNone(self.service.get_owner(REPORT_ID))
        with self.assertRaises(AuthorizationError):
            self.service.transition(REPORT_ID, Action.SUBMIT, Role.USER, "demo_user")
        self.assertFalse(self.state_path.exists())

        self.service.register_draft(REPORT_ID, "demo_user", Role.USER)
        before = self.state_path.read_bytes()
        with self.assertRaises(AuthorizationError):
            self.service.transition(REPORT_ID, Action.SUBMIT, Role.USER, "demo_approver")
        with self.assertRaises(ValueError):
            self.service.register_draft(REPORT_ID, "demo_approver", Role.USER)
        self.assertEqual(self.state_path.read_bytes(), before)

        self.service.transition(REPORT_ID, Action.SUBMIT, Role.USER, "demo_user")
        with self.assertRaises(ValueError):
            self.service.transition(REPORT_ID, Action.SUBMIT, Role.USER, "demo_user")
        self.assertEqual(self.service.get_status(REPORT_ID), Status.PENDING)
        self.assertEqual(len(self.service.get_history(REPORT_ID)), 1)


if __name__ == "__main__":
    unittest.main()
