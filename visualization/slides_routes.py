"""Flask Blueprint for the slides visualization tool.
Mounted at /slides by ingest_server.py.
"""

import json
from pathlib import Path
from flask import Blueprint, send_file, request, jsonify

VIZ_DIR     = Path(__file__).parent
SLIDES_FILE = VIZ_DIR / "slides_data.json"

bp = Blueprint("slides", __name__)


@bp.get("/")
def slides_page():
    return send_file(VIZ_DIR / "slides.html")


@bp.get("/assets/<path:filename>")
def slides_assets(filename):
    path = VIZ_DIR / "assets" / filename
    if not path.exists():
        return "not found", 404
    return send_file(path)


@bp.get("/api/slides")
def slides_get():
    if SLIDES_FILE.exists():
        return SLIDES_FILE.read_text(), 200, {"Content-Type": "application/json"}
    return jsonify({"slides": [{"section": "", "subtitle": ""}]})


@bp.post("/api/slides")
def slides_post():
    data = request.get_json(force=True, silent=True) or {}
    SLIDES_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return jsonify({"ok": True})
