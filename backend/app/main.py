from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import analysis, games, imports, me, sessions, settings
from app.db import engine

app = FastAPI(title="Chess Review Lab", docs_url="/api/docs", openapi_url="/api/openapi.json")

CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "ChessReviewLab"
_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def require_csrf_header(request: Request, call_next):
    """Cross-site requests cannot set a custom header without a CORS preflight (which we never
    grant), so this plus SameSite=Lax cookies blocks CSRF on state-changing endpoints.
    Note: the Swagger UI "Try it out" cannot send this header; use the frontend or curl."""
    if (
        request.method in _MUTATING
        and request.url.path.startswith("/api/")
        and request.headers.get(CSRF_HEADER) != CSRF_VALUE
    ):
        return JSONResponse(
            {"detail": f"Missing '{CSRF_HEADER}: {CSRF_VALUE}' header"}, status_code=403
        )
    return await call_next(request)


@app.get("/api/healthz")
def healthz() -> dict[str, str]:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


app.include_router(sessions.router)
app.include_router(imports.router)
app.include_router(games.router)
app.include_router(analysis.router)
app.include_router(settings.router)
app.include_router(me.router)
