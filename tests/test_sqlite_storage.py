import csv
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from src.approval import Action, Status
from src.permissions import AuthorizationError, Role
from src.sqlite_storage import SQLiteRepository
from src.storage import CSV_COLUMNS


REPORT_ID = "ST-20261103-0001"
REPORT = {
    "report_id": REPORT_ID,
    "talk_date": "2026-11-03",
    "company": "UBE",
    "department": "ผลิตเอทานอล",
    "reporter": "ผู้สาธิต",
    "topic": "Safety Talk",
    "participants": "4",
    "evidence_files": '["example.png"]',
    "created_at": "2026-11-03T10:00:00",
}
HISTORY = [
    {
        "actor": "demo_user", "timestamp": "2026-11-03T03:00:00+00:00",
        "old_status": "Draft", "new_status": "Pending",
        "action": "Submit", "comment": "",
    },
    {
        "actor": "demo_approver", "timestamp": "2026-11-03T04:00:00+00:00",
        "old_status": "Pending", "new_status": "Approved",
        "action": "Approve", "comment": "ตรวจแล้ว",
    },
]


class SQLiteStorageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = SQLiteRepository(self.root / "safety_talk.db")
        self.csv_path = self.root / "reports.csv"
        self.state_path = self.root / "approval_state.json"
        with self.csv_path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerow(REPORT)
        self.state_path.write_text(json.dumps({
            REPORT_ID: {"owner": "demo_user", "status": "Approved", "history": HISTORY}
        }, ensure_ascii=False), encoding="utf-8")

    def test_schema_foreign_keys_and_full_legacy_import_are_read_only(self):
        csv_before = self.csv_path.read_bytes()
        state_before = self.state_path.read_bytes()
        self.assertEqual(self.repo.import_legacy(self.csv_path, self.state_path), 1)
        with closing(self.repo.connect()) as connection:
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            tables = {row["name"] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )}
            self.assertTrue({"reports", "users_demo", "approval_history"}.issubset(tables))
            roles = {row["user_id"]: row["role"] for row in connection.execute(
                "SELECT user_id, role FROM users_demo"
            )}
            self.assertEqual(roles, {
                "demo_user": "USER", "demo_approver": "APPROVER", "demo_admin": "ADMIN"
            })
            foreign_keys = connection.execute("PRAGMA foreign_key_list(approval_history)").fetchall()
            self.assertEqual({row["table"] for row in foreign_keys}, {"reports", "users_demo"})
            self.assertEqual(connection.execute(
                "SELECT actor_user_id FROM approval_history WHERE sequence = 2"
            ).fetchone()[0], "demo_approver")
        stored = self.repo.get_report(REPORT_ID)
        self.assertEqual({column: str(stored[column]) for column in CSV_COLUMNS}, REPORT)
        self.assertEqual(stored["status"], Status.APPROVED.value)
        self.assertEqual(stored["owner_actor"], "demo_user")
        self.assertEqual(stored["owner_user_id"], "demo_user")
        self.assertEqual(self.repo.get_history(REPORT_ID), HISTORY)
        self.assertIsNone(self.repo.get_report("' OR 1=1 --"))
        self.assertEqual(self.csv_path.read_bytes(), csv_before)
        self.assertEqual(self.state_path.read_bytes(), state_before)

    def test_fk_duplicate_id_and_import_rollback(self):
        self.repo.import_legacy(self.csv_path, self.state_path)
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.insert_report(REPORT)
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.import_legacy(self.csv_path, self.state_path)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.repo.transaction() as connection:
                connection.execute(
                    """INSERT INTO approval_history (
                        report_id, sequence, actor, timestamp, old_status,
                        new_status, action, comment
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    ("missing", 1, "demo_user", "2026-11-03T00:00:00+00:00",
                     "Draft", "Pending", "Submit", ""),
                )
        self.assertEqual(self.repo.get_history(REPORT_ID), HISTORY)
        with closing(self.repo.connect()) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM reports").fetchone()[0], 1)

    def test_transition_checks_role_status_and_rolls_back_status_with_history(self):
        self.repo.initialize()
        self.repo.insert_report(REPORT, owner="demo_user")
        self.assertEqual(self.repo.get_report(REPORT_ID)["status"], "Draft")
        with self.assertRaises(AuthorizationError):
            self.repo.transition(REPORT_ID, Action.APPROVE, "demo_user", Role.USER)
        with self.assertRaises(AuthorizationError):
            self.repo.transition(REPORT_ID, Action.SUBMIT, "demo_admin", Role.ADMIN)
        self.assertEqual(self.repo.transition(
            REPORT_ID, Action.SUBMIT, "demo_user", Role.USER
        ), Status.PENDING)
        with self.assertRaises(ValueError):
            self.repo.transition(REPORT_ID, Action.REJECT, "demo_approver", Role.APPROVER)
        with patch.object(self.repo, "_insert_history", side_effect=sqlite3.IntegrityError("failed")):
            with self.assertRaises(sqlite3.IntegrityError):
                self.repo.transition(REPORT_ID, Action.APPROVE, "demo_approver", Role.APPROVER)
        self.assertEqual(self.repo.get_report(REPORT_ID)["status"], "Pending")
        self.assertEqual(len(self.repo.get_history(REPORT_ID)), 1)
        self.assertEqual(self.repo.transition(
            REPORT_ID, Action.APPROVE, "demo_approver", Role.APPROVER
        ), Status.APPROVED)
        for action in Action:
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.repo.transition(REPORT_ID, action, "demo_admin", Role.ADMIN, "เหตุผล")
        self.assertEqual(self.repo.get_report(REPORT_ID)["status"], "Approved")
        self.assertEqual(len(self.repo.get_history(REPORT_ID)), 2)

    def test_import_rolls_back_all_rows_when_later_row_is_invalid(self):
        invalid_report = {
            **REPORT, "report_id": "ST-20261103-0002", "participants": "0"
        }
        with self.csv_path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows([REPORT, invalid_report])
        source_before = self.csv_path.read_bytes()
        with self.assertRaises(ValueError):
            self.repo.import_legacy(self.csv_path, self.state_path)
        with closing(self.repo.connect()) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM reports").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM approval_history").fetchone()[0], 0)
        self.assertEqual(self.csv_path.read_bytes(), source_before)


if __name__ == "__main__":
    unittest.main()
