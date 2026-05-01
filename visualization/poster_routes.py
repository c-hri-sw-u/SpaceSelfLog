"""Flask Blueprint for the poster visualization tool.
Mounted at /poster by ingest_server.py.
"""

from pathlib import Path
from flask import Blueprint, send_file

VIZ_DIR = Path(__file__).parent

bp = Blueprint("poster", __name__)

@bp.get("/")
def poster_page():
    return send_file(VIZ_DIR / "poster.html")
