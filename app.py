import json
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from src.approval import Action, Status
from src.permissions import AuthorizationError, Permission, Role, has_permission, require_permission
from src.sqlite_storage import CSV_COLUMNS, get_repository
from src.validation import validate_report

# 1. ตั้งค่าหน้าเพจ
st.set_page_config(
    page_title="UBE Safety Talk",
    page_icon="🦺",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 2. Styling (CSS)
st.markdown(
    """
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Prompt:wght@300;400;500;600;700&display=swap');
        
        * {
            font-family: 'Prompt', -apple-system, BlinkMacSystemFont, sans-serif;
        }

        .stApp {
            background: linear-gradient(135deg, #f4f8f5 0%, #e8f2ec 100%);
        }

        /* Sidebar Styling */
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0d3325 0%, #164e37 100%);
            border-right: none;
            box-shadow: 6px 0 24px rgba(0, 0, 0, 0.12);
        }
        
        [data-testid="stSidebar"] > div:first-child {
            padding: 1.8rem 1.2rem;
        }

        .sidebar-brand {
            display: flex;
            align-items: center;
            gap: 0.9rem;
            padding: 0.4rem 0 1rem;
        }

        .sidebar-icon {
            display: grid;
            width: 3.5rem;
            height: 3.5rem;
            place-items: center;
            font-size: 1.8rem;
            background: rgba(255, 255, 255, 0.15);
            backdrop-filter: blur(8px);
            border: 1px solid rgba(255, 255, 255, 0.25);
            border-radius: 1rem;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
        }

        .sidebar-brand h2 {
            margin: 0;
            color: #ffffff;
            font-size: 1.35rem;
            font-weight: 700;
            line-height: 1.2;
        }

        .sidebar-brand span {
            color: #b3dfc6;
            font-size: 0.78rem;
            font-weight: 500;
            letter-spacing: 0.05em;
        }

        .menu-label {
            margin: 0.5rem 0 0.6rem;
            color: #92caa8;
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }

        /* Custom Sidebar Buttons */
        [data-testid="stSidebar"] [data-testid="stButton"] {
            margin-bottom: 0.4rem;
        }

        [data-testid="stSidebar"] [data-testid^="stBaseButton-"] {
            min-height: 3.5rem;
            justify-content: flex-start;
            padding: 0.75rem 1.1rem;
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 0.85rem;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        }

        [data-testid="stSidebar"] [data-testid^="stBaseButton-"] p {
            color: #e3f2e9;
            font-size: 0.98rem;
            font-weight: 500;
        }

        [data-testid="stSidebar"] [data-testid^="stBaseButton-"]:hover {
            background: rgba(255, 255, 255, 0.14);
            border-color: rgba(255, 255, 255, 0.25);
            transform: translateX(4px);
        }

        [data-testid="stSidebar"] [data-testid="stBaseButton-primary"] {
            background: #ffffff !important;
            border-color: #ffffff !important;
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.15);
        }

        [data-testid="stSidebar"] [data-testid="stBaseButton-primary"] p {
            color: #0d3325 !important;
            font-weight: 700 !important;
        }

        .sidebar-note {
            padding: 0.85rem 1rem;
            color: #c2e2d0;
            font-size: 0.8rem;
            line-height: 1.5;
            background: rgba(0, 0, 0, 0.18);
            border-radius: 0.75rem;
            border-left: 3px solid #289e68;
        }

        .demo-mode-note {
            padding: 0.75rem 0.9rem;
            margin: 0.5rem 0 0.8rem;
            color: #ffffff;
            background: rgba(255, 193, 7, 0.15);
            border: 1px solid rgba(255, 193, 7, 0.45);
            border-radius: 0.75rem;
            font-size: 0.82rem;
            line-height: 1.55;
        }
        .demo-mode-note strong { color: #ffe29a; }
        [data-testid="stSidebar"] [data-testid="stSelectbox"] label p {
            color: #ffffff;
            font-weight: 600;
        }

        .ube-header.approval-header {
            background: linear-gradient(115deg, #10253d 0%, #143b55 55%, #087e82 100%);
            box-shadow: 0 12px 30px rgba(16, 37, 61, 0.18);
        }
        .approval-summary {
            padding: 0.9rem 1.2rem;
            margin: 0.7rem 0 1.3rem;
            border-left: 4px solid #0b8d90;
            border-radius: 0.75rem;
            background: #eaf5f5;
            color: #17354a;
            font-weight: 600;
        }
        .approval-status {
            display: inline-block;
            margin: 0.25rem 0 1rem;
            padding: 0.35rem 0.9rem;
            border-radius: 999px;
            font-size: 1rem;
            font-weight: 700;
        }
        .approval-status-approved { color: #08645c; background: #d9f3ed; }
        .approval-status-rejected { color: #9f3333; background: #fae7e7; }
        .approval-status-pending { color: #71520d; background: #fff1c8; }
        .approval-status-draft { color: #284c6c; background: #e5eef7; }

        .history-empty {
            padding: 2.8rem 1.5rem;
            margin-top: 1rem;
            text-align: center;
            color: #214057;
            background: #f4f9fa;
            border: 1px dashed #9ac9ca;
            border-radius: 1rem;
        }
        .history-empty strong { display: block; font-size: 1.15rem; color: #10253d; }
        .history-empty span { display: block; margin-top: 0.4rem; color: #5c7380; }
        .history-summary {
            margin: 1rem 0;
            padding: 0.9rem 1.2rem;
            color: #eefcfc;
            background: linear-gradient(100deg, #10253d, #087e82);
            border-radius: 0.8rem;
            font-weight: 600;
        }

        /* Main Header Banner */
        .ube-header {
            padding: 2rem 2.2rem;
            margin-bottom: 1.8rem;
            color: white;
            background: linear-gradient(125deg, #124e36 0%, #1e6d4c 60%, #298d63 100%);
            border-radius: 1.25rem;
            box-shadow: 0 10px 30px rgba(18, 78, 54, 0.18);
        }

        .ube-header h1 {
            margin: 0;
            color: #ffffff;
            font-size: 2.1rem;
            font-weight: 700;
        }

        .ube-header p {
            margin: 0.4rem 0 0;
            color: #d1ebd9;
            font-size: 1rem;
            font-weight: 400;
        }

        /* Content Area Styling */
        .page-kicker {
            color: #1e6d4c;
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            margin-bottom: 0.3rem;
        }

        .page-intro {
            color: #435e52;
            font-size: 1.05rem;
            line-height: 1.7;
            margin: 0.4rem 0 1.2rem;
        }

        /* Custom Placeholder Box */
        .custom-placeholder {
            padding: 1.1rem 1.3rem;
            background-color: #eaf5ee;
            border: 1px solid #c5e4d2;
            border-left: 4px solid #1e6d4c;
            border-radius: 0.75rem;
            color: #1a4d36;
            font-size: 0.95rem;
            line-height: 1.6;
        }

        /* Visual Card Styling */
        .visual-card {
            position: relative;
            overflow: hidden;
            min-height: 185px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 1.2rem 0.9rem;
            background: linear-gradient(145deg, #ffffff 0%, #f0f7f2 100%);
            border: 1px solid #d8e9dd;
            border-radius: 1rem;
            box-shadow: 0 8px 22px rgba(22, 78, 55, 0.07);
            text-align: center;
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }

        .visual-card:hover {
            transform: translateY(-3px);
            box-shadow: 0 18px 40px rgba(22, 78, 55, 0.12);
        }

        .visual-card::before, .visual-card::after {
            content: "";
            position: absolute;
            border-radius: 50%;
            background: rgba(30, 109, 76, 0.06);
        }

        .visual-card::before { width: 95px; height: 95px; top: -40px; right: -30px; }
        .visual-card::after { width: 70px; height: 70px; bottom: -35px; left: -20px; }

        .visual-icon {
            display: grid;
            place-items: center;
            width: 64px;
            height: 64px;
            margin-bottom: 0.7rem;
            color: #ffffff;
            background: linear-gradient(135deg, #227b55, #124e36);
            border: 4px solid #ffffff;
            border-radius: 1.2rem;
            box-shadow: 0 8px 18px rgba(18, 78, 54, 0.18);
            transform: rotate(-4deg);
            transition: transform 0.3s ease;
        }

        .visual-card:hover .visual-icon {
            transform: rotate(0deg) scale(1.05);
        }

        .visual-icon svg { width: 30px; height: 30px; }

        .visual-title {
            color: #124e36;
            font-size: 1rem;
            font-weight: 700;
            line-height: 1.4;
        }

        .visual-subtitle {
            color: #5c7a6c;
            font-size: 0.78rem;
            line-height: 1.45;
            margin-top: 0.2rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# 3. Session State Initialization
if "selected_page" not in st.session_state:
    st.session_state.selected_page = "บันทึก Safety Talk"

DEMO_USERS = {
    "demo_user": "USER",
    "demo_approver": "APPROVER",
    "demo_admin": "ADMIN",
}

def select_page(page_name: str) -> None:
    st.session_state.selected_page = page_name


def reset_dashboard_department() -> None:
    st.session_state.dashboard_department = "ทั้งหมด"


def reset_queue_department() -> None:
    st.session_state.queue_department = "ทั้งหมด"


def reset_history_department() -> None:
    st.session_state.history_department = "ทั้งหมด"

# 4. Sidebar Navigation
with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-brand">
            <div class="sidebar-icon">🦺</div>
            <div>
                <h2>UBE Safety Talk</h2>
                <span>WORKSHOP • DAY 1</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.divider()
    app_url = st.context.url
    local_host = urlsplit(app_url).hostname if app_url else None
    if local_host in ("localhost", "127.0.0.1", "::1"):
        if st.session_state.get("current_demo_user") not in DEMO_USERS:
            st.session_state.current_demo_user = "demo_user"
        st.markdown(
            '<div class="demo-mode-note"><strong>DEMO MODE</strong><br>'
            'NO AUTHENTICATION — สลับบทบาทเพื่อสาธิตเท่านั้น</div>',
            unsafe_allow_html=True,
        )
        st.selectbox(
            "Demo User Switcher",
            tuple(DEMO_USERS),
            format_func=lambda account: f"{account} · {DEMO_USERS[account]}",
            key="current_demo_user",
        )
    st.divider()
    st.markdown('<div class="menu-label">เมนูใช้งาน</div>', unsafe_allow_html=True)
    
    menu_items = (
        ("📝  บันทึก Safety Talk", "บันทึก Safety Talk"),
        ("📊  Dashboard", "Dashboard"),
        ("📋  ประวัติรายงาน", "ประวัติรายงาน"),
    )
    current_role = Role(DEMO_USERS[st.session_state.current_demo_user]) if local_host in ("localhost", "127.0.0.1", "::1") else Role.USER
    if has_permission(current_role, Permission.APPROVE_REPORT):
        menu_items += (("✅  Approval Queue", "Approval Queue"),)
    if has_permission(current_role, Permission.VIEW_ADMIN):
        menu_items += (("⚙️  Admin (DEMO)", "Admin (DEMO)"),)
    
    for button_label, page_name in menu_items:
        st.button(
            button_label,
            key=f"menu_{page_name}",
            type=(
                "primary"
                if st.session_state.selected_page == page_name
                else "secondary"
            ),
            use_container_width=True,
            on_click=select_page,
            args=(page_name,),
        )
        
    st.divider()
    st.markdown(
        """
        <div class="sidebar-note">
            📌 <strong>ระบบสาธิตภายในเครื่อง</strong><br>
            สำหรับการอบรมเท่านั้น
        </div>
        """,
        unsafe_allow_html=True,
    )

# 5. Page Content Configuration
selected_page = st.session_state.selected_page
page_permissions = {
    "บันทึก Safety Talk": Permission.CREATE_REPORT,
    "Dashboard": Permission.VIEW_DASHBOARD,
    "ประวัติรายงาน": Permission.VIEW_DASHBOARD,
    "รายละเอียดรายงาน": Permission.VIEW_DASHBOARD,
    "Approval Queue": Permission.APPROVE_REPORT,
    "Admin (DEMO)": Permission.VIEW_ADMIN,
}
if selected_page not in page_permissions or not has_permission(current_role, page_permissions[selected_page]):
    st.error("ไม่มีสิทธิ์เข้าหน้านี้ใน DEMO MODE")
    st.stop()

repository = get_repository()
try:
    repository.ensure_ready()
except (OSError, ValueError, sqlite3.DatabaseError) as error:
    st.error(f"ไม่สามารถเปิดฐานข้อมูล Safety Talk ได้: {error}")
    st.stop()

header_class = (
    "ube-header approval-header"
    if selected_page in ("Approval Queue", "ประวัติรายงาน", "รายละเอียดรายงาน")
    else "ube-header"
)
st.markdown(
    f"""
    <div class="{header_class}">
        <h1>UBE Safety Talk</h1>
        <p>ระบบบันทึกและติดตามกิจกรรม Safety Talk สำหรับ UBE และ UBS</p>
    </div>
    """,
    unsafe_allow_html=True,
)

page_content = {
    "บันทึก Safety Talk": {
        "kicker": "SAFETY TALK RECORD",
        "title": "บันทึก Safety Talk",
        "intro": "เริ่มต้นบันทึกการสื่อสารด้านความปลอดภัยของทีมในที่เดียว",
        "placeholder": "💡 พื้นที่สำหรับกรอกวันที่ บริษัท หน่วยงาน ผู้รายงาน หัวข้อ จำนวนผู้เข้าร่วม และแนบหลักฐาน (จะพัฒนาในขั้นตอนถัดไป)",
        "visual_title": "บันทึกเรื่องราวความปลอดภัย",
        "visual_subtitle": "ทุกการพูดคุย ช่วยสร้างความปลอดภัยร่วมกัน",
        "icon": '<path d="M9 5h10a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h1"/><rect x="7" y="3" width="10" height="4" rx="2"/><path d="M8 12h8M8 16h6"/>',
    },
    "Dashboard": {
        "kicker": "ACTIVITY OVERVIEW",
        "title": "Dashboard",
        "intro": "ดูภาพรวมกิจกรรม Safety Talk ของ UBE และ UBS ได้อย่างเข้าใจง่าย",
        "placeholder": "💡 พื้นที่สำหรับแสดงจำนวนรายงาน จำนวนผู้เข้าร่วม รายงานของ UBE/UBS และกิจกรรมรายเดือน (จะพัฒนาในขั้นตอนถัดไป)",
        "visual_title": "ภาพรวมกิจกรรม",
        "visual_subtitle": "ติดตามการสื่อสารด้านความปลอดภัย",
        "icon": '<path d="M4 20h16M6 17v-5M12 17V5M18 17V9"/><circle cx="6" cy="9" r="1"/><circle cx="18" cy="6" r="1"/>',
    },
    "ประวัติรายงาน": {
        "kicker": "REPORT HISTORY",
        "title": "ประวัติรายงาน",
        "intro": "ค้นหาและตรวจสอบรายงาน Safety Talk ที่บัญชี Demo นี้มีสิทธิ์ดู",
        "placeholder": "💡 พื้นที่สำหรับค้นหาและตรวจสอบรายการ Safety Talk ที่บันทึกไว้ (จะพัฒนาในขั้นตอนถัดไป)",
        "visual_title": "ค้นหาประวัติได้สะดวก",
        "visual_subtitle": "ทบทวนข้อมูลกิจกรรมที่ผ่านมา",
        "icon": '<rect x="4" y="3" width="13" height="17" rx="2"/><path d="M8 8h5M8 12h4"/><circle cx="17" cy="17" r="3"/><path d="m19.2 19.2 2.3 2.3"/>',
    },
    "รายละเอียดรายงาน": {
        "kicker": "REPORT DETAIL",
        "title": "รายละเอียดรายงาน",
        "intro": "ข้อมูลกิจกรรม สถานะ และลำดับการดำเนินการของรายงานที่เลือก",
    },
    "Approval Queue": {
        "kicker": "PENDING REVIEW · DEMO",
        "title": "Approval Queue",
        "intro": "ตรวจสอบรายงาน Safety Talk ที่ส่งขออนุมัติแล้ว ก่อนตัดสินใจอนุมัติหรือปฏิเสธ",
        "visual_title": "รายการรอตรวจสอบ",
        "visual_subtitle": "การดำเนินการทุกครั้งถูกบันทึกใน Action History",
        "icon": '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 10h8M8 14h5"/>',
    },
    "Admin (DEMO)": {
        "kicker": "DEMO ADMIN",
        "title": "Admin (DEMO)",
        "intro": "พื้นที่สาธิตสิทธิ์ ADMIN สำหรับ Workshop Day 1",
        "placeholder": "ยังไม่มีฟังก์ชันจัดการระบบ ข้อมูล หรือผู้ใช้จริง",
        "visual_title": "สิทธิ์สาธิต",
        "visual_subtitle": "NO AUTHENTICATION — ไม่ใช่ระบบจัดการจริง",
        "icon": '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l2 2"/>',
    },
}

content = page_content[selected_page]

# 6. Render Main Layout
if selected_page in ("Approval Queue", "ประวัติรายงาน", "รายละเอียดรายงาน"):
    text_column, visual_column = st.container(), None
else:
    text_column, visual_column = st.columns([4, 1], gap="large")

with text_column:
    st.markdown(f'<div class="page-kicker">{content["kicker"]}</div>', unsafe_allow_html=True)
    st.header(content["title"])
    st.markdown(f'<p class="page-intro">{content["intro"]}</p>', unsafe_allow_html=True)
    if selected_page == "บันทึก Safety Talk":
        departments_path = Path(__file__).resolve().parent / "config" / "departments.json"
        try:
            with departments_path.open(encoding="utf-8") as file:
                departments = json.load(file)
            if not isinstance(departments, dict) or any(
                not isinstance(departments.get(name), list)
                or not departments[name]
                or not all(isinstance(item, str) and item.strip() for item in departments[name])
                for name in ("UBE", "UBS")
            ):
                raise ValueError("ข้อมูลหน่วยงานไม่ถูกต้อง")
        except (OSError, ValueError):
            st.error("ไม่สามารถโหลดรายชื่อหน่วยงานได้ กรุณาตรวจสอบ config/departments.json")
        else:
            company = st.selectbox("บริษัท *", ("UBE", "UBS"), index=None, placeholder="เลือกบริษัท")
            with st.form("safety_talk_form"):
                department = st.selectbox(
                    "หน่วยงาน *",
                    departments[company] if company else [],
                    index=None,
                    placeholder="เลือกหน่วยงาน" if company else "กรุณาเลือกบริษัทก่อน",
                    key=f"department_{company}",
                    disabled=company is None,
                )
                date_column, participants_column = st.columns(2)
                with date_column:
                    talk_date = st.date_input("วันที่สื่อสาร *", value=None)
                with participants_column:
                    participants = st.number_input(
                        "จำนวนผู้เข้าร่วม (คน) *", min_value=1, value=1, step=1
                    )
                reporter = st.text_input("ชื่อผู้รายงาน *")
                topic = st.text_input("หัวข้อ Safety Talk *")
                notes = st.text_area(
                    "หมายเหตุรายละเอียด (ไม่บังคับ • ส่วนขยายจากโจทย์)",
                    help="เป็นช่องเพิ่มเติมสำหรับ workshop และยังไม่ได้บันทึกลงฐานข้อมูล",
                )
                st.caption("หมายเหตุเป็นส่วนขยายจากโจทย์ และยังไม่ได้บันทึกลงฐานข้อมูล")
                st.caption("ไฟล์แนบสำหรับข้อมูลทดสอบเท่านั้น ห้ามใช้ข้อมูลจริงหรือเอกสารลับ")
                uploads = st.file_uploader(
                    "แนบหลักฐาน (ไม่บังคับ • น้อยกว่า 5 MB ต่อไฟล์)",
                    type=["jpg", "jpeg", "png", "pdf"],
                    accept_multiple_files=True,
                )
                submitted = st.form_submit_button("บันทึกรายงาน")
            if submitted:
                report = {
                    "talk_date": talk_date,
                    "company": company,
                    "department": department,
                    "reporter": reporter,
                    "topic": topic,
                    "participants": participants,
                }
                errors = validate_report(report, departments)
                if errors:
                    for error in errors:
                        st.error(error)
                else:
                    try:
                        report_id = repository.create_report(
                            report, uploads,
                            st.session_state.get("current_demo_user", "demo_user"),
                            current_role,
                        )
                    except AuthorizationError:
                        st.error("ไม่มีสิทธิ์บันทึกรายงานใน DEMO MODE")
                    except PermissionError:
                        st.error(
                            "ไม่สามารถเขียนฐานข้อมูล SQLite หรือไฟล์แนบได้ "
                            "กรุณาตรวจสิทธิ์เขียนโฟลเดอร์ data แล้วลองอีกครั้ง"
                        )
                    except (OSError, ValueError, sqlite3.DatabaseError) as error:
                        st.error(f"ไม่สามารถบันทึกรายงานได้: {error}")
                    else:
                        st.success(f"บันทึกรายงานสำเร็จ: {report_id}")
    elif selected_page == "Dashboard":
        try:
            reports = pd.DataFrame(repository.list_reports(), columns=CSV_COLUMNS)
        except (OSError, ValueError, sqlite3.DatabaseError) as error:
            st.error(f"ไม่สามารถอ่านข้อมูล Dashboard ได้: {error}")
        else:
            required_columns = set(CSV_COLUMNS)
            if not required_columns.issubset(reports.columns):
                st.error("ข้อมูลรายงานไม่มีคอลัมน์ที่จำเป็นสำหรับ Dashboard")
            else:
                st.caption("ข้อมูลรายงานที่บันทึกใน SQLite (DEMO MODE)")
                date_text = reports["talk_date"].astype("string").str.strip()
                slash_dates = date_text.str.contains("/", regex=False).fillna(False)
                parsed_dates = pd.Series(pd.NaT, index=reports.index, dtype="datetime64[ns]")
                parsed_dates.loc[slash_dates] = pd.to_datetime(
                    date_text.loc[slash_dates], format="%d/%m/%Y", errors="coerce"
                )
                parsed_dates.loc[~slash_dates] = pd.to_datetime(
                    date_text.loc[~slash_dates], errors="coerce"
                )

                filter_row_one = st.columns(2)
                filter_row_two = st.columns(2)
                with filter_row_one[0]:
                    company_filter = st.selectbox(
                        "บริษัท", ("ทั้งหมด", "UBE", "UBS"),
                        key="dashboard_company", on_change=reset_dashboard_department,
                    )
                company_reports = reports
                if company_filter != "ทั้งหมด":
                    company_reports = reports.loc[reports["company"] == company_filter]
                departments = company_reports["department"].dropna().astype(str).str.strip()
                department_options = ("ทั้งหมด", *dict.fromkeys(departments[departments != ""]))
                if st.session_state.get("dashboard_department") not in department_options:
                    st.session_state.dashboard_department = "ทั้งหมด"
                with filter_row_one[1]:
                    department_filter = st.selectbox(
                        "หน่วยงาน", department_options, key="dashboard_department"
                    )
                years = sorted(parsed_dates.dropna().dt.year.unique().tolist())
                with filter_row_two[0]:
                    year_filter = st.selectbox("ปี", ("ทั้งหมด", *years), key="dashboard_year")
                with filter_row_two[1]:
                    month_filter = st.selectbox(
                        "เดือน", ("ทั้งหมด", *range(1, 13)), key="dashboard_month",
                        format_func=lambda value: value if value == "ทั้งหมด" else f"{value:02d}",
                    )

                filtered = company_reports
                if department_filter != "ทั้งหมด":
                    filtered = filtered.loc[filtered["department"] == department_filter]
                if year_filter != "ทั้งหมด":
                    filtered = filtered.loc[parsed_dates.loc[filtered.index].dt.year == year_filter]
                if month_filter != "ทั้งหมด":
                    filtered = filtered.loc[parsed_dates.loc[filtered.index].dt.month == month_filter]

                participant_total = int(
                    pd.to_numeric(filtered["participants"], errors="coerce").fillna(0).sum()
                )
                company_counts = filtered["company"].value_counts()
                first_row = st.columns(2)
                second_row = st.columns(2)
                first_row[0].metric("จำนวนรายงาน Safety Talk", len(filtered))
                first_row[1].metric("จำนวนผู้เข้าร่วมทั้งหมด", participant_total)
                second_row[0].metric("จำนวนรายงาน UBE", int(company_counts.get("UBE", 0)))
                second_row[1].metric("จำนวนรายงาน UBS", int(company_counts.get("UBS", 0)))
                st.subheader("จำนวนกิจกรรม Safety Talk รายเดือน")
                valid_dates = parsed_dates.loc[filtered.index].dropna()
                if valid_dates.empty:
                    st.info("ยังไม่มีวันที่สื่อสารที่ถูกต้องสำหรับแสดงกราฟรายเดือน")
                else:
                    monthly_counts = (
                        valid_dates.dt.to_period("M")
                        .astype(str)
                        .value_counts()
                        .sort_index()
                        .rename_axis("เดือน")
                        .reset_index(name="จำนวนกิจกรรม")
                    )
                    st.bar_chart(monthly_counts, x="เดือน", y="จำนวนกิจกรรม")
                export_data = filtered.loc[:, CSV_COLUMNS].to_csv(index=False).encode("utf-8-sig")
                export_date = datetime.now(ZoneInfo("Asia/Bangkok")).strftime("%Y%m%d")
                st.download_button(
                    "ดาวน์โหลด CSV ที่กรองแล้ว",
                    data=export_data,
                    file_name=f"SafetyTalk_{export_date}.csv",
                    mime="text/csv",
                    disabled=filtered.empty,
                )
    elif selected_page == "ประวัติรายงาน":
        actor = st.session_state.get("current_demo_user")
        if actor is None:
            st.info("ประวัติรายงาน DEMO เปิดดูได้จาก localhost เท่านั้น")
        else:
            if "approval_success" in st.session_state:
                st.success(st.session_state.pop("approval_success"))
            with st.container(border=True):
                st.subheader("ค้นหารายงาน")
                search_column, company_column = st.columns([2, 1])
                with search_column:
                    query = st.text_input(
                        "Report ID, หัวข้อ หรือผู้รายงาน", key="history_search",
                        placeholder="พิมพ์คำค้นหา",
                    ).strip()
                with company_column:
                    company_filter = st.selectbox(
                        "บริษัท", ("ทั้งหมด", "UBE", "UBS"), key="history_company",
                        on_change=reset_history_department,
                    )
                try:
                    departments = repository.list_history_departments(
                        actor, current_role,
                        None if company_filter == "ทั้งหมด" else company_filter,
                    )
                except (AuthorizationError, OSError, ValueError, sqlite3.DatabaseError) as error:
                    st.error(f"ไม่สามารถอ่านตัวกรองหน่วยงานได้: {error}")
                    st.stop()
                department_options = ("ทั้งหมด", *departments)
                if st.session_state.get("history_department") not in department_options:
                    st.session_state.history_department = "ทั้งหมด"
                department_column, status_column = st.columns(2)
                with department_column:
                    department_filter = st.selectbox(
                        "หน่วยงาน", department_options, key="history_department",
                    )
                with status_column:
                    status_filter = st.selectbox(
                        "สถานะ", ("ทั้งหมด", *(item.value for item in Status)),
                        key="history_status",
                    )
                date_from_column, date_to_column = st.columns(2)
                with date_from_column:
                    date_from = st.date_input("วันที่เริ่มต้น", value=None, key="history_date_from")
                with date_to_column:
                    date_to = st.date_input("วันที่สิ้นสุด", value=None, key="history_date_to")
            try:
                rows = repository.search_history(
                    actor, current_role, query=query,
                    company=None if company_filter == "ทั้งหมด" else company_filter,
                    department=None if department_filter == "ทั้งหมด" else department_filter,
                    date_from=date_from, date_to=date_to,
                    status=None if status_filter == "ทั้งหมด" else status_filter,
                )
            except (AuthorizationError, OSError, ValueError, sqlite3.DatabaseError) as error:
                st.error(f"ไม่สามารถค้นหารายงานได้: {error}")
            else:
                if not rows:
                    st.markdown(
                        '<div class="history-empty"><strong>ไม่พบรายงานที่แสดงได้</strong>'
                        '<span>ลองปรับคำค้นหาหรือตัวกรอง หรือบันทึกรายงานใหม่</span></div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f'<div class="history-summary">พบ {len(rows)} รายงานที่มีสิทธิ์ดู'
                        f' · {current_role.value} · DEMO MODE</div>',
                        unsafe_allow_html=True,
                    )
                    history_columns = {
                        "report_id": "Report ID", "talk_date": "วันที่สื่อสาร",
                        "company": "บริษัท", "department": "หน่วยงาน",
                        "topic": "หัวข้อ", "reporter": "ผู้รายงาน",
                        "participants": "ผู้เข้าร่วม", "status": "สถานะ",
                    }
                    st.dataframe(
                        pd.DataFrame(rows).loc[:, list(history_columns)].rename(
                            columns=history_columns
                        ),
                        hide_index=True, width="stretch",
                    )
                    report_ids = [row["report_id"] for row in rows]
                    if st.session_state.get("history_report_id") not in report_ids:
                        st.session_state.history_report_id = report_ids[0]
                    selected_id = st.selectbox(
                        "เลือกรายงาน", report_ids, key="history_report_id",
                    )
                    if st.button("ดูรายละเอียดรายงาน", key="history_open_detail", type="primary"):
                        st.session_state.selected_report_id = selected_id
                        select_page("รายละเอียดรายงาน")
                        st.rerun()
    elif selected_page == "รายละเอียดรายงาน":
        if st.button("← กลับไปประวัติรายงาน", key="history_back"):
            select_page("ประวัติรายงาน")
            st.rerun()
        report_id = st.session_state.get("selected_report_id")
        actor = st.session_state.get("current_demo_user")
        if not report_id or not actor:
            st.markdown(
                '<div class="history-empty"><strong>ยังไม่ได้เลือกรายงาน</strong>'
                '<span>กลับไปหน้า History เพื่อเลือกรายงานที่ต้องการดู</span></div>',
                unsafe_allow_html=True,
            )
        else:
            try:
                detail = repository.get_visible_report_detail(report_id, actor, current_role)
            except (AuthorizationError, OSError, ValueError, sqlite3.DatabaseError) as error:
                st.error(f"ไม่สามารถอ่านรายละเอียดรายงานได้: {error}")
            else:
                if detail is None:
                    st.markdown(
                        '<div class="history-empty"><strong>ไม่พบรายงานหรือไม่มีสิทธิ์ดู</strong>'
                        '<span>กรุณาเลือกรายงานจากหน้า History อีกครั้ง</span></div>',
                        unsafe_allow_html=True,
                    )
                else:
                    report, actions = detail
                    status = Status(report["status"])
                    st.markdown(
                        f'<span class="approval-status approval-status-{status.value.lower()}">'
                        f'{status.value}</span>', unsafe_allow_html=True,
                    )
                    with st.container(border=True):
                        st.subheader(report["report_id"])
                        first, second, third = st.columns(3)
                        first.write(f"**วันที่สื่อสาร**  \n{report['talk_date']}")
                        second.write(f"**บริษัท**  \n{report['company']}")
                        third.write(f"**จำนวนผู้เข้าร่วม**  \n{report['participants']} คน")
                        st.write("**หน่วยงาน**")
                        st.write(report["department"])
                        st.write("**ผู้รายงาน**")
                        st.write(report["reporter"])
                        st.write("**หัวข้อ Safety Talk**")
                        st.write(report["topic"])
                        st.write("**ไฟล์หลักฐาน**")
                        try:
                            evidence_names = json.loads(report["evidence_files"])
                            if not isinstance(evidence_names, list):
                                raise ValueError("รูปแบบไฟล์แนบไม่ถูกต้อง")
                        except (TypeError, ValueError):
                            st.caption("ข้อมูลไฟล์แนบไม่ถูกต้อง")
                        else:
                            st.write(", ".join(str(name) for name in evidence_names) or "ไม่มีไฟล์แนบ")
                        st.caption(f"สร้างเมื่อ {report['created_at']} · เจ้าของ Demo: {report['owner_actor'] or 'ไม่ระบุ'}")
                    action = None
                    if status is Status.DRAFT and report["owner_actor"] == actor:
                        if st.button("ส่งขออนุมัติ", key="detail_submit", type="primary"):
                            action = Action.SUBMIT
                    elif status is Status.REJECTED and report["owner_actor"] == actor:
                        if st.button("แก้ไขเป็น Draft (DEMO)", key="detail_revise"):
                            action = Action.REVISE
                    elif status is Status.PENDING and has_permission(current_role, Permission.APPROVE_REPORT):
                        st.caption("ตรวจสอบและตัดสินใจได้ใน Approval Queue")
                    if action is not None:
                        try:
                            new_status = repository.transition(
                                report_id, action, actor=actor, role=current_role,
                            )
                        except (AuthorizationError, OSError, ValueError, sqlite3.DatabaseError) as error:
                            st.error(f"ไม่สามารถเปลี่ยนสถานะได้: {error}")
                        else:
                            st.session_state.approval_success = (
                                f"ส่งขออนุมัติสำเร็จ: {report_id} (Pending)"
                                if action is Action.SUBMIT else f"{report_id}: {new_status.value} (DEMO)"
                            )
                            st.rerun()
                    if "approval_success" in st.session_state:
                        st.success(st.session_state.pop("approval_success"))
                    st.subheader("Approval History")
                    if not actions:
                        st.markdown(
                            '<div class="history-empty"><strong>ยังไม่มี Approval History</strong>'
                            '<span>รายการจะปรากฏเมื่อมีการส่งหรือดำเนินการอนุมัติ</span></div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        action_frame = pd.DataFrame(actions)
                        action_frame["timestamp"] = (
                            pd.to_datetime(action_frame["timestamp"], errors="coerce", utc=True)
                            .dt.tz_convert("Asia/Bangkok").dt.strftime("%d/%m/%Y %H:%M:%S")
                        )
                        action_columns = {
                            "actor": "ผู้ทำรายการ", "timestamp": "เวลา (กรุงเทพฯ)",
                            "old_status": "สถานะเดิม", "new_status": "สถานะใหม่",
                            "action": "Action", "comment": "เหตุผล/หมายเหตุ",
                        }
                        st.dataframe(
                            action_frame.loc[:, list(action_columns)].rename(columns=action_columns),
                            hide_index=True, width="stretch",
                        )
    elif selected_page == "Approval Queue":
        service = repository
        try:
            pending_reports = service.list_pending(current_role)
        except (AuthorizationError, OSError, ValueError) as error:
            st.error(f"ไม่สามารถอ่าน Approval Queue ได้: {error}")
        else:
            if "queue_success" in st.session_state:
                st.success(st.session_state.pop("queue_success"))
            st.markdown(
                f'<div class="approval-summary">รายงานรอตรวจสอบ {len(pending_reports)} รายการ · '
                'DEMO MODE · NO AUTHENTICATION</div>',
                unsafe_allow_html=True,
            )
            if not pending_reports:
                st.info("ยังไม่มีรายงานสถานะ Pending สำหรับตรวจสอบ")
            else:
                queue = pd.DataFrame(pending_reports)
                search_column, company_column, department_column = st.columns([2, 1, 1])
                with search_column:
                    query = st.text_input(
                        "ค้นหา Report ID หัวข้อ หน่วยงาน หรือผู้ส่ง", key="queue_search"
                    ).strip()
                with company_column:
                    company_filter = st.selectbox(
                        "บริษัท", ("ทั้งหมด", "UBE", "UBS"),
                        key="queue_company", on_change=reset_queue_department,
                    )
                company_queue = queue
                if company_filter != "ทั้งหมด":
                    company_queue = queue.loc[queue["company"] == company_filter]
                departments = company_queue["department"].dropna().astype(str).str.strip()
                department_options = ("ทั้งหมด", *dict.fromkeys(departments[departments != ""]))
                if st.session_state.get("queue_department") not in department_options:
                    st.session_state.queue_department = "ทั้งหมด"
                with department_column:
                    department_filter = st.selectbox(
                        "หน่วยงาน", department_options, key="queue_department"
                    )

                filtered_queue = company_queue
                if department_filter != "ทั้งหมด":
                    filtered_queue = filtered_queue.loc[
                        filtered_queue["department"] == department_filter
                    ]
                if query:
                    matches = pd.Series(False, index=filtered_queue.index)
                    for column in ("report_id", "topic", "department", "submitted_by"):
                        matches |= filtered_queue[column].astype(str).str.contains(
                            query, case=False, regex=False, na=False
                        )
                    filtered_queue = filtered_queue.loc[matches]

                st.caption(f"พบ {len(filtered_queue)} จาก {len(pending_reports)} รายงาน Pending")
                if filtered_queue.empty:
                    st.info("ไม่พบรายงาน Pending ที่ตรงกับคำค้นหาและตัวกรอง")
                else:
                    display_columns = {
                        "report_id": "Report ID",
                        "talk_date": "วันที่",
                        "company": "บริษัท",
                        "department": "หน่วยงาน",
                        "topic": "หัวข้อ",
                        "submitted_by": "ผู้ส่ง",
                        "status": "สถานะ",
                    }
                    st.dataframe(
                        filtered_queue.loc[:, list(display_columns)].rename(columns=display_columns),
                        hide_index=True,
                        width="stretch",
                    )
                    selected_id = st.selectbox(
                        "เลือกรายงานเพื่อดำเนินการ", filtered_queue["report_id"].tolist(),
                        key="queue_report_id",
                    )
                    reject_reason = st.text_area(
                        "เหตุผลเมื่อปฏิเสธ (บังคับสำหรับ Reject)",
                        key=f"queue_reject_reason_{selected_id}",
                    )
                    reject_confirmed = st.checkbox(
                        f"ยืนยันการปฏิเสธรายงาน {selected_id}",
                        key=f"queue_reject_confirm_{selected_id}",
                    )
                    approve_column, reject_column = st.columns(2)
                    approve_clicked = approve_column.button(
                        "อนุมัติรายงาน", key="queue_approve", type="primary"
                    )
                    reject_clicked = reject_column.button(
                        "ปฏิเสธรายงาน", key="queue_reject"
                    )
                    if approve_clicked or reject_clicked:
                        action = Action.APPROVE if approve_clicked else Action.REJECT
                        if reject_clicked and not reject_reason.strip():
                            st.error("กรุณาระบุเหตุผลก่อนปฏิเสธรายงาน")
                        elif reject_clicked and not reject_confirmed:
                            st.error("กรุณายืนยันการปฏิเสธรายงานที่เลือก")
                        else:
                            try:
                                new_status = service.transition(
                                    selected_id, action,
                                    actor=st.session_state.current_demo_user,
                                    role=current_role,
                                    comment="" if approve_clicked else reject_reason,
                                )
                            except (AuthorizationError, OSError, ValueError) as error:
                                st.error(f"ไม่สามารถดำเนินการกับ {selected_id} ได้: {error}")
                            else:
                                st.session_state.queue_success = (
                                    f"{selected_id}: {new_status.value} (DEMO)"
                                )
                                st.session_state.queue_history_target = selected_id
                                st.rerun()

            st.divider()
            st.subheader("สถานะและ Approval History")
            try:
                review_ids = service.list_report_ids(current_role)
            except (AuthorizationError, OSError, ValueError) as error:
                st.error(f"ไม่สามารถอ่านประวัติการอนุมัติได้: {error}")
            else:
                if not review_ids:
                    st.info("ยังไม่มีรายงานสำหรับแสดง Approval History")
                else:
                    history_target = st.session_state.pop("queue_history_target", None)
                    if history_target in review_ids:
                        st.session_state.queue_history_id = history_target
                    elif st.session_state.get("queue_history_id") not in review_ids:
                        st.session_state.queue_history_id = review_ids[0]
                    history_id = st.selectbox(
                        "เลือก Report ID เพื่อดูสถานะและประวัติ", review_ids,
                        key="queue_history_id",
                    )
                    try:
                        review_status = service.get_status(history_id)
                        action_history = service.get_history(history_id)
                    except (OSError, ValueError) as error:
                        st.error(f"ไม่สามารถอ่านสถานะ {history_id} ได้: {error}")
                    else:
                        st.markdown(
                            f'<span class="approval-status approval-status-{review_status.value.lower()}">'
                            f'{review_status.value}</span>',
                            unsafe_allow_html=True,
                        )
                        if not action_history:
                            st.info("รายงานนี้ยังไม่มี Action History")
                        else:
                            history_frame = pd.DataFrame(action_history)
                            history_frame["timestamp"] = (
                                pd.to_datetime(history_frame["timestamp"], errors="coerce", utc=True)
                                .dt.tz_convert("Asia/Bangkok")
                                .dt.strftime("%d/%m/%Y %H:%M:%S")
                            )
                            history_columns = {
                                "actor": "ผู้ทำรายการ",
                                "timestamp": "เวลา (กรุงเทพฯ)",
                                "old_status": "สถานะเดิม",
                                "new_status": "สถานะใหม่",
                                "action": "Action",
                                "comment": "เหตุผล/หมายเหตุ",
                            }
                            st.dataframe(
                                history_frame.loc[:, list(history_columns)].rename(
                                    columns=history_columns
                                ),
                                hide_index=True,
                                width="stretch",
                            )
    elif selected_page == "Admin (DEMO)":
        require_permission(current_role, Permission.VIEW_ADMIN)
        st.info("หน้า Admin สำหรับสาธิตสิทธิ์เท่านั้น ไม่มีการจัดการผู้ใช้หรือข้อมูลจริง")
    else:
        st.markdown(f'<div class="custom-placeholder">{content["placeholder"]}</div>', unsafe_allow_html=True)

if visual_column is not None:
    with visual_column:
        st.markdown(
            f"""
            <div class="visual-card">
                <div class="visual-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                         stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"
                         aria-hidden="true">{content["icon"]}</svg>
                </div>
                <div class="visual-title">{content["visual_title"]}</div>
                <div class="visual-subtitle">{content["visual_subtitle"]}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.divider()
st.caption(
    "สำหรับการอบรมและสาธิตด้วยข้อมูลตัวอย่างเท่านั้น "
    "กรุณาอย่าใช้ข้อมูลส่วนบุคคลจริงหรือเอกสารลับ"
)
