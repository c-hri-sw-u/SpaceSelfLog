"""
SpaceSelfLog preview video generator.
Layout (top→bottom): timeline · timestamp · metadata · thumbnails · description
"""

import os
import re
import io
import textwrap
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from PIL import Image, ImageFilter, ImageDraw, ImageFont
import numpy as np

# cairosvg needs the homebrew cairo dylib on macOS
os.environ.setdefault("DYLD_LIBRARY_PATH", "/opt/homebrew/lib")
import cairosvg  # noqa: E402  (kept for fallback)
from resvg_py import svg_to_bytes as _resvg_render

PIT_TZ = ZoneInfo("America/New_York")

# ── paths ────────────────────────────────────────────────────────────────────
THUMBNAILS_DIR = Path("/Users/mia/.spaceselflog/thumbnails")
LOGS_DIR       = Path("/Users/mia/.openclaw/workspace/memory/physical-logs")
OUT_DIR        = Path(__file__).parent / "preview_frames"
OUT_VIDEO      = Path(__file__).parent / "preview.mp4"

# ── canvas ───────────────────────────────────────────────────────────────────
W, H        = 1920, 1080
PAD         = 80          # left/right margin
IPAD        = 30          # inner vertical gap between sections
TL_PAD      = 30          # padding above timeline
TL_H        = 56          # timeline strip height (not counting TL_PAD)
IMG_H       = 260         # thumbnail row height
BLUR_R      = 2
CONTENT_W   = W - PAD * 2         # full content width
META_PLAN_W = 308                  # floor plan width in metadata row
META_PLAN_MIN_H = 180              # minimum floor plan height
META_GAP    = 48                   # gap between text and floor plan
META_PLAN_X = W - PAD - META_PLAN_W  # x start of floor plan
META_TEXT_W = META_PLAN_X - PAD - META_GAP  # metadata text column width

# ── colors ───────────────────────────────────────────────────────────────────
BG           = (10, 10, 14)
TICK_COL     = (50, 50, 62)
TICK_LABEL   = (90, 90, 105)
MARKER_COL   = (220, 75, 55)
DATE_COL     = (90, 90, 108)
TS_COL       = (70, 70, 85)
KEY_COL      = (75, 75, 95)
ACTIVITY_COL = (220, 200, 125)
LOCATION_COL = (125, 188, 218)
OBJECTS_COL  = (148, 208, 148)
SOCIAL_COL   = (195, 150, 208)
NOTABLE_COL  = (208, 165, 125)
DESC_COL     = (175, 175, 188)
DIV_COL      = (35, 35, 48)


# ── floor plan ───────────────────────────────────────────────────────────────
# SVG coordinate space: 605 × 434
PLAN_SVG_W, PLAN_SVG_H = 605, 434

STRUCT_PATH = (
    "M420 7H365V60H358V7H229V60H222V7H7V358.5H64V427H222V197.5H236V204.5H229V236.5H325.5V204"
    "H318.5V198.5L317.963 199.344L301.5 188.867L285.037 199.344L283.963 197.656L300.463 187.156"
    "L301.5 188.785L302.537 187.156L318.5 197.314V197H332.5V243.5H300V247H293.5V249.415H261.411"
    "C261.632 261.487 266.827 268.883 273.258 273.278C279.859 277.79 287.799 279.164 293.092 279.098"
    "L293.097 279.5H300V339.5H303.5V346.5H229V427H350V346.5H346.5V339.5H350V330.5H391V309H398V342"
    "H391V337.5H357V427H391V423H398V427H598V265.998L398 265.517V269H391V265.5H390.991L391.009 258.5"
    "L413 258.553V255H420V258.569L598 258.998V59H452V63H445V59H420V148.5H445V144H452V155.5H420V213.502"
    "C426.74 213.419 436.845 215.161 445.282 220.928C453.572 226.594 460.214 236.125 460.49 251.503"
    "H460.5V254.503H419.5V251.503H459.489C459.214 236.462 452.74 227.236 444.718 221.753"
    "C436.491 216.13 426.6 214.421 420.006 214.503L420 214H413V48H420V48.4775L420.006 48"
    "C426.6 48.0824 436.491 46.3729 444.718 40.75C452.74 35.2669 459.214 26.0405 459.489 11"
    "H419.5V8H460.5V11H460.49C460.214 26.3783 453.572 35.909 445.282 41.5752"
    "C436.845 47.3421 426.74 49.0831 420 49V52H605V434H57V365.5H0V0H420V7Z"
)

