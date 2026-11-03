"""สิทธิ์สำหรับบทบาทสมมติใน Workshop; ไม่ใช่ระบบยืนยันตัวตน."""

from enum import StrEnum


class Role(StrEnum):
    USER = "USER"
    APPROVER = "APPROVER"
    ADMIN = "ADMIN"


class Permission(StrEnum):
    VIEW_DASHBOARD = "VIEW_DASHBOARD"
    CREATE_REPORT = "CREATE_REPORT"
    SUBMIT_REPORT = "SUBMIT_REPORT"
    APPROVE_REPORT = "APPROVE_REPORT"
    VIEW_ADMIN = "VIEW_ADMIN"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.USER: frozenset({
        Permission.VIEW_DASHBOARD,
        Permission.CREATE_REPORT,
        Permission.SUBMIT_REPORT,
    }),
    Role.APPROVER: frozenset({
        Permission.VIEW_DASHBOARD,
        Permission.CREATE_REPORT,
        Permission.SUBMIT_REPORT,
        Permission.APPROVE_REPORT,
    }),
    Role.ADMIN: frozenset(Permission),
}


class AuthorizationError(PermissionError):
    """Action ถูกปฏิเสธเพราะบทบาทไม่มีสิทธิ์."""


def has_permission(role: Role | str, permission: Permission | str) -> bool:
    """คืน False สำหรับบทบาทหรือชื่อสิทธิ์ที่ไม่รู้จัก."""
    try:
        return Permission(permission) in ROLE_PERMISSIONS[Role(role)]
    except (ValueError, KeyError, TypeError):
        return False


def require_permission(role: Role | str, permission: Permission | str) -> None:
    """ตรวจสิทธิ์ก่อนเรียก Action ที่อ่านหรือเปลี่ยนข้อมูล."""
    if not has_permission(role, permission):
        raise AuthorizationError(f"บทบาท {role} ไม่มีสิทธิ์ {permission}")
