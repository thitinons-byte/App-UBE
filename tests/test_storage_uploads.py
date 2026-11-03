import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from src import storage


class FakeUpload:
    def __init__(self, name, data):
        self.name = name
        self.data = data

    def getvalue(self):
        return self.data


class StorageUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.reports = root / "reports.csv"
        self.uploads = root / "uploads"
        reports_patch = patch.object(storage, "REPORTS_PATH", self.reports)
        uploads_patch = patch.object(storage, "UPLOADS_PATH", self.uploads)
        reports_patch.start()
        uploads_patch.start()
        self.addCleanup(reports_patch.stop)
        self.addCleanup(uploads_patch.stop)
        self.report = {
            "talk_date": date(2026, 11, 2),
            "company": "UBE",
            "department": "หน่วยงานตัวอย่าง",
            "reporter": "ผู้สาธิต",
            "topic": "หัวข้อทดสอบ",
            "participants": 3,
        }

    def test_uploads_use_generated_names_and_json(self):
        report_id = storage.save_report(
            self.report,
            [FakeUpload("../../original.JPG", b"image"), FakeUpload("doc.pdf", b"pdf")],
        )
        row = storage.read_reports()[0]
        names = json.loads(row["evidence_files"])
        self.assertEqual(report_id, "ST-20261102-0001")
        self.assertEqual(len(names), 2)
        self.assertTrue(all((self.uploads / name).is_file() for name in names))
        self.assertTrue(all("/" not in name and "\\" not in name for name in names))
        self.assertNotIn("original", names[0])
        self.assertEqual(storage.save_report(self.report, []), "ST-20261102-0002")
        self.assertEqual(json.loads(storage.read_reports()[1]["evidence_files"]), [])

    def test_invalid_uploads_do_not_write(self):
        for upload in (
            FakeUpload("test.exe", b"test"),
            FakeUpload("test.png", b"x" * storage.MAX_UPLOAD_BYTES),
        ):
            with self.subTest(name=upload.name), self.assertRaises(ValueError):
                storage.save_report(self.report, [upload])
        self.assertFalse(self.reports.exists())
        self.assertFalse(self.uploads.exists())

    def test_locked_report_does_not_create_uploads(self):
        self.reports.write_text(
            ",".join(storage.CSV_COLUMNS) + "\n", encoding="utf-8-sig"
        )
        before = self.reports.read_bytes()
        with patch.object(Path, "open", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                storage.save_report(self.report, [FakeUpload("demo.png", b"demo")])
        self.assertEqual(self.reports.read_bytes(), before)
        self.assertFalse(self.uploads.exists())

    def test_report_id_uses_next_number_per_talk_date(self):
        row = dict.fromkeys(storage.CSV_COLUMNS, "")
        for report_id in ("ST-20261102-0001", "ST-20261102-0003", "ST-20261103-0012"):
            row["report_id"] = report_id
            storage.append_report(row)
        self.assertEqual(storage.save_report(self.report, []), "ST-20261102-0004")
        self.report["talk_date"] = date(2026, 11, 3)
        self.assertEqual(storage.save_report(self.report, []), "ST-20261103-0013")
        self.report["talk_date"] = date(2026, 11, 4)
        self.assertEqual(storage.save_report(self.report, []), "ST-20261104-0001")
        with self.reports.open(encoding="utf-8-sig") as file:
            self.assertEqual(file.readline().strip().split(","), storage.CSV_COLUMNS)
        self.assertTrue(self.reports.read_bytes().startswith(b"\xef\xbb\xbf"))


if __name__ == "__main__":
    unittest.main()
