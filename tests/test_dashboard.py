"""Dashboard reads only the temporary SQLite repository."""

import csv
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src.sqlite_storage import CSV_COLUMNS


APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def add_report(repository, report_id, talk_date, company, department, participants):
    repository.insert_report({
        "report_id": report_id, "talk_date": talk_date, "company": company,
        "department": department, "reporter": "ผู้สาธิต", "topic": "ทดสอบ",
        "participants": participants, "evidence_files": "[]", "created_at": "2026-11-03T10:00:00",
    }, owner="demo_user")


def open_dashboard():
    app = AppTest.from_file(str(APP_PATH)).run()
    next(button for button in app.button if button.key == "menu_Dashboard").click().run()
    return app


def test_empty_sqlite_has_zero_metrics_and_no_sample_fallback(isolated_app_database):
    with patch("streamlit.bar_chart") as chart, patch("pandas.read_csv") as csv_read:
        app = open_dashboard()
    assert [metric.value for metric in app.metric] == ["0", "0", "0", "0"]
    assert not app.exception
    chart.assert_not_called()
    csv_read.assert_not_called()


def test_dashboard_metrics_monthly_chart_and_filters(isolated_app_database):
    repository = isolated_app_database
    add_report(repository, "ST-20261101-0001", "2026-11-01", "UBE", "ผลิต", 2)
    add_report(repository, "ST-20261201-0001", "2026-12-01", "UBE", "ซ่อมบำรุง", 3)
    add_report(repository, "ST-20261102-0001", "2026-11-02", "UBS", "คลังสินค้า", 5)
    add_report(repository, "ST-20251103-0001", "2025-11-03", "UBS", "คลังสินค้า", 7)
    with patch("streamlit.bar_chart") as chart, patch("streamlit.download_button") as download:
        app = open_dashboard()
        assert [metric.value for metric in app.metric] == ["4", "17", "2", "2"]
        assert chart.call_count == 1
        app.selectbox(key="dashboard_company").select("UBE").run()
        assert app.selectbox(key="dashboard_department").options == ["ทั้งหมด", "ผลิต", "ซ่อมบำรุง"]
        app.selectbox(key="dashboard_department").select("ผลิต").run()
        app.selectbox(key="dashboard_year").select(2026).run()
        app.selectbox(key="dashboard_month").select(11).run()
        assert [metric.value for metric in app.metric] == ["1", "2", "1", "0"]
        data = download.call_args.kwargs["data"]
        assert data.startswith(b"\xef\xbb\xbf")
        reader = csv.DictReader(StringIO(data.decode("utf-8-sig")))
        assert reader.fieldnames == CSV_COLUMNS
        assert [row["report_id"] for row in reader] == ["ST-20261101-0001"]
        app.selectbox(key="dashboard_company").select("UBS").run()
        assert app.selectbox(key="dashboard_department").value == "ทั้งหมด"
        assert app.selectbox(key="dashboard_department").options == ["ทั้งหมด", "คลังสินค้า"]
        assert [metric.value for metric in app.metric] == ["1", "5", "0", "1"]
    assert not app.exception


def test_invalid_date_does_not_draw_chart(isolated_app_database):
    add_report(isolated_app_database, "ST-20261103-0001", "invalid", "UBE", "ผลิต", 2)
    with patch("streamlit.bar_chart") as chart:
        app = open_dashboard()
    chart.assert_not_called()
    assert app.info
    assert not app.exception
