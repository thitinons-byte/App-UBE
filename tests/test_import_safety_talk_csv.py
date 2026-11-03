import csv
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from io import StringIO
from pathlib import Path

from import_safety_talk_csv import main
from src.sqlite_storage import SQLiteRepository
from src.storage import CSV_COLUMNS


ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data" / "sample_safety_talk.csv"


def report(report_id: str, topic: str = "หัวข้อทดสอบ") -> dict[str, str]:
    return {
        "report_id": report_id,
        "talk_date": "2026-11-03",
        "company": "UBE",
        "department": "ผลิตเอทานอล",
        "reporter": "ผู้สาธิต",
        "topic": topic,
        "participants": "3",
        "evidence_files": "[]",
        "created_at": "2026-11-03T10:00:00",
    }


def write_csv(path: Path, rows: list[dict[str, str]], columns=CSV_COLUMNS) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def run_import(csv_path: Path, db_path: Path) -> dict[str, str]:
    output = StringIO()
    with redirect_stdout(output):
        result = main(["--csv", str(csv_path), "--db", str(db_path)])
    if result != 0:
        raise AssertionError("Import failed unexpectedly")
    return dict(line.split(": ", 1) for line in output.getvalue().splitlines())


class ImportSafetyTalkTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db_path = self.root / "safety_talk.sqlite3"
        self.repo = SQLiteRepository(self.db_path)

    def test_sample_twice_is_idempotent_and_second_run_creates_backup(self):
        source_hash = hashlib.sha256(SAMPLE.read_bytes()).hexdigest()
        source_count = sum(1 for _ in csv.DictReader(
            SAMPLE.open(encoding="utf-8-sig", newline="")
        ))
        first = run_import(SAMPLE, self.db_path)
        self.assertEqual(first["source_rows"], str(source_count))
        self.assertEqual(first["inserted"], str(source_count))
        self.assertEqual(first["skipped"], "0")
        self.assertEqual(first["invalid"], "0")
        self.assertEqual(first["total_after"], str(source_count))
        self.assertEqual(first["backup"], "-")

        second = run_import(SAMPLE, self.db_path)
        self.assertEqual(second["source_rows"], str(source_count))
        self.assertEqual(second["inserted"], "0")
        self.assertEqual(second["skipped"], str(source_count))
        self.assertEqual(second["invalid"], "0")
        self.assertEqual(second["total_after"], str(source_count))
        backup = Path(second["backup"])
        self.assertTrue(backup.is_file())
        with closing(SQLiteRepository(backup).connect()) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM reports").fetchone()[0], source_count)
        self.assertEqual(hashlib.sha256(SAMPLE.read_bytes()).hexdigest(), source_hash)

    def test_invalid_rows_counted_and_existing_record_never_overwritten(self):
        csv_path = self.root / "input.csv"
        original = report("ST-20261103-0001")
        write_csv(csv_path, [
            original,
            report("ST-20261340-0002"),
            report("BAD-ID"),
        ])
        first = run_import(csv_path, self.db_path)
        self.assertEqual(first["source_rows"], "3")
        self.assertEqual(first["inserted"], "1")
        self.assertEqual(first["invalid"], "2")
        self.assertEqual(first["total_after"], "1")

        changed = report("ST-20261103-0001", topic="ห้ามเขียนทับ")
        write_csv(csv_path, [changed, report("ST-20261103-0002")])
        second = run_import(csv_path, self.db_path)
        self.assertEqual(second["source_rows"], "2")
        self.assertEqual(second["inserted"], "1")
        self.assertEqual(second["skipped"], "1")
        self.assertEqual(second["invalid"], "0")
        self.assertEqual(second["total_after"], "2")
        self.assertEqual(self.repo.get_report("ST-20261103-0001")["topic"], original["topic"])
        backup = SQLiteRepository(Path(second["backup"]))
        self.assertIsNone(backup.get_report("ST-20261103-0002"))
        self.assertEqual(backup.get_report("ST-20261103-0001")["topic"], original["topic"])

    def test_reports_csv_auto_imports_approval_history_without_duplicates(self):
        csv_path = self.root / "reports.csv"
        state_path = self.root / "approval_state.json"
        report_id = "ST-20261103-0001"
        write_csv(csv_path, [report(report_id)])
        events = [
            {"actor": "demo_user", "timestamp": "2026-11-03T10:01:00+00:00",
             "old_status": "Draft", "new_status": "Pending", "action": "Submit", "comment": ""},
            {"actor": "demo_approver", "timestamp": "2026-11-03T10:02:00+00:00",
             "old_status": "Pending", "new_status": "Approved", "action": "Approve", "comment": ""},
        ]
        state_path.write_text(json.dumps({
            report_id: {"owner": "demo_user", "status": "Approved", "history": events}
        }, ensure_ascii=False), encoding="utf-8")
        state_hash = hashlib.sha256(state_path.read_bytes()).hexdigest()
        run_import(csv_path, self.db_path)
        second = run_import(csv_path, self.db_path)
        self.assertEqual(second["inserted"], "0")
        self.assertEqual(second["skipped"], "1")
        self.assertEqual(self.repo.get_report(report_id)["status"], "Approved")
        self.assertEqual(self.repo.get_history(report_id), events)
        self.assertEqual(hashlib.sha256(state_path.read_bytes()).hexdigest(), state_hash)

    def test_existing_demo_users_are_backed_up_before_first_report(self):
        self.repo.initialize()
        csv_path = self.root / "input.csv"
        write_csv(csv_path, [report("ST-20261103-0001")])
        summary = run_import(csv_path, self.db_path)
        backup = SQLiteRepository(Path(summary["backup"]))
        self.assertIsNone(backup.get_report("ST-20261103-0001"))
        with closing(backup.connect()) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM users_demo").fetchone()[0], 3)
        self.assertEqual(summary["inserted"], "1")

    def test_wrong_header_aborts_before_creating_database(self):
        csv_path = self.root / "wrong.csv"
        write_csv(csv_path, [report("ST-20261103-0001")], columns=list(reversed(CSV_COLUMNS)))
        source_before = csv_path.read_bytes()
        self.assertEqual(main(["--csv", str(csv_path), "--db", str(self.db_path)]), 1)
        self.assertFalse(self.db_path.exists())
        self.assertEqual(csv_path.read_bytes(), source_before)


if __name__ == "__main__":
    unittest.main()