# Interior detail subpaths — rendered stroke-only to avoid filled blobs on dark bg.
DETAIL_PATH = (
    "M346.003 387H343.003V386.989C327.625 386.713 318.094 380.072 312.428 371.782"
    "C306.659 363.342 304.919 353.234 305.003 346.494L306.003 346.506C305.921 353.1 307.63 362.991"
    "313.253 371.218C318.736 379.24 327.962 385.714 343.003 385.989V346H346.003V387Z"
    "M229 339.5H293V280.097C287.562 280.146 279.464 278.732 272.693 274.104"
    "C265.851 269.428 260.402 261.493 260.402 248.609H260.5V247H293V243.5H229V339.5Z"
    "M271.537 197.656L270.463 199.344L254 188.867L237.537 199.344L236.463 197.656L252.963 187.156"
    "L254 188.785L255.037 187.156L271.537 197.656Z"
    "M461.844 124.963L460.214 126L461.844 127.037L451.344 143.537L449.656 142.463L460.132 126"
    "L449.656 109.537L451.344 108.463L461.844 124.963Z"
    "M365 143H222V102H229V136H358V101.5H365V143Z"
    "M461.844 79.9629L460.214 81L461.844 82.0371L451.344 98.5371L449.656 97.4629L460.132 81"
    "L449.656 64.5371L451.344 63.4629L461.844 79.9629Z"
)

FURN_PATH = (
    "M269.5 427H229.5V347H269.5V427ZM279.989 387.984C282.554 380.99 292.446 380.99 295.011 387.984"
    "L296.188 391.193C297.717 395.365 298.5 399.774 298.5 404.217C298.5 406.306 296.806 408 294.717 408"
    "H293.5V410C297.918 410 301.5 413.582 301.5 418V425C301.5 426.105 300.605 427 299.5 427H275.5"
    "C274.395 427 273.5 426.105 273.5 425V418C273.5 413.582 277.082 410 281.5 410V408H280.283"
    "C278.194 408 276.5 406.306 276.5 404.217C276.5 399.774 277.283 395.365 278.812 391.193"
    "L279.989 387.984ZM350.5 427H305.5V398H350.5V427ZM100.5 360C117.069 360 130.5 373.431 130.5 390"
    "V396C130.5 412.569 117.069 426 100.5 426H94.5C77.9315 426 64.5 412.569 64.5 396V390"
    "C64.5 373.431 77.9315 360 94.5 360H100.5ZM203.5 426H131.5V408H203.5V426ZM33.5 343H15.5V325H33.5V343Z"
    "M203.5 335H131.5V299H203.5V335ZM33.5 324H15.5V292H33.5V324ZM121.5 281H113.5V249H121.5V281Z"
    "M166.5 281H122.5V249H166.5V281ZM211.5 281H167.5V249H211.5V281ZM220.5 281H212.5V249H220.5V281Z"
    "M50.5 255H8.5V155H50.5V255ZM166.5 248H113.5V236H166.5V248ZM220.5 248H167.5V236H220.5V248Z"
    "M596.5 237H564.5V165H596.5V237ZM181.5 235H107.5V201H181.5V235ZM220.5 235H197.5V197H220.5V235Z"
    "M70.5 220H57.5V217H70.5V220ZM69.5 216H51.5V198H69.5V216ZM76.5 216H70.5V198H76.5V216Z"
    "M554.5 214H541.5V211H554.5V214ZM541.5 210H535.5V192H541.5V210ZM560.5 210H542.5V192H560.5V210Z"
    "M70.5 197H57.5V194H70.5V197ZM554.5 191H541.5V188H554.5V191ZM118.5 175H100.5V169H118.5V175Z"
    "M118.5 168H100.5V150H118.5V168ZM596.5 164H524.5V132H596.5V164ZM130.5 146H88.5V74H130.5V146Z"
    "M319.5 104H357.5V136H229.5V104H279.5V101H319.5V104ZM65.5 135H59.5V117H65.5V135Z"
    "M84.5 135H66.5V117H84.5V135ZM152.5 135H134.5V117H152.5V135ZM159.5 135H153.5V117H159.5V135Z"
    "M596.5 131H494.5V60H596.5V131ZM24.5 58H17.5V106H24.5V108H8.5V106H15.5V58H8.5V56H24.5V58Z"
    "M65.5 103H59.5V85H65.5V103ZM84.5 103H66.5V85H84.5V103ZM152.5 103H134.5V85H152.5V103Z"
    "M159.5 103H153.5V85H159.5V103ZM118.5 70H100.5V52H118.5V70ZM220.5 56H200.5V8H220.5V56Z"
    "M357.5 40H269.5V56H229.5V8H357.5V40ZM118.5 51H100.5V45H118.5V51ZM379.5 48H365.5V8H379.5V48Z"
    "M199.5 32H147.5V8H199.5V32ZM146.5 24H27.5V8H146.5V24Z"
)

