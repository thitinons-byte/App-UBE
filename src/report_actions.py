"""Action ของรายงานที่ตรวจสิทธิ์ก่อนเปลี่ยนข้อมูล."""

from collections.abc import Mapping
from typing import Any

from src import storage
from src.permissions import Permission, Role, require_permission


def submit_report(role: Role | str, report: Mapping[str, Any], uploads: list) -> str:
    """ตรวจสิทธิ์ก่อนบันทึก CSV และไฟล์แนบ."""
    require_permission(role, Permission.SUBMIT_REPORT)
    return storage.save_report(report, uploads)


