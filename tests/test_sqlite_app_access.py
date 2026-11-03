import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from src.approval import Action, Status
from src.permissions import AuthorizationError, Role
from src.sqlite_storage import SQLiteRepository


class FakeUpload:
    name = "raw-name.png"

    def getvalue(self):
        return b"demo-image"


class SQLiteAppAccessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = SQLiteRepository(self.root / "reports.sqlite3")
        self.uploads = self.root / "uploads"
        self.report = {
            "talk_date": date(2026, 11, 3),
            "company": "UBE",
            "department": "ผลิตเอทานอล",
            "reporter": "ผู้สาธิต",
            "topic": "Safety Talk",
            "participants": 3,
        }

    def test_create_read_approve_and_refresh_preserve_id_and_files(self):
        self.repo.initialize()
        report_id = self.repo.create_report(
            self.report, [FakeUpload()], "demo_user", Role.USER, self.uploads
        )
        self.assertEqual(report_id, "ST-20261103-0001")
        saved = self.repo.get_report(report_id)
        self.assertEqual(saved["status"], "Draft")
        self.assertEqual(saved["owner_actor"], "demo_user")
        self.assertEqual(saved["participants"], 3)
        names = json.loads(saved["evidence_files"])
        self.assertEqual(len(names), 1)
        self.assertNotEqual(names[0], FakeUpload.name)
        self.assertTrue((self.uploads / names[0]).is_file())
        self.assertEqual(len(self.repo.list_reports()), 1)
        with self.assertRaises(AuthorizationError):
            self.repo.list_pending(Role.USER)

        self.assertEqual(self.repo.transition(
            report_id, Action.SUBMIT, "demo_user", Role.USER
        ), Status.PENDING)
        self.assertEqual(
            [row["report_id"] for row in self.repo.list_pending(Role.APPROVER)],
            [report_id],
        )
        self.assertEqual(self.repo.list_pending(Role.APPROVER)[0]["submitted_by"], "demo_user")
        self.assertEqual(self.repo.transition(
            report_id, Action.APPROVE, "demo_approver", Role.APPROVER
        ), Status.APPROVED)
        self.assertEqual(self.repo.list_pending(Role.APPROVER), [])

        refreshed = SQLiteRepository(self.repo.db_path)
        self.assertEqual(refreshed.get_status(report_id), Status.APPROVED)
        self.assertEqual([event["action"] for event in refreshed.get_history(report_id)], [
            "Submit", "Approve"
        ])
        self.assertEqual(refreshed.list_reports()[0]["report_id"], report_id)

    def test_next_report_id_uses_imported_sequence(self):
        self.repo.initialize()
        self.assertEqual(self.repo.create_report(
            self.report, [], "demo_user", Role.USER, self.uploads
        ), "ST-20261103-0001")
        self.assertEqual(self.repo.create_report(
            self.report, [], "demo_user", Role.USER, self.uploads
        ), "ST-20261103-0002")
        self.assertEqual(len(self.repo.list_reports()), 2)

    def test_missing_database_does_not_create_empty_file(self):
        with self.assertRaises(FileNotFoundError):
            self.repo.create_report(self.report, [], "demo_user", Role.USER, self.uploads)
        self.assertFalse(self.repo.db_path.exists())


if __name__ == "__main__":
    unittest.main()
