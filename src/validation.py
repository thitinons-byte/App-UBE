"""ตรวจข้อมูลรายงาน Safety Talk ก่อนส่งต่อไปบันทึก."""

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any


def validate_report(
    report: Mapping[str, Any], departments: Mapping[str, Sequence[str]]
) -> list[str]:
    """คืนข้อความภาษาไทยสำหรับข้อมูลที่ไม่ผ่านการตรวจ; รายการว่างหมายถึงผ่าน."""
    errors = []

    talk_date = report.get("talk_date")
    if isinstance(talk_date, str):
        try:
            date.fromisoformat(talk_date)
        except ValueError:
            errors.append("กรุณาระบุวันที่สื่อสารที่ถูกต้อง")
    elif not isinstance(talk_date, date) or isinstance(talk_date, datetime):
        errors.append("กรุณาระบุวันที่สื่อสารที่ถูกต้อง")

    company = report.get("company")
    if company not in ("UBE", "UBS"):
        errors.append("กรุณาเลือกบริษัท UBE หรือ UBS")

    department = report.get("department")
    if not isinstance(department, str) or not department.strip():
        errors.append("กรุณาเลือกหน่วยงาน")
    elif company not in ("UBE", "UBS") or department not in departments.get(company, ()):
        errors.append("หน่วยงานไม่ตรงกับบริษัทที่เลือก")

    for field, label in (("reporter", "ชื่อผู้รายงาน"), ("topic", "หัวข้อ Safety Talk")):
        value = report.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"กรุณาระบุ{label}")

    participants = report.get("participants")
    if isinstance(participants, bool) or not isinstance(participants, int) or participants <= 0:
        errors.append("จำนวนผู้เข้าร่วมต้องเป็นจำนวนเต็มมากกว่า 0")

    return errors
