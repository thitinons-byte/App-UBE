"""นำเข้า CSV Safety Talk ลง SQLite แบบไม่เขียนทับข้อมูลเดิม.

ตัวอย่าง:
    python import_safety_talk_csv.py
    python import_safety_talk_csv.py --csv data/reports.csv
    python import_safety_talk_csv.py --csv data/reports.csv --db data/safety_talk.sqlite3
"""

import argparse
import sqlite3
import sys
from pathlib import Path

from src.sqlite_storage import SQLiteRepository


PROJECT_ROOT = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import Safety Talk CSV into SQLite")
    parser.add_argument(
        "--csv", type=Path,
        default=PROJECT_ROOT / "data" / "sample_safety_talk.csv",
        help="CSV 9 คอลัมน์ (ค่าเริ่มต้น: sample_safety_talk.csv)",
    )
    parser.add_argument(
        "--db", type=Path,
        default=PROJECT_ROOT / "data" / "safety_talk.sqlite3",
        help="ไฟล์ SQLite ปลายทาง",
    )
    parser.add_argument(
        "--approval-state", type=Path,
        help="JSON ประวัติ Approval; สำหรับ reports.csv จะตรวจไฟล์ข้างกันอัตโนมัติ",
    )
    args = parser.parse_args(argv)
    approval_path = args.approval_state
    if approval_path is None and args.csv.name.lower() == "reports.csv":
        candidate = args.csv.with_name("approval_state.json")
        if candidate.exists():
            approval_path = candidate

    try:
        summary = SQLiteRepository(args.db).import_csv_idempotent(
            args.csv, approval_path
        )
    except (OSError, ValueError, sqlite3.DatabaseError) as error:
        print(f"Import failed: {error}", file=sys.stderr)
        return 1

    print(f"source_rows: {summary.source_rows}")
    print(f"inserted: {summary.inserted}")
    print(f"skipped: {summary.skipped}")
    print(f"invalid: {summary.invalid}")
    print(f"total_after: {summary.total_after}")
    print(f"backup: {summary.backup_path or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
