"""
Middleware for FastAPI application.
Contains auth middleware and global error handler.
"""

import os
import traceback
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse

from app.core.app_role import is_admin
from app.auth.middleware import is_public_path, require_auth_from_cookie


_api_docs_exposed = (
    is_admin()
    and os.getenv("EXPOSE_API_DOCS", "false").strip().lower() == "true"
)


async def auth_middleware(request: Request, call_next):
    """
    Global auth middleware.
    Checks auth from cookie for all requests except public paths.
    """
    path = request.url.path

    if not _api_docs_exposed and (
        path in {"/docs", "/redoc", "/openapi.json"}
        or path.startswith("/docs/")
        or path.startswith("/redoc/")
    ):
        return JSONResponse(status_code=404, content={"detail": "Not found"})

    # Whitelist: không cần auth
    if is_public_path(path):
        return await call_next(request)

    # Check auth từ cookie
    try:
        require_auth_from_cookie(request)
    except HTTPException as e:
        # Nếu là API call → trả JSON 401
        if path.startswith("/api/") or path.startswith("/admin/") or path.startswith("/scan"):
            return JSONResponse(
                status_code=e.status_code,
                content={"detail": e.detail}
            )
        # Nếu là page navigation → redirect login
        return RedirectResponse(url="/login", status_code=302)

    return await call_next(request)


async def global_error(request: Request, exc: Exception):
    """
    Global error handler for unhandled exceptions.
    """
    e = f"{type(exc).__name__}: {exc}"
    print(f"\n{'='*60}\n🚨 {e}\n{traceback.format_exc()}{'='*60}")
    return JSONResponse(status_code=500, content={"error": e})


def setup_middleware(app: FastAPI):
    """
    Setup all middleware for the FastAPI app.
    """
    app.middleware("http")(auth_middleware)
    app.exception_handler(Exception)(global_error)