# Room definitions: label, SVG center, highlight shape (in SVG coords), keyword hints
ROOMS = {
    "home_office":  {"label": "Home Office", "cx": 546, "cy": 195,
                     "shape": {"type": "rect", "x": 494.5, "y": 132, "w": 102, "h": 126},
                     "keys": ["home office", "office", "desk", "computer", "monitor", "keyboard"]},
    "kitchen":      {"label": "Kitchen",     "cx": 294, "cy": 72,
                     "shape": {"type": "rect", "x": 229.5, "y": 7, "w": 128, "h": 129},
                     "keys": ["kitchen", "sink", "counter", "dishwasher", "refrigerator", "stove", "cooking"]},
    "bedroom":      {"label": "Bedroom",     "cx": 457, "cy": 140,
                     "shape": {"type": "path", "d": "M420.5 60H596.5V131H494.5V258H420.5V60Z"},
                     "keys": ["bedroom", "bed", "sleep", "sleeping"]},
    "living_room":  {"label": "Living Room", "cx": 152, "cy": 305,
                     "shape": {"type": "path", "d": "M80.5 175.5H221.5V426H64.5V360.5H80.5V342V175.5Z"},
                     "keys": ["living", "couch", "sofa", "tv", "television", "exercise bike", "punching bag"]},
    "hallway":      {"label": "Hallway",     "cx": 312, "cy": 235,
                     "shape": {"type": "path", "d": "M365.5 101H412.5V258H391V330H350V339.5H229V197.5H221.5V143.5H365.5V101Z"},
                     "keys": ["hallway", "hall", "corridor", "doorway"]},
    "dining_area":  {"label": "Dining",      "cx": 115, "cy": 80,
                     "shape": {"type": "path", "d": "M7.5 7L221.5 7V175H7.5V7Z"},
                     "keys": ["dining", "dining area", "dining room", "table", "chairs"]},
    "bathroom":     {"label": "Bathroom",    "cx": 290, "cy": 387,
                     "shape": {"type": "rect", "x": 229.5, "y": 347, "w": 121, "h": 79},
                     "keys": ["bathroom", "restroom", "toilet"]},
    "workout_area": {"label": "Workout",     "cx": 44,  "cy": 309,
                     "shape": {"type": "rect", "x": 7.5, "y": 258, "w": 73, "h": 102},
                     "keys": ["workout", "exercise", "gym", "weights"]},
    "workspace":    {"label": "Workspace",   "cx": 44,  "cy": 202,
                     "shape": {"type": "rect", "x": 7.5, "y": 146, "w": 73, "h": 112},
                     "keys": ["workspace", "work area"]},
    "entrance":     {"label": "Entrance",    "cx": 389, "cy": 55,
                     "shape": {"type": "rect", "x": 365.5, "y": 8, "w": 47, "h": 93},
                     "keys": ["entrance", "entryway", "door", "entry"]},
}

_PLAN_BASE_CACHE: Image.Image | None = None

