"""Flask Blueprint for the slides visualization tool.
Mounted at /slides by ingest_server.py.
"""

import os
import re
import subprocess
import json
import itertools
from collections import Counter
from pathlib import Path
from datetime import datetime
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


@bp.get("/assets/<path:filename>")
def asset_file(filename):
    assets_dir = VIZ_DIR / "assets"
    path = assets_dir / filename
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


@bp.get("/api/frames")
def api_frames():
    frames_dir = Path.home() / ".spaceselflog" / "frames"
    images = []
    if frames_dir.exists():
        for root, _, files in os.walk(frames_dir):
            root_path = Path(root)
            manifest_path = root_path / "manifest.json"
            meta_dict = {}
            batch_ts = 0
            
            if manifest_path.exists():
                try:
                    with open(manifest_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if "created_at" in data:
                            dt = datetime.fromisoformat(data["created_at"].replace('Z', '+00:00'))
                            batch_ts = int(dt.timestamp() * 1000)
                            
                        for m in data.get("frames_meta", []):
                            if "filename" in m and "captured_at" in m:
                                dt = datetime.fromisoformat(m["captured_at"].replace('Z', '+00:00'))
                                meta_dict[m["filename"]] = int(dt.timestamp() * 1000)
                except Exception:
                    pass

            for f in files:
                if f.endswith('.jpg'):
                    rel_base = root_path.relative_to(frames_dir)
                    url = f"/slides/thumbnails-data/{rel_base.as_posix()}/{f}"
                    ts = meta_dict.get(f, batch_ts)
                    if ts > 0:
                        images.append({"url": url, "ts": ts})
                    
    images.sort(key=lambda x: x["ts"])
    return jsonify({"images": images})


@bp.get("/frames-data/<path:filename>")
def serve_frame_data(filename):
    path = Path.home() / ".spaceselflog" / "frames" / filename
    if not path.exists():
        return "not found", 404
    return send_file(path)


@bp.get("/thumbnails-data/<path:filename>")
def serve_thumbnail_data(filename):
    original_path = Path.home() / ".spaceselflog" / "frames" / filename
    if not original_path.exists():
        return "not found", 404
        
    thumb_dir = Path.home() / ".spaceselflog" / "thumbnails"
    thumb_path = thumb_dir / filename
    
    if not thumb_path.exists():
        # Lazy Generation
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Use macOS native image engine to constrain max dimension to 96px
            subprocess.run(
                ["sips", "-Z", "96", str(original_path), "--out", str(thumb_path)], 
                check=True, 
                capture_output=True
            )
        except Exception as e:
            # Fallback to original
            return send_file(original_path)
            
    return send_file(thumb_path)

import glob
from datetime import timedelta

@bp.get("/api/activity-rhythm")
def api_activity_rhythm():
    base_dir = Path.home() / ".openclaw" / "workspace" / "memory" / "physical-daily-narrative"
    if not base_dir.exists():
        return jsonify([])
        
    timeline_files = sorted(glob.glob(str(base_dir / "*-timeline.md")))
    events = []

    for file in timeline_files:
        try:
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                base_date_str = data.get("date")
                if not base_date_str: continue
                
                for seg in data.get("segments", []):
                    start = seg.get("start_time")
                    end = seg.get("end_time")
                    act = seg.get("standard_activity")
                    if not start or not end or not act:
                        continue
                    
                    if "T" in start:
                        fmt = "%Y-%m-%dT%H:%M" if len(start) == 16 else "%Y-%m-%dT%H:%M:%S"
                        start_dt = datetime.strptime(start, fmt)
                    else:
                        start_dt = datetime.strptime(f"{base_date_str} {start}", "%Y-%m-%d %H:%M")
                    
                    if "T" in end:
                        fmt = "%Y-%m-%dT%H:%M" if len(end) == 16 else "%Y-%m-%dT%H:%M:%S"
                        end_dt = datetime.strptime(end, fmt)
                    else:
                        end_dt = datetime.strptime(f"{base_date_str} {end}", "%Y-%m-%d %H:%M")
                        if end_dt < start_dt:
                            end_dt += timedelta(days=1)
                            
                    # CLAMP LOGIC: Cap at 3 hours
                    if (end_dt - start_dt).total_seconds() > 3 * 3600 and act != "Sleep / Untracked":
                        end_dt = start_dt + timedelta(hours=3)
                    
                    events.append({
                        "start": start_dt,
                        "end": end_dt,
                        "activity": act,
                        "summary": seg.get("summary", "")
                    })
        except Exception as e:
            continue

    if not events:
        return jsonify([])

    output_data = []
    min_date = min([e['start'].date() for e in events])
    max_date = max([e['end'].date() for e in events])

    curr = min_date
    while curr <= max_date:
        date_str = curr.strftime("%Y-%m-%d")
        boxes = []
        
        for hr in range(24):
            for m in (0, 15, 30, 45):
                slot_start = datetime(curr.year, curr.month, curr.day, hr, m)
                slot_end = slot_start + timedelta(minutes=15)
                
                slot_act = "Sleep / Untracked"
                slot_summary = ""
                
                for e in events:
                    if max(slot_start, e['start']) < min(slot_end, e['end']):
                        slot_act = e['activity']
                        slot_summary = e['summary']
                        if slot_act != "Sleep / Untracked":
                            break
                            
                boxes.append({
                    "time": f"{hr:02d}:{m:02d}",
                    "activity": slot_act,
                    "summary": slot_summary
                })
        
        output_data.append({
            "date": date_str,
            "boxes": boxes
        })
        curr += timedelta(days=1)

    return jsonify(output_data)


# ─── Object Co-occurrence Network ──────────────────────────────────────────────
CANONICAL_MAP = {
    # Keyboard
    'mechanical keyboard': 'Mechanical Keyboard',
    'backlit keyboard':    'Mechanical Keyboard',
    'external keyboard':   'Keyboard',
    'wireless keyboard':   'Keyboard',
    'keyboard':            'Keyboard',

    # Monitor / Display
    'dual monitor':        'Dual Monitors',
    'multi-monitor':       'Dual Monitors',
    'three-monitor':       'Dual Monitors',
    'curved display':      'Dual Monitors',
    'external monitor':    'Monitor',
    'monitor':             'Monitor',
    'display':             'Monitor',

    # Mouse
    'ergonomic mouse':     'Mouse',
    'wireless mouse':      'Mouse',
    'mouse':               'Mouse',

    # Computers
    'laptop':              'Laptop',
    'macbook':             'Laptop',
    'mac mini':            'Mac Mini',

    # Beverages – Cola / Energy
    'coca-cola zero':      'Coca-Cola Zero',
    'red coca-cola':       'Coca-Cola Zero',
    'no calorías':         'Coca-Cola Zero',
    'red bull':            'Red Bull',
    'red energy drink':    'Red Bull',
    'energy drink':        'Red Bull',

    # Coffee / Tea / Hot drinks
    'starbucks':           'Starbucks',
    'ceramic mug':         'Coffee / Tea',
    'coffee':              'Coffee / Tea',
    'hot drink':           'Coffee / Tea',
    'tea':                 'Coffee / Tea',
    'mug':                 'Coffee / Tea',

    # Yogurt / Yoplait
    'yoplait':             'Yogurt (Yoplait)',
    'yogur':               'Yogurt (Yoplait)',
    'yogon':               'Yogurt (Yoplait)',

    # Other drinks
    'water bottle':        'Water Bottle',
    'sports drink':        'Sports Drink',
    'fanta':               'Fanta',

    # Phone / Tablet
    'smartphone':          'Smartphone',
    'ipad':                'iPad',

    # Peripherals / Tech
    'headphones':          'Headphones',
    'terminal':            'Terminal / Code',

    # Desk accessories
    'sticky note':         'Sticky Notes',
    'yellow sticky':       'Sticky Notes',
    'rubber duck':         'Rubber Duck',
    'figurine':            'Desk Figurines',
    'desk lamp':           'Desk Lamp',
    'wall map':            'Wall Map',
    'papers':              'Papers / Docs',
    'document':            'Papers / Docs',
    'notebook':            'Notebook',
    'whiteboard':          'Whiteboard',
    'books':               'Books',
    'office chair':        'Office Chair',

    # Gaming / Leisure
    'fanatec':             'Racing Simulator',
    'racing wheel':        'Racing Simulator',
    'board game':          'Board Games',
}

def _canonicalize_obj(raw: str):
    """Return canonical label if substring matches, else None."""
    lower = raw.lower()
    for kw, label in CANONICAL_MAP.items():
        if kw in lower:
            return label
    return None


@bp.get("/api/object-cooccurrence")
def api_object_cooccurrence():
    logs_dir = Path.home() / ".openclaw" / "workspace" / "memory" / "physical-logs"
    if not logs_dir.exists():
        return jsonify({"nodes": [], "links": []})

    log_files = sorted(logs_dir.glob("*.md"))
    all_entries = []
    
    for fpath in log_files:
        try:
            content = fpath.read_text(encoding="utf-8")
        except Exception:
            continue

        # Pattern 1: **objects:** ["desc1", "desc2", ...]
        for m in re.finditer(r'\*\*objects:\*\*\s*\[([^\]]+)\]', content):
            raw = m.group(1)
            items = re.findall(r'"([^"]+)"|\'([^\']+)\'', raw)
            objs = [a or b for a, b in items]
            if objs:
                all_entries.append(objs)

        # Pattern 2: **objects:** item1, item2, ...  (no brackets)
        for m in re.finditer(r'\*\*objects:\*\*\s+([^\n|]+)', content):
            raw = m.group(1).strip()
            if '[' not in raw:
                items = [x.strip() for x in raw.split(',') if x.strip()]
                if items:
                    all_entries.append(items)

    # Build canonical per-entry sets
    node_counter  = Counter()
    edge_counter  = Counter()

    for raw_entry in all_entries:
        canon_set = set()
        for obj in raw_entry:
            c = _canonicalize_obj(obj)
            if c:
                canon_set.add(c)
        if len(canon_set) >= 2:
            node_counter.update(canon_set)
            for a, b in itertools.combinations(sorted(canon_set), 2):
                edge_counter[(a, b)] += 1

    if not node_counter:
        return jsonify({"nodes": [], "links": []})

    # Keep top-N nodes by frequency; show only edges between kept nodes
    TOP_NODES = 28
    top_nodes = {n for n, _ in node_counter.most_common(TOP_NODES)}

    # Min edge weight threshold (tune to taste)
    MIN_WEIGHT = 5
    links = []
    for (a, b), w in edge_counter.items():
        if a in top_nodes and b in top_nodes and w >= MIN_WEIGHT:
            links.append({"source": a, "target": b, "value": w})

    max_freq = max(node_counter.values())
    nodes = [
        {"id": n, "freq": node_counter[n], "normFreq": node_counter[n] / max_freq}
        for n in top_nodes
    ]

    return jsonify({"nodes": nodes, "links": links})


# ─── Sankey: Location → Activity ───────────────────────────────────────────────
_SANKEY_LOC_MAP = {
    'home office':    'Home Office',
    'office':         'Home Office',
    'workstation':    'Home Office',
    'bedroom-office': 'Home Office',
    'bedroom':        'Bedroom',
    'kitchen':        'Kitchen',
    'dining':         'Dining Area',
    'living':         'Living Room',
    'bathroom':       'Bathroom',
    'outside':        'Outside',
    'transit':        'In Transit',
    'car':            'In Transit',
}

_SANKEY_ACT_MAP = {
    'working':      'Focused Work',
    'coding':       'Focused Work',
    'debug':        'Focused Work',
    'programming':  'Focused Work',
    'terminal':     'Focused Work',
    'develop':      'Focused Work',
    'typing':       'Focused Work',
    'reading':      'Learning & Review',
    'studying':     'Learning & Review',
    'learning':     'Learning & Review',
    'reviewing':    'Learning & Review',
    'research':     'Learning & Review',
    'browsing':     'Learning & Review',
    'browse':       'Learning & Review',
    'eating':       'Life Maintenance',
    'cooking':      'Life Maintenance',
    'cleaning':     'Life Maintenance',
    'washing':      'Life Maintenance',
    'meal':         'Life Maintenance',
    'sleep':        'Sleep / Untracked',
    'rest':         'Rest & Leisure',
    'gaming':       'Rest & Leisure',
    'watching':     'Rest & Leisure',
    'relaxing':     'Rest & Leisure',
    'walking':      'Movement & Transit',
    'moving':       'Movement & Transit',
}


def _sankey_loc(raw: str):
    low = raw.lower()
    for kw, label in _SANKEY_LOC_MAP.items():
        if kw in low:
            return label
    return 'Other'


def _sankey_act(raw: str):
    low = raw.lower()
    for kw, label in _SANKEY_ACT_MAP.items():
        if kw in low:
            return label
    return None


@bp.get("/api/sankey")
def api_sankey():
    logs_dir = Path.home() / ".openclaw" / "workspace" / "memory" / "physical-logs"
    if not logs_dir.exists():
        return jsonify({"nodes": [], "links": []})

    flow_counter: Counter = Counter()

    for fpath in sorted(logs_dir.glob("*.md")):
        try:
            content = fpath.read_text(encoding="utf-8")
        except Exception:
            continue
        # Parse inline entry rows: **activity:** ... | **location:** ...
        for m in re.finditer(
            r'\*\*activity:\*\*\s*([^|]+).*?\*\*location:\*\*\s*([^|\n]+)',
            content
        ):
            act_raw = m.group(1).strip()
            loc_raw = m.group(2).strip()
            loc = _sankey_loc(loc_raw)
            act = _sankey_act(act_raw)
            if act:
                flow_counter[(loc, act)] += 1

    if not flow_counter:
        return jsonify({"nodes": [], "links": []})

    # Build nodes & links
    locations  = sorted({l for l, _ in flow_counter})
    activities = sorted({a for _, a in flow_counter})

    # Filter out tiny flows (< 3 entries) to keep the chart clean
    MIN_FLOW = 3
    links = []
    for (loc, act), val in flow_counter.items():
        if val >= MIN_FLOW:
            links.append({"source": loc, "target": act, "value": val})

    # Keep only nodes that appear in at least one link
    used_locs = {l["source"] for l in links}
    used_acts = {l["target"] for l in links}

    nodes = (
        [{"id": n, "type": "location"}  for n in sorted(used_locs)] +
        [{"id": n, "type": "activity"}  for n in sorted(used_acts)]
    )

    return jsonify({"nodes": nodes, "links": links})
