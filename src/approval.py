"""Approval workflow สำหรับ Workshop; แยกสถานะจาก CSV รายงานเดิม."""

import json
import os
import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from src import storage
from src.permissions import AuthorizationError, Permission, Role, require_permission


APPROVAL_STATE_PATH = storage.REPORTS_PATH.parent / "approval_state.json"
_STATE_LOCK = threading.Lock()


class Status(StrEnum):
    DRAFT = "Draft"
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


class Action(StrEnum):
    SUBMIT = "Submit"
    APPROVE = "Approve"
    REJECT = "Reject"
    REVISE = "Revise"


TRANSITIONS = {
    Action.SUBMIT: (Status.DRAFT, Status.PENDING, Permission.SUBMIT_REPORT),
    Action.APPROVE: (Status.PENDING, Status.APPROVED, Permission.APPROVE_REPORT),
    Action.REJECT: (Status.PENDING, Status.REJECTED, Permission.APPROVE_REPORT),
    Action.REVISE: (Status.REJECTED, Status.DRAFT, Permission.CREATE_REPORT),
}


class ApprovalService:
    def __init__(
        self,
        state_path: Path | None = None,
        reports_reader: Callable[[], list[dict[str, str]]] | None = None,
    ) -> None:
        self.state_path = state_path if state_path is not None else APPROVAL_STATE_PATH
        self.reports_reader = reports_reader if reports_reader is not None else storage.read_reports

    def _check_report_id(self, report_id: str) -> None:
        if not isinstance(report_id, str) or not report_id.strip():
            raise ValueError("กรุณาระบุ Report ID")
        if not any(row.get("report_id") == report_id for row in self.reports_reader()):
            raise ValueError("ไม่พบ Report ID ใน data/reports.csv")

    def _load(self) -> dict:
        try:
            with self.state_path.open(encoding="utf-8") as file:
                data = json.load(file)
        except FileNotFoundError:
            return {}
        if not isinstance(data, dict):
            raise ValueError("ข้อมูลสถานะรายงานไม่ถูกต้อง")
        return data

    @staticmethod
    def _record(data: Mapping, report_id: str) -> tuple[Status, list]:
        entry = data.get(report_id, {"status": Status.DRAFT, "history": []})
        if not isinstance(entry, dict) or not isinstance(entry.get("history"), list):
            raise ValueError("ข้อมูลสถานะรายงานไม่ถูกต้อง")
        try:
            status = Status(entry["status"])
        except (KeyError, ValueError, TypeError) as error:
            raise ValueError("สถานะรายงานไม่ถูกต้อง") from error
        return status, entry["history"]

    def get_status(self, report_id: str) -> Status:
        self._check_report_id(report_id)
        status, _ = self._record(self._load(), report_id)
        return status

    def get_owner(self, report_id: str) -> str | None:
        """รายงานเก่าที่ไม่มีข้อมูลเจ้าของจะคืน None โดยไม่เดาเจ้าของ."""
        self._check_report_id(report_id)
        entry = self._load().get(report_id)
        if entry is None:
            return None
        self._record({report_id: entry}, report_id)
        owner = entry.get("owner")
        return owner if isinstance(owner, str) and owner.strip() else None

    def register_draft(self, report_id: str, owner: str, role: Role | str) -> None:
        """ผูกเจ้าของบัญชีจำลองกับ Report ID หลังบันทึก CSV สำเร็จ."""
        require_permission(role, Permission.CREATE_REPORT)
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError("กรุณาระบุเจ้าของรายงาน")
        with _STATE_LOCK:
            self._check_report_id(report_id)
            data = self._load()
            if report_id in data:
                status, history = self._record(data, report_id)
                if data[report_id].get("owner") == owner and status is Status.DRAFT and not history:
                    return
                raise ValueError("Report ID นี้มีข้อมูลเจ้าของหรือประวัติ Action แล้ว")
            data[report_id] = {"owner": owner.strip(), "status": Status.DRAFT.value, "history": []}
            self._write(data)

    def get_history(self, report_id: str) -> list[dict]:
        self._check_report_id(report_id)
        _, history = self._record(self._load(), report_id)
        return [item.copy() for item in history]

    def list_pending(self, role: Role | str) -> list[dict[str, str]]:
        """อ่านคิว Pending จากรายงานจริงและประวัติการส่ง โดยตรวจสิทธิ์ก่อนอ่าน."""
        require_permission(role, Permission.APPROVE_REPORT)
        reports = self.reports_reader()
        states = self._load()
        pending = []
        for report in reports:
            report_id = report.get("report_id", "")
            if not report_id:
                continue
            status, history = self._record(states, report_id)
            if status is not Status.PENDING:
                continue
            submit_event = next(
                (event for event in reversed(history) if event.get("action") == Action.SUBMIT),
                None,
            )
            pending.append({
                "report_id": report_id,
                "talk_date": report.get("talk_date", ""),
                "company": report.get("company", ""),
                "department": report.get("department", ""),
                "topic": report.get("topic", ""),
                "submitted_by": submit_event.get("actor", "") if submit_event else "",
                "status": status.value,
            })
        return pending

    def list_report_ids(self, role: Role | str) -> list[str]:
        """คืน Report ID ที่มีอยู่จริงสำหรับดูสถานะและ Action History."""
        require_permission(role, Permission.APPROVE_REPORT)
        return [
            report_id
            for row in self.reports_reader()
            if (report_id := row.get("report_id"))
        ]

    def _write(self, data: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(f".{self.state_path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
                file.write("\n")
            os.replace(temporary, self.state_path)
        finally:
            temporary.unlink(missing_ok=True)

    def transition(
        self,
        report_id: str,
        action: Action | str,
        role: Role | str,
        actor: str,
        comment: str = "",
    ) -> Status:
        """ตรวจสิทธิ์และสถานะก่อนบันทึก Action History ลงไฟล์แยก."""
        try:
            requested_action = Action(action)
        except (ValueError, TypeError) as error:
            raise ValueError("Action ไม่ถูกต้อง") from error
        old_required, new_status, permission = TRANSITIONS[requested_action]
        require_permission(role, permission)
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError("กรุณาระบุผู้ดำเนินการ")
        if not isinstance(comment, str):
            raise ValueError("Comment ต้องเป็นข้อความ")
        if requested_action is Action.REJECT and not comment.strip():
            raise ValueError("กรุณาระบุเหตุผลเมื่อ Reject")

        with _STATE_LOCK:
            self._check_report_id(report_id)
            data = self._load()
            old_status, history = self._record(data, report_id)
            if old_status is not old_required:
                raise ValueError(
                    f"ไม่สามารถ {requested_action} จากสถานะ {old_status}; ต้องเป็น {old_required}"
                )
            if requested_action is Action.SUBMIT and data.get(report_id, {}).get("owner") != actor.strip():
                raise AuthorizationError("ผู้ส่งขออนุมัติต้องเป็นเจ้าของรายงานใน DEMO MODE")
            event = {
                "actor": actor.strip(),
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "old_status": old_status.value,
                "new_status": new_status.value,
                "action": requested_action.value,
                "comment": comment.strip(),
            }
            data[report_id] = {
                **data.get(report_id, {}),
                "status": new_status.value,
                "history": [*history, event],
            }
            self._write(data)
            return new_status
