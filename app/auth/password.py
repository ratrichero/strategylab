"""
Password hashing utilities.
Dùng bcrypt qua passlib.
"""

import hashlib
from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Hash plaintext password."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify plaintext against hashed password."""
    return _pwd_context.verify(plain, hashed)


def hash_secret(plain: str) -> str:
    """Hash machine secret bằng sha256. Dùng cho BOT_SECRET."""
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def verify_secret(plain: str, hashed: str) -> bool:
    """Verify machine secret bằng sha256."""
    return hashlib.sha256(plain.encode("utf-8")).hexdigest() == hashed