import json
import os
from datetime import datetime, date

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers.analysis import router, templates
from app.routers.llm import router as llm_router

app = FastAPI(title="Dota 2 Match Analyzer", version="2.0.0")


def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# Register tojson filter for Jinja2 templates
templates.env.filters["tojson"] = lambda obj: json.dumps(
    obj, ensure_ascii=False, default=_json_default
)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(router)
app.include_router(llm_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=os.getenv("APP_RELOAD", "0") == "1",
    )
