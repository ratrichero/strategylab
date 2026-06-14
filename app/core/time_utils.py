"""
Time Utils — Single source of truth cho timezone handling.

Rule:
  - Lưu DB:    UTC (timestamptz)
  - Xử lý:     UTC aware
  - Hiển thị:  UTC+7 (chỉ ở layer này)
  - Filter ngày VN: convert range local -> UTC trước khi query
"""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, Tuple
import time as _time

# ── Constants ────────────────────────────────────────────────
UTC    = timezone.utc
VN_TZ  = ZoneInfo("Asia/Ho_Chi_Minh")


# ── Now ──────────────────────────────────────────────────────

def utc_now() -> datetime:
    """Luôn dùng cái này thay cho datetime.utcnow()."""
    return datetime.now(UTC)


def vn_now() -> datetime:
    """Giờ hiện tại theo UTC+7 — chỉ dùng để hiển thị / log."""
    return datetime.now(VN_TZ)


def vn_now_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """String UTC+7 để print/log."""
    return vn_now().strftime(fmt)


# ── Ensure UTC ───────────────────────────────────────────────

def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Nhận bất kỳ datetime nào → trả về UTC aware.
    - None       → None
    - naive      → gắn nhãn UTC (vì convention toàn hệ thống là UTC)
    - aware UTC  → giữ nguyên
    - aware khác → convert sang UTC
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # naive → assume UTC (đúng với convention hệ thống)
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# ── Convert hiển thị ─────────────────────────────────────────

def to_vn(dt: Optional[datetime]) -> Optional[datetime]:
    """UTC datetime → UTC+7. Chỉ dùng để hiển thị."""
    dt = ensure_utc(dt)
    if dt is None:
        return None
    return dt.astimezone(VN_TZ)


def to_vn_str(dt: Optional[datetime], fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """UTC datetime → string UTC+7."""
    vn = to_vn(dt)
    if vn is None:
        return ""
    return vn.strftime(fmt)


# ── Filter theo ngày VN ──────────────────────────────────────

def vn_day_to_utc_range(date_str: str) -> Tuple[datetime, datetime]:
    """
    Nhận string ngày VN "2026-06-14" 
    → trả về (start_utc, end_utc) để query DB.

    Ví dụ:
      "2026-06-14"
      → start = 2026-06-13 17:00:00 UTC
      → end   = 2026-06-14 17:00:00 UTC
    """
    from datetime import date
    d = date.fromisoformat(date_str)
    start_vn = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=VN_TZ)
    end_vn   = start_vn + timedelta(days=1)
    return start_vn.astimezone(UTC), end_vn.astimezone(UTC)


def vn_range_to_utc(
    start_str: Optional[str],
    end_str:   Optional[str],
    end_inclusive: bool = True
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    Nhận start/end string ngày VN (YYYY-MM-DD)
    → trả về UTC range để query DB.

    end_inclusive=True:
      end "2026-06-14" → end_utc = 2026-06-15 00:00 VN → 2026-06-14 17:00 UTC
    """
    start_utc = None
    end_utc   = None

    if start_str:
        s, _ = vn_day_to_utc_range(start_str)
        start_utc = s

    if end_str:
        _, e = vn_day_to_utc_range(end_str)
        end_utc = e  # đã là đầu ngày hôm sau, tức inclusive hết ngày end

    return start_utc, end_utc


# ── Expire / Cooldown helpers ─────────────────────────────────

def utc_after(hours: float = 0, minutes: float = 0, seconds: float = 0) -> datetime:
    """Tính thời điểm trong tương lai theo UTC."""
    return utc_now() + timedelta(hours=hours, minutes=minutes, seconds=seconds)


def utc_before(hours: float = 0, minutes: float = 0) -> datetime:
    """Tính thời điểm trong quá khứ theo UTC."""
    return utc_now() - timedelta(hours=hours, minutes=minutes)


def is_expired(dt: Optional[datetime]) -> bool:
    """Kiểm tra xem một timestamp (UTC) đã qua chưa."""
    if dt is None:
        return False
    return ensure_utc(dt) < utc_now()


# ── Pandas Timestamp ─────────────────────────────────────────

def pd_ts_to_utc(ts) -> Optional[datetime]:
    """
    Convert pandas Timestamp → UTC aware datetime.
    Dùng khi lấy candle_time từ DataFrame.
    """
    if ts is None:
        return None
    try:
        import pandas as pd
        if isinstance(ts, pd.Timestamp):
            dt = ts.to_pydatetime()
            return ensure_utc(dt)
        if isinstance(ts, datetime):
            return ensure_utc(ts)
    except Exception:
        pass
    return None