"""Data Access Layer สำหรับ Safety Talk บน SQLite โดยไม่แก้ไฟล์ CSV เดิม."""

import csv
import json
import re
import sqlite3
from collections.abc import Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from src.approval import Action, Status, TRANSITIONS
from src.permissions import AuthorizationError, Permission, Role, require_permission
from src.storage import ALLOWED_EXTENSIONS, CSV_COLUMNS, MAX_UPLOAD_BYTES


DEMO_USERS = (
    ("demo_user", Role.USER.value, "demo_user"),
    ("demo_approver", Role.APPROVER.value, "demo_approver"),
    ("demo_admin", Role.ADMIN.value, "demo_admin"),
)
HISTORY_COLUMNS = (
    "actor", "timestamp", "old_status", "new_status", "action", "comment"
)
REPORT_ID_PATTERN = re.compile(r"^ST-(\d{8})-(\d{4})$")
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "safety_talk.sqlite3"
DEFAULT_UPLOADS_PATH = DEFAULT_DB_PATH.parent / "uploads"


@dataclass(frozen=True)
class ImportSummary:
    source_rows: int
    inserted: int
    skipped: int
    invalid: int
    total_after: int
    backup_path: Path | None


def _valid_report_id(report_id: str | None) -> bool:
    match = REPORT_ID_PATTERN.fullmatch(report_id or "")
    if match is None or int(match.group(2)) == 0:
        return False
    try:
        datetime.strptime(match.group(1), "%Y%m%d")
    except ValueError:
        return False
    return True


def _valid_import_row(row: Mapping[str, Any]) -> bool:
    participants = row.get("participants")
    return (
        set(row) == set(CSV_COLUMNS)
        and all(value is not None for value in row.values())
        and _valid_report_id(row.get("report_id"))
        and row.get("company") in ("UBE", "UBS")
        and isinstance(participants, str)
        and participants.isascii()
        and participants.isdigit()
        and int(participants) > 0
    )


