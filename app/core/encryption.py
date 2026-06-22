"""
Encryption helpers cho Multi-Bot Architecture.

3 use cases:
  1. At rest:     encrypt DB URL trong admin DB (ADMIN_MASTER_KEY)
  2. In transport: encrypt DB URL gửi từ admin → bot (derive từ bot_secret)
  3. Local cache:  encrypt bootstrap cache (derive từ bot_secret)

Algorithm: AES-256-GCM
"""

import os
import json
import hashlib
import secrets
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# ── Constants ─────────────────────────────────────────────
KEY_SIZE = 32   # 256 bits
NONCE_SIZE = 12  # 96 bits (recommended for GCM)


# ============================================================
# KEY DERIVATION
# ============================================================

def derive_key(secret: str, salt: str = "") -> bytes:
    """
    Derive 256-bit key từ secret string.
    Dùng SHA-256 (đơn giản, đủ cho use case này).

    Args:
        secret: bot_secret hoặc master_key
        salt: optional salt để tạo key khác nhau từ cùng secret

    Returns:
        32 bytes key
    """
    material = f"{secret}:{salt}".encode("utf-8")
    return hashlib.sha256(material).digest()


def get_master_key() -> bytes:
    """
    Đọc ADMIN_MASTER_KEY từ env.
    Dùng cho encrypt at rest trong admin DB.
    """
    raw = os.environ.get("ADMIN_MASTER_KEY", "").strip()
    if not raw:
        raise EnvironmentError(
            "[ENCRYPTION] ADMIN_MASTER_KEY is not set in env. "
            "Required for encrypting bot DB URLs."
        )
    return derive_key(raw, salt="master_at_rest")


# ============================================================
# ENCRYPT / DECRYPT
# ============================================================

def encrypt_value(plaintext: str, key: bytes) -> str:
    """
    Encrypt plaintext string → base64-like hex string.
    Format output: nonce_hex:ciphertext_hex

    Args:
        plaintext: string cần encrypt
        key: 32 bytes key

    Returns:
        string dạng "nonce_hex:ciphertext_hex"
    """
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(NONCE_SIZE)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return f"{nonce.hex()}:{ciphertext.hex()}"


def decrypt_value(encrypted: str, key: bytes) -> str:
    """
    Decrypt string đã encrypt bởi encrypt_value().

    Args:
        encrypted: string dạng "nonce_hex:ciphertext_hex"
        key: 32 bytes key

    Returns:
        plaintext string

    Raises:
        ValueError nếu format sai hoặc key sai
    """
    try:
        parts = encrypted.split(":", 1)
        if len(parts) != 2:
            raise ValueError("Invalid encrypted format: expected 'nonce:ciphertext'")

        nonce = bytes.fromhex(parts[0])
        ciphertext = bytes.fromhex(parts[1])

        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode("utf-8")
    except Exception as e:
        raise ValueError(f"Decryption failed: {e}")


# ============================================================
# HIGH-LEVEL HELPERS
# ============================================================

def encrypt_at_rest(plaintext: str) -> str:
    """
    Encrypt cho lưu trữ trong admin DB.
    Dùng ADMIN_MASTER_KEY.
    """
    key = get_master_key()
    return encrypt_value(plaintext, key)


def decrypt_at_rest(encrypted: str) -> str:
    """
    Decrypt giá trị đã lưu trong admin DB.
    Dùng ADMIN_MASTER_KEY.
    """
    key = get_master_key()
    return decrypt_value(encrypted, key)


def encrypt_for_transport(plaintext: str, bot_secret: str) -> str:
    """
    Encrypt cho gửi qua API (admin → bot).
    Dùng key derive từ bot_secret.
    """
    key = derive_key(bot_secret, salt="transport")
    return encrypt_value(plaintext, key)


def decrypt_from_transport(encrypted: str, bot_secret: str) -> str:
    """
    Decrypt giá trị nhận từ admin API.
    Dùng key derive từ bot_secret.
    """
    key = derive_key(bot_secret, salt="transport")
    return decrypt_value(encrypted, key)


def encrypt_for_cache(plaintext: str, bot_secret: str) -> str:
    """
    Encrypt cho lưu bootstrap cache local.
    Dùng key derive từ bot_secret.
    """
    key = derive_key(bot_secret, salt="cache")
    return encrypt_value(plaintext, key)


def decrypt_from_cache(encrypted: str, bot_secret: str) -> str:
    """
    Decrypt bootstrap cache local.
    Dùng key derive từ bot_secret.
    """
    key = derive_key(bot_secret, salt="cache")
    return decrypt_value(encrypted, key)


# ============================================================
# CACHE FILE HELPERS
# ============================================================

def encrypt_cache_file(data: dict, bot_secret: str) -> str:
    """
    Encrypt toàn bộ cache dict → encrypted string.
    """
    plaintext = json.dumps(data, default=str)
    return encrypt_for_cache(plaintext, bot_secret)


def decrypt_cache_file(encrypted: str, bot_secret: str) -> Optional[dict]:
    """
    Decrypt cache string → dict.
    Returns None nếu decrypt fail.
    """
    try:
        plaintext = decrypt_from_cache(encrypted, bot_secret)
        return json.loads(plaintext)
    except Exception as e:
        print(f"[CACHE DECRYPT WARN] Failed: {e}")
        return None