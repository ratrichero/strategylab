"""
FastAPI dependencies cho dashboard auth.
Đọc JWT từ cookie, verify, trả về user.
"""

from fastapi import Request, HTTPException, Depends
from app.auth.jwt_utils import decode_token, get_cookie_name
from app.auth.models import DashboardUser
from app.db.session import SessionLocal


def get_current_user(request: Request) -> DashboardUser:
    """
    Dependency: lấy current user từ cookie JWT.
    Raise 401 nếu chưa login hoặc token invalid.
    """
    cookie_name = get_cookie_name()
    token = request.cookies.get(cookie_name)

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Token expired or invalid")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    db = SessionLocal()
    try:
        user = db.query(DashboardUser).filter(
            DashboardUser.id == int(user_id),
            DashboardUser.is_active == True
        ).first()

        if not user:
            raise HTTPException(status_code=401, detail="User not found or inactive")

        return user
    finally:
        db.close()


def require_admin(current_user: DashboardUser = Depends(get_current_user)) -> DashboardUser:
    """
    Dependency: require role ADMIN.
    Raise 403 nếu không đủ quyền.
    """
    if current_user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def require_authenticated(current_user: DashboardUser = Depends(get_current_user)) -> DashboardUser:
    """
    Dependency: chỉ cần đã login, không care role.
    """
    return current_user