def _valid_import_state(state: Any) -> bool:
    if not isinstance(state, dict):
        return False
    try:
        status = Status(state.get("status", Status.DRAFT))
        owner = state.get("owner")
        history = state.get("history", [])
        if owner is not None and not isinstance(owner, str):
            return False
        if not isinstance(history, list):
            return False
        for event in history:
            if not isinstance(event, dict) or not all(key in event for key in HISTORY_COLUMNS):
                return False
            Status(event["old_status"])
            Status(event["new_status"])
            Action(event["action"])
            if not all(isinstance(event[key], str) for key in HISTORY_COLUMNS):
                return False
        return not history or history[-1]["new_status"] == status.value
    except (TypeError, ValueError):
        return False

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS users_demo (
        user_id TEXT PRIMARY KEY,
        role TEXT NOT NULL CHECK (role IN ('USER', 'APPROVER', 'ADMIN')),
        display_name TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS reports (
        report_id TEXT PRIMARY KEY,
        talk_date TEXT NOT NULL,
        company TEXT NOT NULL CHECK (company IN ('UBE', 'UBS')),
        department TEXT NOT NULL,
        reporter TEXT NOT NULL,
        topic TEXT NOT NULL,
        participants INTEGER NOT NULL CHECK (participants > 0),
        evidence_files TEXT NOT NULL,
        created_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Draft'
            CHECK (status IN ('Draft', 'Pending', 'Approved', 'Rejected')),
        owner_actor TEXT,
        owner_user_id TEXT REFERENCES users_demo(user_id) ON DELETE RESTRICT
    )""",
    """CREATE TABLE IF NOT EXISTS approval_history (
        history_id INTEGER PRIMARY KEY,
        report_id TEXT NOT NULL REFERENCES reports(report_id) ON DELETE RESTRICT,
        sequence INTEGER NOT NULL,
        actor TEXT NOT NULL,
        actor_user_id TEXT REFERENCES users_demo(user_id) ON DELETE RESTRICT,
        timestamp TEXT NOT NULL,
        old_status TEXT NOT NULL
            CHECK (old_status IN ('Draft', 'Pending', 'Approved', 'Rejected')),
        new_status TEXT NOT NULL
            CHECK (new_status IN ('Draft', 'Pending', 'Approved', 'Rejected')),
        action TEXT NOT NULL CHECK (action IN ('Submit', 'Approve', 'Reject', 'Revise')),
        comment TEXT NOT NULL,
        UNIQUE (report_id, sequence)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_approval_history_report ON approval_history(report_id, sequence)",
)


class SQLiteRepository:
    """รับ path ฐานข้อมูลอย่างชัดเจน; การสร้าง schema ไม่แตะ CSV."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    def connect(self) -> sqlite3.Connection:
        """ทุก connection เปิด foreign key enforcement ก่อนเริ่ม transaction."""
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as connection:
            for statement in SCHEMA:
                connection.execute(statement)
            connection.executemany(
                "INSERT OR IGNORE INTO users_demo (user_id, role, display_name) VALUES (?, ?, ?)",
                DEMO_USERS,
            )

    def ensure_ready(self) -> None:
        """ป้องกันแอปสร้างฐานข้อมูลว่างแทนข้อมูลเดิมโดยไม่ตั้งใจ."""
        if not self.db_path.is_file():
            raise FileNotFoundError("ยังไม่มีฐานข้อมูล SQLite; ต้อง Import ข้อมูลเดิมก่อน")
        with closing(self.connect()) as connection:
            if connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'reports'"
            ).fetchone() is None:
                raise ValueError("ฐานข้อมูล SQLite ยังไม่มีตาราง reports")

    @staticmethod
    def _known_demo_user(connection: sqlite3.Connection, actor: str | None) -> str | None:
        if not actor:
            return None
        row = connection.execute(
            "SELECT user_id FROM users_demo WHERE user_id = ?", (actor,)
        ).fetchone()
        return row["user_id"] if row else None

    def _insert_report(
        self, connection: sqlite3.Connection, report: Mapping[str, Any],
        status: Status | str = Status.DRAFT, owner: str | None = None,
    ) -> None:
        if set(report) != set(CSV_COLUMNS):
            raise ValueError("รายงานต้องมี key ตรงกับ CSV 9 คอลัมน์เดิม")
        try:
            participants = int(report["participants"])
            report_status = Status(status).value
        except (TypeError, ValueError) as error:
            raise ValueError("จำนวนผู้เข้าร่วมหรือสถานะไม่ถูกต้อง") from error
        if participants <= 0 or isinstance(report["participants"], bool):
            raise ValueError("จำนวนผู้เข้าร่วมต้องมากกว่า 0")
        connection.execute(
            """INSERT INTO reports (
                report_id, talk_date, company, department, reporter, topic,
                participants, evidence_files, created_at, status, owner_actor, owner_user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                *(report[column] for column in CSV_COLUMNS[:6]),
                participants, report["evidence_files"], report["created_at"],
                report_status, owner, self._known_demo_user(connection, owner),
            ),
        )

    def insert_report(
        self, report: Mapping[str, Any], owner: str | None = None
    ) -> None:
        """เพิ่ม Draft หนึ่งรายการ; PRIMARY KEY ป้องกัน Report ID ซ้ำ."""
        with self.transaction() as connection:
            self._insert_report(connection, report, owner=owner)

    def create_report(
        self, report: Mapping[str, Any], uploads: list,
        actor: str, role: Role | str, uploads_path: Path | None = None,
    ) -> str:
        """สร้าง Draft และ Report ID ใน SQLite transaction; ไฟล์แนบอยู่ใน data/uploads."""
        require_permission(role, Permission.CREATE_REPORT)
        self.ensure_ready()
        talk_date = report.get("talk_date")
        if not isinstance(talk_date, date) or isinstance(talk_date, datetime):
            raise ValueError("วันที่สื่อสารไม่ถูกต้อง")
        prepared = []
        for upload in uploads:
            extension = Path(upload.name.replace("\\", "/")).suffix.lower()
            if extension not in ALLOWED_EXTENSIONS:
                raise ValueError("ไฟล์แนบต้องเป็น JPG, JPEG, PNG หรือ PDF เท่านั้น")
            data = upload.getvalue()
            if len(data) >= MAX_UPLOAD_BYTES:
                raise ValueError("ไฟล์แนบแต่ละไฟล์ต้องมีขนาดน้อยกว่า 5 MB")
            prepared.append((extension, data))

        destination = Path(uploads_path) if uploads_path is not None else DEFAULT_UPLOADS_PATH
        saved_paths = []
        try:
            with self.transaction() as connection:
                user = connection.execute(
                    "SELECT role FROM users_demo WHERE user_id = ?", (actor,)
                ).fetchone()
                if user is None or user["role"] != Role(role):
                    raise AuthorizationError("ผู้สร้างและบทบาท Demo ไม่ตรงกัน")
                prefix = f"ST-{talk_date:%Y%m%d}-"
                existing_ids = connection.execute(
                    "SELECT report_id FROM reports WHERE report_id LIKE ?", (f"{prefix}%",)
                ).fetchall()
                numbers = [
                    int(suffix) for row in existing_ids
                    if (suffix := row["report_id"].removeprefix(prefix)).isascii()
                    and len(suffix) == 4 and suffix.isdigit()
                ]
                next_number = max(numbers, default=0) + 1
                if next_number > 9999:
                    raise ValueError("ไม่สามารถสร้างรหัสรายงานสำหรับวันนี้ได้")
                report_id = f"{prefix}{next_number:04d}"
                if prepared:
                    destination.mkdir(parents=True, exist_ok=True)
                for extension, data in prepared:
                    path = destination / f"{uuid4().hex}{extension}"
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
                    "evidence_files": json.dumps(
                        [path.name for path in saved_paths], ensure_ascii=False
                    ),
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                }
                self._insert_report(connection, row, owner=actor)
            return report_id
        except Exception:
            for path in saved_paths:
                path.unlink(missing_ok=True)
            raise

    def _insert_history(
        self, connection: sqlite3.Connection, report_id: str,
        sequence: int, event: Mapping[str, Any],
    ) -> None:
        if not all(field in event for field in HISTORY_COLUMNS):
            raise ValueError("Action History ไม่มีฟิลด์ที่จำเป็นครบ")
        actor = event["actor"]
        connection.execute(
            """INSERT INTO approval_history (
                report_id, sequence, actor, actor_user_id, timestamp,
                old_status, new_status, action, comment
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report_id, sequence, actor,
                self._known_demo_user(connection, actor),
                *(event[field] for field in HISTORY_COLUMNS[1:]),
            ),
        )

    def import_legacy(self, csv_path: Path, approval_path: Path | None = None) -> int:
        """อ่าน CSV/JSON เท่านั้น แล้วนำเข้าทุกรายการใน transaction เดียว."""
        with Path(csv_path).open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames != CSV_COLUMNS:
                raise ValueError("CSV header ต้องตรง schema 9 คอลัมน์เดิม")
            reports = list(reader)
        if any(None in report for report in reports):
            raise ValueError("CSV มีข้อมูลเกิน 9 คอลัมน์")

        states: dict = {}
        if approval_path is not None and Path(approval_path).exists():
            with Path(approval_path).open(encoding="utf-8") as file:
                states = json.load(file)
        if not isinstance(states, dict):
            raise ValueError("ไฟล์ Approval State ไม่ถูกต้อง")
        report_ids = {report["report_id"] for report in reports}
        if set(states) - report_ids:
            raise ValueError("Approval State มี Report ID ที่ไม่มีใน CSV")

        self.initialize()
        with self.transaction() as connection:
            for report in reports:
                report_id = report["report_id"]
                state = states.get(report_id, {})
                if not isinstance(state, dict) or not isinstance(state.get("history", []), list):
                    raise ValueError("ข้อมูล Approval State ไม่ถูกต้อง")
                history = state.get("history", [])
                status = Status(state.get("status", Status.DRAFT))
                if history and history[-1].get("new_status") != status:
                    raise ValueError("สถานะรายงานไม่ตรงกับ Action History ล่าสุด")
                self._insert_report(
                    connection, report, status=status, owner=state.get("owner")
                )
                for sequence, event in enumerate(history, start=1):
                    self._insert_history(connection, report_id, sequence, event)
        return len(reports)

    def _backup_if_populated(self) -> Path | None:
        """สำรองฐานข้อมูลก่อน Import เมื่อมีข้อมูลเดิม โดยใช้ SQLite online backup."""
        if not self.db_path.exists():
            return None
        with closing(self.connect()) as source:
            tables = {
                row["name"] for row in source.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            populated = any(
                source.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                for table in ("reports", "users_demo", "approval_history")
                if table in tables
            )
            if not populated:
                return None
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = self.db_path.with_name(
                f"{self.db_path.stem}.backup-{stamp}-{uuid4().hex[:8]}{self.db_path.suffix}"
            )
            with closing(SQLiteRepository(backup_path).connect()) as destination:
                source.backup(destination)
            return backup_path

    def import_csv_idempotent(
        self, csv_path: Path, approval_path: Path | None = None
    ) -> ImportSummary:
        """ตรวจ CSV/Report ID แล้วเพิ่มเฉพาะ ID ใหม่; ไม่เขียนต้นทางหรือแถวเดิม."""
        with Path(csv_path).open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames != CSV_COLUMNS:
                raise ValueError("CSV header ต้องตรง schema 9 คอลัมน์เดิม")
            source_rows = list(reader)

        states: dict = {}
        if approval_path is not None and Path(approval_path).exists():
            with Path(approval_path).open(encoding="utf-8") as file:
                states = json.load(file)
        if not isinstance(states, dict):
            raise ValueError("ไฟล์ Approval State ไม่ถูกต้อง")
        source_ids = {row.get("report_id") for row in source_rows}
        if set(states) - source_ids:
            raise ValueError("Approval State มี Report ID ที่ไม่มีใน CSV")

        candidates = []
        seen_ids = set()
        skipped = invalid = 0
        for row in source_rows:
            report_id = row.get("report_id")
            state = states.get(report_id, {})
            if not _valid_import_row(row) or not _valid_import_state(state):
                invalid += 1
            elif report_id in seen_ids:
                skipped += 1
            else:
                seen_ids.add(report_id)
                candidates.append((row, state))

        backup_path = self._backup_if_populated()
        self.initialize()
        inserted = 0
        with self.transaction() as connection:
            for row, state in candidates:
                report_id = row["report_id"]
                if connection.execute(
                    "SELECT 1 FROM reports WHERE report_id = ?", (report_id,)
                ).fetchone():
                    skipped += 1
                    continue
                connection.execute("SAVEPOINT import_row")
                try:
                    self._insert_report(
                        connection, row,
                        status=state.get("status", Status.DRAFT),
                        owner=state.get("owner"),
                    )
                    for sequence, event in enumerate(state.get("history", []), start=1):
                        self._insert_history(connection, report_id, sequence, event)
                except (ValueError, sqlite3.IntegrityError):
                    connection.execute("ROLLBACK TO SAVEPOINT import_row")
                    invalid += 1
                else:
                    inserted += 1
                finally:
                    connection.execute("RELEASE SAVEPOINT import_row")
            total_after = connection.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        return ImportSummary(
            source_rows=len(source_rows), inserted=inserted, skipped=skipped,
            invalid=invalid, total_after=total_after, backup_path=backup_path,
        )

    def get_report(self, report_id: str) -> dict | None:
        with closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT * FROM reports WHERE report_id = ?", (report_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_reports(self) -> list[dict]:
        """คืน 9 ฟิลด์เดิมจาก SQLite สำหรับ Dashboard และ History."""
        columns = ", ".join(CSV_COLUMNS)
        with closing(self.connect()) as connection:
            rows = connection.execute(
                f"SELECT {columns} FROM reports ORDER BY rowid"
            ).fetchall()
            return [dict(row) for row in rows]

    @staticmethod
    def _talk_date_iso(value: str | None) -> str | None:
        """Normalize legacy day/month/year dates for read-only SQLite filters."""
        if not value:
            return None
        for format_string in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(value, format_string).date().isoformat()
            except ValueError:
                continue
        return None

    @staticmethod
    def _history_scope(
        connection: sqlite3.Connection, actor: str, role: Role | str,
    ) -> tuple[str, list[str]]:
        require_permission(role, Permission.VIEW_DASHBOARD)
        user = connection.execute(
            "SELECT role FROM users_demo WHERE user_id = ?", (actor,)
        ).fetchone()
        if user is None or user["role"] != Role(role):
            raise AuthorizationError("ผู้ใช้และบทบาท Demo ไม่ตรงกัน")
        if Role(role) is Role.USER:
            return "r.owner_actor = ?", [actor]
        return "1 = 1", []

    def search_history(
        self, actor: str, role: Role | str, *, query: str = "",
        company: str | None = None, department: str | None = None,
        date_from: date | None = None, date_to: date | None = None,
        status: Status | str | None = None,
    ) -> list[dict]:
        """Search only visible reports; every user value is a query parameter."""
        if company is not None and company not in ("UBE", "UBS"):
            raise ValueError("บริษัทไม่ถูกต้อง")
        if status is not None:
            status = Status(status).value
        if date_from is not None and date_to is not None and date_from > date_to:
            raise ValueError("วันที่เริ่มต้นต้องไม่เกินวันที่สิ้นสุด")
        with closing(self.connect()) as connection:
            scope, parameters = self._history_scope(connection, actor, role)
            conditions = [scope]
            if query.strip():
                conditions.append(
                    "(instr(lower(r.report_id), lower(?)) > 0 OR "
                    "instr(lower(r.topic), lower(?)) > 0 OR "
                    "instr(lower(r.reporter), lower(?)) > 0)"
                )
                parameters.extend([query.strip()] * 3)
            if company is not None:
                conditions.append("r.company = ?")
                parameters.append(company)
            if department is not None:
                conditions.append("r.department = ?")
                parameters.append(department)
            if status is not None:
                conditions.append("r.status = ?")
                parameters.append(status)
            if date_from is not None or date_to is not None:
                connection.create_function("talk_date_iso", 1, self._talk_date_iso, deterministic=True)
                if date_from is not None:
                    conditions.append("talk_date_iso(r.talk_date) >= ?")
                    parameters.append(date_from.isoformat())
                if date_to is not None:
                    conditions.append("talk_date_iso(r.talk_date) <= ?")
                    parameters.append(date_to.isoformat())
            columns = ", ".join(f"r.{column}" for column in CSV_COLUMNS)
            rows = connection.execute(
                f"SELECT {columns}, r.status FROM reports AS r "
                f"WHERE {' AND '.join(conditions)} ORDER BY r.rowid DESC",
                parameters,
            ).fetchall()
            return [dict(row) for row in rows]

    def list_history_departments(
        self, actor: str, role: Role | str, company: str | None = None,
    ) -> list[str]:
        if company is not None and company not in ("UBE", "UBS"):
            raise ValueError("บริษัทไม่ถูกต้อง")
        with closing(self.connect()) as connection:
            scope, parameters = self._history_scope(connection, actor, role)
            company_clause = " AND r.company = ?" if company is not None else ""
            if company is not None:
                parameters.append(company)
            rows = connection.execute(
                "SELECT DISTINCT r.department FROM reports AS r "
                f"WHERE {scope}{company_clause} AND trim(r.department) <> '' "
                "ORDER BY r.department", parameters,
            ).fetchall()
            return [row["department"] for row in rows]

    def get_visible_report_detail(
        self, report_id: str, actor: str, role: Role | str,
    ) -> tuple[dict, list[dict]] | None:
        """Read a report and its actions only after checking visibility in the DAL."""
        with closing(self.connect()) as connection:
            scope, parameters = self._history_scope(connection, actor, role)
            columns = ", ".join(f"r.{column}" for column in CSV_COLUMNS)
            row = connection.execute(
                f"SELECT {columns}, r.status, r.owner_actor FROM reports AS r "
                f"WHERE r.report_id = ? AND {scope}",
                [report_id, *parameters],
            ).fetchone()
            if row is None:
                return None
            events = connection.execute(
                "SELECT actor, timestamp, old_status, new_status, action, comment "
                "FROM approval_history WHERE report_id = ? ORDER BY sequence",
                (report_id,),
            ).fetchall()
            return dict(row), [dict(event) for event in events]

    def get_status(self, report_id: str) -> Status:
        report = self.get_report(report_id)
        if report is None:
            raise ValueError("ไม่พบ Report ID")
        return Status(report["status"])

    def get_owner(self, report_id: str) -> str | None:
        report = self.get_report(report_id)
        if report is None:
            raise ValueError("ไม่พบ Report ID")
        return report["owner_actor"]

    def get_history(self, report_id: str) -> list[dict]:
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """SELECT actor, timestamp, old_status, new_status, action, comment
                FROM approval_history WHERE report_id = ? ORDER BY sequence""",
                (report_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_pending(self, role: Role | str) -> list[dict]:
        require_permission(role, Permission.APPROVE_REPORT)
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """SELECT r.report_id, r.talk_date, r.company, r.department,
                    r.topic, r.status,
                    (SELECT h.actor FROM approval_history AS h
                     WHERE h.report_id = r.report_id AND h.action = 'Submit'
                     ORDER BY h.sequence DESC LIMIT 1) AS submitted_by
                FROM reports AS r WHERE r.status = 'Pending' ORDER BY r.rowid"""
            ).fetchall()
            return [dict(row) for row in rows]

    def list_report_ids(self, role: Role | str) -> list[str]:
        require_permission(role, Permission.APPROVE_REPORT)
        with closing(self.connect()) as connection:
            rows = connection.execute(
                "SELECT report_id FROM reports ORDER BY rowid"
            ).fetchall()
            return [row["report_id"] for row in rows]

    def transition(
        self, report_id: str, action: Action | str,
        actor: str, role: Role | str, comment: str = "",
    ) -> Status:
        """เปลี่ยนสถานะและเพิ่ม History ใน transaction เดียว."""
        requested_action = Action(action)
        required_status, new_status, permission = TRANSITIONS[requested_action]
        require_permission(role, permission)
        if requested_action is Action.REJECT and not comment.strip():
            raise ValueError("กรุณาระบุเหตุผลเมื่อ Reject")
        with self.transaction() as connection:
            user = connection.execute(
                "SELECT role FROM users_demo WHERE user_id = ?", (actor,)
            ).fetchone()
            if user is None or user["role"] != Role(role):
                raise AuthorizationError("ผู้ทำรายการและบทบาท Demo ไม่ตรงกัน")
            report = connection.execute(
                "SELECT status, owner_actor FROM reports WHERE report_id = ?", (report_id,)
            ).fetchone()
            if report is None:
                raise ValueError("ไม่พบ Report ID")
            if report["status"] != required_status:
                raise ValueError("สถานะปัจจุบันไม่อนุญาต Action นี้")
            if requested_action is Action.SUBMIT and report["owner_actor"] != actor:
                raise AuthorizationError("ผู้ส่งต้องเป็นเจ้าของรายงาน")
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM approval_history WHERE report_id = ?",
                (report_id,),
            ).fetchone()[0]
            connection.execute(
                "UPDATE reports SET status = ? WHERE report_id = ?",
                (new_status.value, report_id),
            )
            self._insert_history(connection, report_id, sequence, {
                "actor": actor,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "old_status": required_status.value,
                "new_status": new_status.value,
                "action": requested_action.value,
                "comment": comment.strip(),
            })
        return new_status


def get_repository() -> SQLiteRepository:
    """สร้าง DAL สำหรับแอป; เปลี่ยน path ในเทสต์ได้โดยไม่แตะข้อมูลจริง."""
    return SQLiteRepository(DEFAULT_DB_PATH)
