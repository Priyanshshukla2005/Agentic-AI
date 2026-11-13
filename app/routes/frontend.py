"""Phase 5: serve the web app and the sample profiles.

GET /              -> app/static/index.html (the mobile web app)
GET /compare.html  -> app/static/compare.html (prompt comparison page)
GET /api/samples   -> sample profiles from data/eval/sample_profiles.json ("Try a sample")
CSS and JS files are served from /static/... (see app.mount in app/main.py).
"""
import json

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.config import BASE_DIR

router = APIRouter(tags=["frontend"])

STATIC_DIR = BASE_DIR / "app" / "static"
SAMPLES_FILE = BASE_DIR / "data" / "eval" / "sample_profiles.json"


@router.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/compare.html", include_in_schema=False)
def compare_page():
    return FileResponse(STATIC_DIR / "compare.html")


@router.get("/api/samples")
def samples():
    """Complete example profiles for quick demos (used by "Try a sample" and the compare page)."""
    profiles = json.loads(SAMPLES_FILE.read_text(encoding="utf-8"))
    return {
        "samples": [
            {"index": i, "label": p["business_idea"], "language": p.get("language", "en"), "profile": p}
            for i, p in enumerate(profiles)
        ]
    }
