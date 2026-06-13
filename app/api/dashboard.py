from fastapi import APIRouter
from fastapi.responses import HTMLResponse
router = APIRouter()

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return """
    <html><body>
    <h1>Quant Research Lab v2.0</h1>
    <p>Dashboard frontend served from /dist</p>
    <p><a href='/docs'>API Docs</a></p>
    </body></html>
    """
