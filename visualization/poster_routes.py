"""Flask Blueprint for the poster visualization tool.
Mounted at /poster by ingest_server.py.
"""

from pathlib import Path
from flask import Blueprint, send_file

VIZ_DIR = Path(__file__).parent

bp = Blueprint("poster", __name__)

@bp.get("/")
@bp.get("/1")
def poster_1_page():
    return send_file(VIZ_DIR / "poster_1.html")

@bp.get("/2")
def poster_2_page():
    return send_file(VIZ_DIR / "poster_2.html")
