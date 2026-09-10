from fastapi import FastAPI

from hymail_api.core.config import settings

app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    docs_url="/docs",
    redoc_url=None,
)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "hymail-api",
        "version": settings.version,
    }