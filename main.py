import json
from datetime import datetime, date
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.routers.analysis import router, templates

app = FastAPI(title="Dota 2 Match Analyzer", version="1.0.0")


def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# Register tojson filter for Jinja2 templates
templates.env.filters["tojson"] = lambda obj: json.dumps(obj, ensure_ascii=False, default=_json_default)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