def _shape_svg(shape: dict, fill: str, stroke: str, sw: int) -> str:
    if shape["type"] == "rect":
        return (f'<rect x="{shape["x"]}" y="{shape["y"]}" width="{shape["w"]}" height="{shape["h"]}"'
                f' fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
    else:
        return f'<path d="{shape["d"]}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'


_STRUCT_SVG_PATH = Path(__file__).parent / "assets/img/apt_plan/structure_1.svg"

def _build_plan_svg(scale: float = 1.0) -> str:
    """Build plan SVG using the source file (correct fill-rule=evenodd) + furniture + labels."""
    pw = int(PLAN_SVG_W * scale)
    ph = int(PLAN_SVG_H * scale)
    # strip the outer <svg> tag from the source file and re-wrap with white bg + scale
    struct_inner = ""
    if _STRUCT_SVG_PATH.exists():
        raw = _STRUCT_SVG_PATH.read_text()
        # extract everything between first > and last </svg>
        start = raw.index(">") + 1
        end = raw.rindex("</svg>")
        struct_inner = raw[start:end]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {PLAN_SVG_W} {PLAN_SVG_H}" width="{pw}" height="{ph}">',
        f'<rect width="{PLAN_SVG_W}" height="{PLAN_SVG_H}" fill="white"/>',
        struct_inner,
        f'<path d="{FURN_PATH}" fill="#eeeeee"/>',
    ]
    # room labels in gray (remapped to light-on-dark by render_floorplan)
    for key, rm in ROOMS.items():
        parts.append(
            f'<text x="{rm["cx"]}" y="{rm["cy"] + 4}" text-anchor="middle"'
            f' font-family="Helvetica,Arial,sans-serif" font-size="11"'
            f' font-weight="400" fill="#999999">{rm["label"]}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def match_room(location: str) -> str | None:
    """Fuzzy-match a location string to a room key.
    Prefers the keyword that appears earliest; ties broken by longest keyword."""
    loc = location.lower()
    best_key = None
    best_pos, best_len = len(loc) + 1, 0
    for key, rm in ROOMS.items():
        for kw in rm["keys"]:
            pos = loc.find(kw)
            if pos != -1:
                if pos < best_pos or (pos == best_pos and len(kw) > best_len):
                    best_key, best_pos, best_len = key, pos, len(kw)
    return best_key


def _path_to_polygon(d: str, scale: float, ox: int, oy: int) -> list[tuple[int, int]]:
    """Convert simple SVG path (M/H/V/L/Z only) to scaled PIL polygon points."""
    import re
    tokens = re.findall(r'[MHLVZ]|[-+]?[0-9]*\.?[0-9]+', d)
    pts: list[tuple[float, float]] = []
    x = y = 0.0
    i = 0
    while i < len(tokens):
        cmd = tokens[i]; i += 1
        if cmd == 'M':
            x, y = float(tokens[i]), float(tokens[i + 1]); i += 2
            pts.append((x, y))
        elif cmd == 'L':
            x, y = float(tokens[i]), float(tokens[i + 1]); i += 2
            pts.append((x, y))
        elif cmd == 'H':
            x = float(tokens[i]); i += 1
            pts.append((x, y))
        elif cmd == 'V':
            y = float(tokens[i]); i += 1
            pts.append((x, y))
        # Z — close path, no new point needed
    return [(int(px * scale) + ox, int(py * scale) + oy) for px, py in pts]


def render_floorplan(location: str, panel_w: int, panel_h: int) -> Image.Image:
    """Render the floor plan PNG for the given location string."""
    room_key = match_room(location)
    scale = panel_w / PLAN_SVG_W

    # 1. Render exactly like the HTML reference (white bg, gray walls) using resvg
    svg_str = _build_plan_svg(scale=scale)
    png_bytes = _resvg_render(svg_str)
    src = np.array(Image.open(io.BytesIO(png_bytes)).convert("RGB"), dtype=np.float32)

    # 2. Color remap: white(255)→BG, gray walls(~217)→near-white(~210).
    #    All gray values (incl. the hallway blob) remap consistently → no floating blobs.
    #    Formula: out = clip(5.5 * (255 - src), 0, 255)
    dark = np.clip(5.5 * (255.0 - src), 0, 255).astype(np.uint8)
    plan_dark = Image.fromarray(dark)

    # 3. Composite onto BG
    actual_h = max(panel_h, plan_dark.height)
    bg = Image.new("RGB", (panel_w, actual_h), BG)
    y_offset = (actual_h - plan_dark.height) // 2
    bg.paste(plan_dark, (0, y_offset))

    # 4. Draw room highlight on top using PIL (bypasses SVG renderer entirely)
    if room_key and room_key in ROOMS:
        rm = ROOMS[room_key]
        draw = ImageDraw.Draw(bg, "RGBA")
        sh = rm["shape"]
        sx, sy = 0, y_offset
        if sh["type"] == "rect":
            x0 = int(sh["x"] * scale) + sx
            y0 = int(sh["y"] * scale) + sy
            x1 = x0 + int(sh["w"] * scale)
            y1 = y0 + int(sh["h"] * scale)
            draw.rectangle([x0, y0, x1, y1], fill=(220, 80, 60, 80), outline=(220, 80, 60, 200), width=2)
        elif sh["type"] == "path":
            pts = _path_to_polygon(sh["d"], scale, sx, sy)
            if pts:
                draw.polygon(pts, fill=(220, 80, 60, 80), outline=(220, 80, 60, 200))
        # draw label for active room
        font_size = max(8, int(11 * scale))
        try:
            fnt = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
        except Exception:
            fnt = ImageFont.load_default(size=font_size)
        lx = int(rm["cx"] * scale) + sx
        ly = int((rm["cy"] + 4) * scale) + sy
        draw.text((lx, ly), rm["label"], font=fnt, fill=(220, 100, 80, 255), anchor="mm")

    return bg


# ── fonts ────────────────────────────────────────────────────────────────────
def load_fonts():
    mono_path = next(
        (p for p in [
            "/System/Library/Fonts/Supplemental/Courier New.ttf",
            "/System/Library/Fonts/Menlo.ttc",
            "/System/Library/Fonts/Monaco.ttf",
        ] if Path(p).exists()), None
    )
    sans_path = next(
        (p for p in [
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
        ] if Path(p).exists()), None
    )

    def f(path, size):
        try:
            return ImageFont.truetype(path, size) if path else ImageFont.load_default(size=size)
        except Exception:
            return ImageFont.load_default(size=size)

    # three sizes, two faces
    return {
        "sm":  f(mono_path, 16),   # timeline ticks, session id
        "md":  f(sans_path, 20),   # metadata values, description
        "lg":  f(sans_path, 26),   # date + timestamp
    }


# ── log parser ───────────────────────────────────────────────────────────────
ENTRY_RE = re.compile(
    r"^## (\d{2}:\d{2})\s+`([^`]+)`\s*\n"
    r"<!-- session=(\S+)\s+frames=([^\-\n]+?) -->\s*\n"
    r"\n"
    r"\*\*activity:\*\* (.+?) \|  \*\*location:\*\* (.+?) \|  \*\*objects:\*\* (.+?) \|  \*\*social_context:\*\* (.+?) \|  \*\*notable_events:\*\* (.+?)\s*\n"
    r"\n"
    r"((?:.|\n)+?)(?=\n## |\Z)",
    re.MULTILINE,
)

def parse_log(log_path: Path) -> list[dict]:
    entries = []
    for m in ENTRY_RE.finditer(log_path.read_text()):
        entries.append({
            "time_display": m.group(1),
            "timestamp":    m.group(2),
            "session":      m.group(3),
            "activity":     m.group(5).strip(),
            "location":     m.group(6).strip(),
            "objects":      m.group(7).strip(),
            "social":       m.group(8).strip(),
            "notable":      m.group(9).strip(),
            "description":  m.group(10).strip(),
        })
    return entries


# ── thumbnails ───────────────────────────────────────────────────────────────
def load_thumbnails(session: str, timestamp: str) -> list[Image.Image]:
    folder = THUMBNAILS_DIR / session / timestamp
    if not folder.exists():
        return []
    imgs = []
    for p in sorted(folder.iterdir()):
        if p.suffix.lower() in (".jpg", ".jpeg", ".png"):
            try:
                img = Image.open(p).convert("RGB")
                if img.height > img.width:
                    img = img.rotate(-90, expand=True)
                imgs.append(img)
            except Exception:
                pass
    return imgs


def compose_thumb_row(imgs: list[Image.Image], row_h: int, max_w: int) -> Image.Image:
    """Blur and arrange thumbnails in a centered horizontal strip.
    If images don't fit with gaps they overlap so all are always visible."""
    strip = Image.new("RGB", (max_w, row_h), BG)
    if not imgs:
        return strip

    gap = 12
    blurred = [img.filter(ImageFilter.GaussianBlur(radius=BLUR_R)) for img in imgs]
    resized = []
    for b in blurred:
        ratio = row_h / b.height
        nw = max(1, int(b.width * ratio))
        r = b.resize((nw, row_h), Image.LANCZOS).convert("RGBA")
        alpha = Image.new("L", r.size, int(255 * 0.85))
        r.putalpha(alpha)
        resized.append(r)

    n = len(resized)
    natural_w = sum(r.width for r in resized) + gap * (n - 1)

    if natural_w <= max_w:
        # fits — center with gaps
        x_start = (max_w - natural_w) // 2
        x = x_start
        for r in resized:
            strip.paste(r, (x, 0), r)
            x += r.width + gap
    else:
        # overlap: spread evenly so all images are visible, last one flush right
        total_img_w = sum(r.width for r in resized)
        # step = how far each image advances
        if n > 1:
            step = (max_w - resized[-1].width) // (n - 1)
        else:
            step = 0
        x_start = (max_w - (step * (n - 1) + resized[-1].width)) // 2
        x = x_start
        for r in resized:
            strip.paste(r, (x, 0), r)
            x += step

    return strip


# ── timeline ─────────────────────────────────────────────────────────────────
def _minutes(t: str) -> int:
    try:
        h, m = map(int, t.split(":"))
        return h * 60 + m
    except Exception:
        return 0

def draw_timeline(draw: ImageDraw.ImageDraw, fonts,
                  date_str: str, time_str: str,
                  all_times: list[str], current_idx: int):
    # same background — no fill rectangle needed (BG is already set)
    bar_x0 = PAD + 200
    bar_x1 = W - PAD
    bar_y  = TL_PAD + TL_H // 2
    bar_w  = bar_x1 - bar_x0

    # axis
    draw.line([bar_x0, bar_y, bar_x1, bar_y], fill=TICK_COL, width=2)

    # hour ticks
    for h in range(25):
        x = bar_x0 + int(h / 24 * bar_w)
        th = 8 if h % 6 == 0 else 4
        draw.line([x, bar_y - th, x, bar_y + th], fill=TICK_COL, width=1)
        if h % 6 == 0 and h < 24:
            draw.text((x - 16, bar_y + 11), f"{h:02d}:00",
                      font=fonts["sm"], fill=TICK_LABEL)

    # all-entry dots
    for i, t in enumerate(all_times):
        if i == current_idx:
            continue
        x = bar_x0 + int(_minutes(t) / 1440 * bar_w)
        c = (72, 72, 88) if i < current_idx else (38, 38, 50)
        draw.ellipse([x-3, bar_y-3, x+3, bar_y+3], fill=c)

    # current dot
    cx = bar_x0 + int(_minutes(time_str) / 1440 * bar_w)
    draw.ellipse([cx-7, bar_y-7, cx+7, bar_y+7], fill=MARKER_COL)
    draw.text((cx - 20, bar_y - 26), time_str, font=fonts["sm"], fill=MARKER_COL)

    # date label left of bar
    draw.text((PAD, bar_y - fonts["md"].size // 2), date_str,
              font=fonts["md"], fill=DATE_COL)

    # divider below timeline
    div_y = TL_PAD + TL_H + 14
    draw.line([PAD, div_y, W - PAD, div_y], fill=DIV_COL, width=1)


# ── metadata block ────────────────────────────────────────────────────────────
FIELDS = [
    ("activity", ACTIVITY_COL),
    ("location", LOCATION_COL),
    ("objects",  OBJECTS_COL),
    ("social",   SOCIAL_COL),
    ("notable",  NOTABLE_COL),
]

def draw_metadata(draw: ImageDraw.ImageDraw, fonts, entry: dict, y: int) -> int:
    """Draw metadata lines. Returns y after last line."""
    font = fonts["md"]
    line_h = font.size + 6
    content_w = META_TEXT_W
    avg_cw = font.size * 0.55

    for key, col in FIELDS:
        val = entry[key]
        label = key + "  "
        label_px = int(font.getlength(label))
        draw.text((PAD, y), label, font=font, fill=KEY_COL)

        # value, wrapped to remaining width
        val_w = content_w - label_px
        cpl = max(1, int(val_w / avg_cw))
        lines = textwrap.wrap(val, width=cpl)
        for j, ln in enumerate(lines):
            draw.text((PAD + label_px, y), ln, font=font, fill=col)
            y += line_h
            if j == 0 and len(lines) > 1:
                label_px_cont = int(font.getlength("  " + " " * len(key)))  # indent continuation
        if not lines:
            y += line_h
        y += 2

    return y


# ── full frame ────────────────────────────────────────────────────────────────
def render_frame(entry: dict, all_times: list[str], current_idx: int,
                 date_str: str, fonts) -> Image.Image:
    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    y = 0

    # 1. timeline
    draw_timeline(draw, fonts, date_str, entry["time_display"], all_times, current_idx)
    content_y0 = TL_PAD + TL_H + 14 + IPAD  # top of content area
    y = content_y0

    # 2. timestamp  →  Pittsburgh local time
    raw_ts = entry["timestamp"]  # e.g. 2026-03-22T04-47-21Z
    try:
        dt_utc = datetime.strptime(raw_ts, "%Y-%m-%dT%H-%M-%SZ").replace(tzinfo=timezone.utc)
        dt_pit = dt_utc.astimezone(PIT_TZ)
        tz_abbr = dt_pit.strftime("%Z")  # EDT or EST
        ts_text = dt_pit.strftime("%H:%M:%S") + f"  {tz_abbr}"
    except Exception:
        ts_text = raw_ts
    draw.text((PAD, y), ts_text, font=fonts["md"], fill=TS_COL)
    y += fonts["md"].size + IPAD

    # 4. metadata (left column) + floor plan (right, same row)
    meta_y_start = y
    y = draw_metadata(draw, fonts, entry, y)
    meta_h = y - meta_y_start

    # floor plan: anchored to content top, height = max(metadata block, min height)
    plan_h = max(meta_h, META_PLAN_MIN_H)
    plan_panel = render_floorplan(entry["location"], META_PLAN_W, plan_h)
    img.paste(plan_panel, (META_PLAN_X, TL_PAD + 100))

    # advance y past whichever is taller: metadata text or floor plan
    y = meta_y_start + plan_h + IPAD

    # 5. thin divider (full width)
    draw.line([PAD, y, W - PAD, y], fill=DIV_COL, width=1)
    y += IPAD

    # 6. thumbnails (full content width)
    thumbs = load_thumbnails(entry["session"], entry["timestamp"])
    strip = compose_thumb_row(thumbs, IMG_H, CONTENT_W)
    img.paste(strip, (PAD, y))
    y += IMG_H + IPAD

    # 7. thin divider
    draw.line([PAD, y, W - PAD, y], fill=DIV_COL, width=1)
    y += IPAD

    # 8. description
    font = fonts["md"]
    avg_cw = font.size * 0.55
    cpl    = max(1, int(CONTENT_W / avg_cw))
    for ln in textwrap.wrap(entry["description"], width=cpl):
        if y + font.size > H - PAD:
            break
        draw.text((PAD, y), ln, font=font, fill=DESC_COL)
        y += font.size + 5

    return img


# ── dates to render ───────────────────────────────────────────────────────────
RENDER_DATES = [
    "2026-04-05", "2026-04-06", "2026-04-07", "2026-04-09", "2026-04-10",
    "2026-04-11", "2026-04-17", "2026-04-19", "2026-04-21", "2026-04-22",
    "2026-04-24", "2026-04-26", "2026-04-30",
]

# ── main ──────────────────────────────────────────────────────────────────────
def render_date(date_str: str, fonts):
    log_file = LOGS_DIR / f"{date_str}.md"
    if not log_file.exists():
        print(f"[SKIP] {date_str} — log file not found"); return

    entries = parse_log(log_file)
    print(f"\n=== {date_str}: {len(entries)} entries ===")
    if not entries:
        print("  No entries parsed — check regex"); return

    out_dir   = Path(__file__).parent / f"preview_frames_{date_str}"
    out_video = Path(__file__).parent / f"preview_{date_str}.mp4"
    out_dir.mkdir(exist_ok=True)

    all_times = [e["time_display"] for e in entries]
    frames = []
    for i, entry in enumerate(entries):
        n_thumbs = len(load_thumbnails(entry["session"], entry["timestamp"]))
        print(f"  [{i+1}/{len(entries)}] {entry['timestamp']}  ({n_thumbs} thumbs)")
        frame = render_frame(entry, all_times, i, date_str, fonts)
        frame.save(out_dir / f"frame_{i:04d}.png")
        frames.append(frame)

    print(f"  Saved {len(frames)} frames → {out_dir}")
    print("  Assembling video...")
    from moviepy import ImageClip, concatenate_videoclips
    clips = [ImageClip(np.array(f)).with_duration(2) for f in frames]
    concatenate_videoclips(clips, method="compose").write_videofile(
        str(out_video), fps=24, codec="libx264", audio=False, logger="bar"
    )
    print(f"  Done → {out_video}")


def main():
    import sys
    fonts = load_fonts()
    dates = sys.argv[1:] if len(sys.argv) > 1 else RENDER_DATES
    for date_str in dates:
        render_date(date_str, fonts)


if __name__ == "__main__":
    main()
