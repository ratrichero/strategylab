"""
Bot Runtime module.
Chỉ active khi APP_ROLE=BOT.

Chức năng:
  - Bootstrap: lấy DB URL từ admin hoặc cache
  - License client: sync với admin
  - Runtime gate: check quyền hoạt động
  - Heartbeat: định kỳ report về admin
"""