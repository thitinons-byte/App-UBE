"""อ่านและเพิ่มรายงาน Safety Talk ใน CSV สำหรับ workshop ภายในเครื่อง.

การตรวจข้อมูลฟอร์มเป็นหน้าที่ของส่วนเรียกใช้งาน
"""

import csv
import json
import threading
from datetime import datetime
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4


CSV_COLUMNS = [
    "report_id",
    "talk_date",
    "company",
    "department",
    "reporter",
    "topic",
    "participants",
    "evidence_files",
    "created_at",
]

REPORTS_PATH = Path(__file__).resolve().parent.parent / "data" / "reports.csv"
UPLOADS_PATH = REPORTS_PATH.parent / "uploads"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}
_SAVE_LOCK = threading.Lock()


def _check_header(fieldnames: list[str] | None) -> None:
    """ป้องกันการอ่านหรือเขียนไฟล์ที่มี header ไม่ตรงกับ schema."""
    if (
        fieldnames is None
        or len(fieldnames) != len(CSV_COLUMNS)
        or set(fieldnames) != set(CSV_COLUMNS)
    ):
        raise ValueError("CSV header ไม่ตรงกับคอลัมน์รายงาน Safety Talk")


def read_reports() -> list[dict[str, str]]:
    """อ่านรายงานจาก reports.csv; คืนรายการว่างเมื่อยังไม่มีข้อมูล."""
    try:
        with REPORTS_PATH.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames is None:
                return []
            _check_header(reader.fieldnames)
            return list(reader)
    except FileNotFoundError:
        return []


def append_report(report: Mapping[str, Any]) -> None:
    """เพิ่มหนึ่งรายงานลง reports.csv โดยคง header และข้อมูลเดิมไว้.

    report ต้องมี key ตาม CSV_COLUMNS ทุกคอลัมน์ โดย evidence_files ใช้
    สตริงว่างได้เมื่อไม่มีไฟล์แนบ ฟังก์ชันนี้ไม่แก้ไขไฟล์ sample
    """
    if set(report) != set(CSV_COLUMNS):
        raise ValueError("ข้อมูลรายงานต้องมี key ตรงกับ CSV_COLUMNS")

    REPORTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORTS_PATH.open("a+", encoding="utf-8-sig", newline="") as file:
        file.seek(0)
        contents = file.read()
        if contents:
            file.seek(0)
            reader = csv.DictReader(file)
            _check_header(reader.fieldnames)
            fieldnames = reader.fieldnames
        else:
            fieldnames = CSV_COLUMNS

        file.seek(0, 2)
        if contents and not contents.endswith(("\n", "\r")):
            file.write("\n")
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        if not contents:
            writer.writeheader()
        writer.writerow(report)


def save_report(report: Mapping[str, Any], uploads: list) -> str:
    """บันทึกรายงานที่ผ่านการตรวจแล้วและไฟล์แนบในเครื่อง workshop."""
    prepared = []
    for upload in uploads:
        extension = Path(upload.name.replace("\\", "/")).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise ValueError("ไฟล์แนบต้องเป็น JPG, JPEG, PNG หรือ PDF เท่านั้น")
        data = upload.getvalue()
        if len(data) >= MAX_UPLOAD_BYTES:
            raise ValueError("ไฟล์แนบแต่ละไฟล์ต้องมีขนาดน้อยกว่า 5 MB")
        prepared.append((extension, data))

    with _SAVE_LOCK:
        # ตรวจว่าเปิดไฟล์รายงานเพื่อเขียนได้ก่อนสร้างไฟล์แนบใด ๆ
        # โดยไม่แก้ไขเนื้อหาไฟล์ระหว่างตรวจ
        if REPORTS_PATH.exists():
            with REPORTS_PATH.open("r+", encoding="utf-8-sig", newline=""):
                pass
        talk_date = report["talk_date"]
        date_prefix = talk_date.strftime("%Y%m%d")
        prefix = f"ST-{date_prefix}-"
        sequence_numbers = []
        for row in read_reports():
            existing_id = row.get("report_id", "")
            suffix = existing_id.removeprefix(prefix)
            if existing_id.startswith(prefix) and len(suffix) == 4 and suffix.isascii() and suffix.isdigit():
                sequence_numbers.append(int(suffix))
        next_number = max(sequence_numbers, default=0) + 1
        if next_number > 9999:
            raise ValueError("ไม่สามารถสร้างรหัสรายงานสำหรับวันนี้ได้")
        report_id = f"{prefix}{next_number:04d}"

        saved_paths = []
        try:
            if prepared:
                UPLOADS_PATH.mkdir(parents=True, exist_ok=True)
            for extension, data in prepared:
                path = UPLOADS_PATH / f"{uuid4().hex}{extension}"
                with path.open("xb") as file:
                    saved_paths.append(path)
                    file.write(data)
            row = {
                "report_id": report_id,
                "talk_date": talk_date.isoformat(),
                "company": report["company"],
                "department": report["department"],
                "reporter": report["reporter"].strip(),
                "topic": report["topic"].strip(),
                "participants": report["participants"],
                "evidence_files": json.dumps([path.name for path in saved_paths], ensure_ascii=False),
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
            append_report(row)
        except Exception:
            for path in saved_paths:
                path.unlink(missing_ok=True)
            raise
        return report_id
