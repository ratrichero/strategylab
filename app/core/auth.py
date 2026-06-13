"""
API Key Authentication & Rate Limiting
"""
import os, time
from typing import Optional, Dict, Tuple
from collections import defaultdict, deque
from fastapi import Request, HTTPException, Security
from fastapi.security import APIKeyHeader

RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "200"))
RATE_LIMIT_WINDOW   = int(os.getenv("RATE_LIMIT_WINDOW",   "60"))

PUBLIC_PATHS = {"/", "/health", "/docs", "/redoc", "/openapi.json", "/favicon.ico"}
PUBLIC_PREFIXES = ("/docs", "/redoc", "/static", "/dashboard", "/assets")

async def auth_middleware(request: Request, call_next):
    # DÒNG NÀY PHẢI LÀ DÒNG ĐẦU TIÊN trong function
    if request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path

    if path in PUBLIC_PATHS:
        return await call_next(request)
    # ... rest


class ApiKeyRegistry:
    def __init__(self):
        self._keys: Dict[str, str] = {}
        self._loaded_at: float = 0
        self._reload()

    
    def _reload(self):
        keys = {}
        raw = os.getenv("API_KEYS", "").strip()
        if raw:
            for pair in raw.split(","):
                pair = pair.strip()
                if ":" in pair:
                    name, key = pair.split(":", 1)
                    keys[key.strip()] = name.strip()
        single = os.getenv("API_KEY", "").strip()
        if single:
            keys[single] = "default"
        self._keys = keys
        self._loaded_at = time.time()
        if keys:
            print(f"🔑 API Keys loaded: {list(keys.values())}")
        else:
            print("⚠️  No API keys — open access mode")

    def validate(self, key: str) -> Optional[str]:
        if time.time() - self._loaded_at > 300:
            self._reload()
        return self._keys.get(key)

    @property
    def is_open(self) -> bool:
        return len(self._keys) == 0


class SlidingWindowRateLimiter:
    def __init__(self, max_requests=RATE_LIMIT_REQUESTS, window=RATE_LIMIT_WINDOW):
        self.max_requests = max_requests
        self.window = window
        self._store: Dict[str, deque] = defaultdict(deque)

    def is_allowed(self, client_id: str) -> Tuple[bool, int]:
        now = time.time()
        bucket = self._store[client_id]
        while bucket and bucket[0] < now - self.window:
            bucket.popleft()
        remaining = self.max_requests - len(bucket)
        if len(bucket) >= self.max_requests:
            return False, 0
        bucket.append(now)
        return True, remaining - 1


_registry     = ApiKeyRegistry()
_rate_limiter = SlidingWindowRateLimiter()
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    request: Request,
    api_key: Optional[str] = Security(_api_key_header)
) -> str:
    if _registry.is_open:
        return "dev"
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key",
                            headers={"WWW-Authenticate": "ApiKey"})
    caller = _registry.validate(api_key)
    if not caller:
        raise HTTPException(status_code=401, detail="Invalid API key",
                            headers={"WWW-Authenticate": "ApiKey"})
    allowed, remaining = _rate_limiter.is_allowed(caller)
    if not allowed:
        raise HTTPException(status_code=429,
            detail=f"Rate limit exceeded: {RATE_LIMIT_REQUESTS} req/{RATE_LIMIT_WINDOW}s")
    return caller


async def optional_api_key(
    request: Request,
    api_key: Optional[str] = Security(_api_key_header)
) -> Optional[str]:
    if _registry.is_open:
        return "dev"
    if not api_key:
        return None
    return _registry.validate(api_key)


async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC_PATHS:
        return await call_next(request)
    if any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return await call_next(request)
    if not path.startswith("/api/"):
        return await call_next(request)
    if _registry.is_open:
        return await call_next(request)
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=401,
            content={"detail": "Missing API key"})
    caller = _registry.validate(api_key)
    if not caller:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=401,
            content={"detail": "Invalid API key"})
    allowed, remaining = _rate_limiter.is_allowed(caller)
    if not allowed:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=429,
            content={"detail": "Rate limit exceeded"})
    request.state.caller = caller
    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(RATE_LIMIT_REQUESTS)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    return response
