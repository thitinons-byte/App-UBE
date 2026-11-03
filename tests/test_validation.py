import unittest
from datetime import date

from src.validation import validate_report


class ValidateReportTests(unittest.TestCase):
    def setUp(self):
        self.departments = {"UBE": ["หน่วยงาน UBE"], "UBS": ["หน่วยงาน UBS"]}
        self.report = {
            "talk_date": date(2026, 11, 2),
            "company": "UBE",
            "department": "หน่วยงาน UBE",
            "reporter": "ผู้สาธิต",
            "topic": "การทำงานอย่างปลอดภัย",
            "participants": 5,
        }

    def test_empty_topic(self):
        self.report["topic"] = "  "
        self.assertIn("กรุณาระบุหัวข้อ Safety Talk", validate_report(self.report, self.departments))

    def test_zero_participants(self):
        self.report["participants"] = 0
        self.assertIn(
            "จำนวนผู้เข้าร่วมต้องเป็นจำนวนเต็มมากกว่า 0",
            validate_report(self.report, self.departments),
        )

    def test_department_must_match_company(self):
        self.report["department"] = "หน่วยงาน UBS"
        self.assertIn("หน่วยงานไม่ตรงกับบริษัทที่เลือก", validate_report(self.report, self.departments))

    def test_valid_report_has_no_errors(self):
        self.assertEqual(validate_report(self.report, self.departments), [])


if __name__ == "__main__":
    unittest.main()
