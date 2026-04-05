"""Flask Blueprint for the slides visualization tool.
Mounted at /slides by ingest_server.py.
"""

import json
from pathlib import Path
from flask import Blueprint, send_file, request, jsonify

VIZ_DIR     = Path(__file__).parent
SLIDES_DIR  = VIZ_DIR / "slides"
SLIDES_FILE = VIZ_DIR / "slides_data.json"

SLIDE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
  width: 100vw;
  height: 100vh;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #111;
}
</style>
</head>
<body>

</body>
</html>
"""

bp = Blueprint("slides", __name__)


@bp.get("/")
def slides_page():
    return send_file(VIZ_DIR / "slides.html")


@bp.get("/slide-files/<path:filename>")
def slide_file(filename):
    path = SLIDES_DIR / filename
    if not path.exists():
        return "not found", 404
    return send_file(path)


@bp.get("/api/slides")
def slides_get():
    if SLIDES_FILE.exists():
        return SLIDES_FILE.read_text(), 200, {"Content-Type": "application/json"}
    return jsonify({"slides": [{"section": "", "subtitle": "", "src": "/slides/slide-files/01_cover.html"}]})


@bp.post("/api/slides")
def slides_post():
    data = request.get_json(force=True, silent=True) or {}
    SLIDES_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return jsonify({"ok": True})


@bp.post("/api/slides/new")
def slides_new():
    SLIDES_DIR.mkdir(exist_ok=True)
    # find next available slide_NNN.html
    n = len(list(SLIDES_DIR.glob("slide_*.html"))) + 1
    filename = f"slide_{n:03d}.html"
    while (SLIDES_DIR / filename).exists():
        n += 1
        filename = f"slide_{n:03d}.html"
    (SLIDES_DIR / filename).write_text(SLIDE_TEMPLATE)
    return jsonify({"ok": True, "src": f"/slides/slide-files/{filename}"})
