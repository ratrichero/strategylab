from app.services.binance_service import get_valid_symbols
try:
    VALID_SYMBOLS = set(get_valid_symbols())
except Exception:
    VALID_SYMBOLS = set()
