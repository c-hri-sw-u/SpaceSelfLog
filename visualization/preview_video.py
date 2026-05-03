"""
SpaceSelfLog preview video generator.
Renders a short video from a few log batches: timeline + blurred thumbnails + log text.
"""

import re
import textwrap
from pathlib import Path
from PIL import Image, ImageFilter, ImageDraw, ImageFont
import numpy as np

# ── paths ────────────────────────────────────────────────────────────────────
THUMBNAILS_DIR = Path("/Users/mia/.spaceselflog/thumbnails")
LOGS_DIR = Path("/Users/mia/.openclaw/workspace/memory/physical-logs")
OUT_DIR = Path(__file__).parent / "preview_frames"
OUT_VIDEO = Path(__file__).parent / "preview.mp4"

# ── layout constants ─────────────────────────────────────────────────────────
W, H = 1920, 1080
TIMELINE_H = 72
PADDING = 40
THUMB_AREA_W = int(W * 0.42)
TEXT_AREA_X = THUMB_AREA_W + PADDING * 2
TEXT_AREA_W = W - TEXT_AREA_X - PADDING

# ── colors ───────────────────────────────────────────────────────────────────
BG           = (10, 10, 14)
TL_BG        = (18, 18, 24)
TL_MARKER    = (220, 80, 60)
TL_TICK      = (55, 55, 65)
TL_TEXT      = (100, 100, 115)
LABEL_COL    = (90, 90, 108)
ACTIVITY_COL = (220, 200, 130)
LOCATION_COL = (130, 190, 220)
OBJECTS_COL  = (155, 210, 155)
SOCIAL_COL   = (200, 155, 210)
NOTABLE_COL  = (210, 170, 130)
DESC_COL     = (185, 185, 195)
TS_COL       = (65, 65, 80)
DIM_WHITE    = (230, 230, 235)

BLUR_RADIUS = 14


# ── font loader ──────────────────────────────────────────────────────────────
def load_fonts():
    mono_candidates = [
        "/System/Library/Fonts/Supplemental/Courier New.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Monaco.ttf",
    ]
    sans_candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/SFNS.ttf",
    ]

    def first_valid(candidates):
        for p in candidates:
            if Path(p).exists():
                return p
        return None

    mono = first_valid(mono_candidates)
    sans = first_valid(sans_candidates)

    def f(path, size):
        if path:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
        return ImageFont.load_default(size=size)

    return {
        "ts":      f(mono, 22),
        "label":   f(sans, 18),
        "key":     f(sans, 20),
        "val":     f(sans, 20),
        "desc":    f(sans, 19),
        "tl":      f(mono, 16),
        "session": f(mono, 17),
        "date":    f(sans, 26),
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
    text = log_path.read_text()
    entries = []
    for m in ENTRY_RE.finditer(text):
        entries.append({
            "time_display": m.group(1),
            "timestamp":    m.group(2),
            "session":      m.group(3),
            "frames":       m.group(4).strip(),
            "activity":     m.group(5).strip(),
            "location":     m.group(6).strip(),
            "objects":      m.group(7).strip(),
            "social":       m.group(8).strip(),
            "notable":      m.group(9).strip(),
            "description":  m.group(10).strip(),
        })
    return entries


# ── thumbnail loader ─────────────────────────────────────────────────────────
def load_thumbnails(session: str, timestamp: str) -> list[Image.Image]:
    folder = THUMBNAILS_DIR / session / timestamp
    if not folder.exists():
        return []
    imgs = []
    for p in sorted(folder.iterdir()):
        if p.suffix.lower() in (".jpg", ".jpeg", ".png"):
            try:
                imgs.append(Image.open(p).convert("RGB"))
            except Exception:
                pass
    return imgs


# ── timeline strip ───────────────────────────────────────────────────────────
def draw_timeline(draw: ImageDraw.ImageDraw, fonts, time_str: str, date_str: str,
                  all_times: list[str], current_idx: int):
    draw.rectangle([0, 0, W, TIMELINE_H], fill=TL_BG)

    bar_x0 = 220
    bar_x1 = W - 60
    bar_y  = TIMELINE_H // 2
    bar_w  = bar_x1 - bar_x0

    draw.line([bar_x0, bar_y, bar_x1, bar_y], fill=TL_TICK, width=2)

    for h in range(25):
        x = bar_x0 + int(h / 24 * bar_w)
        tick_h = 10 if h % 6 == 0 else 5
        draw.line([x, bar_y - tick_h, x, bar_y + tick_h], fill=TL_TICK, width=1)
        if h % 6 == 0 and h < 24:
            draw.text((x - 18, bar_y + 13), f"{h:02d}:00", font=fonts["tl"], fill=TL_TEXT)

    # past/future entry dots
    for i, t in enumerate(all_times):
        if i == current_idx:
            continue
        x = bar_x0 + int(_time_to_minutes(t) / (24 * 60) * bar_w)
        col = (80, 80, 95) if i < current_idx else (40, 40, 52)
        draw.ellipse([x - 3, bar_y - 3, x + 3, bar_y + 3], fill=col)

    # current marker
    cx = bar_x0 + int(_time_to_minutes(time_str) / (24 * 60) * bar_w)
    draw.ellipse([cx - 7, bar_y - 7, cx + 7, bar_y + 7], fill=TL_MARKER)
    draw.text((cx - 22, bar_y - 26), time_str, font=fonts["tl"], fill=TL_MARKER)

    # date label
    draw.text((14, bar_y - 14), date_str, font=fonts["date"], fill=DIM_WHITE)


def _time_to_minutes(t: str) -> int:
    try:
        h, m = map(int, t.split(":"))
        return h * 60 + m
    except Exception:
        return 0


# ── thumbnail composite ───────────────────────────────────────────────────────
def compose_thumbnails(imgs: list[Image.Image], area_w: int, area_h: int) -> Image.Image:
    panel = Image.new("RGB", (area_w, area_h), BG)
    if not imgs:
        # placeholder
        draw = ImageDraw.Draw(panel)
        draw.text((area_w // 2 - 40, area_h // 2), "no frames", fill=TL_TICK)
        return panel

    n = len(imgs)
    cols = min(n, 3)
    rows = (n + cols - 1) // cols
    pad = 12
    cell_w = (area_w - pad * (cols + 1)) // cols
    cell_h = (area_h - pad * (rows + 1)) // rows

    for i, img in enumerate(imgs):
        blurred = img.filter(ImageFilter.GaussianBlur(radius=BLUR_RADIUS))
        blurred.thumbnail((cell_w, cell_h), Image.LANCZOS)
        tw, th = blurred.size
        col = i % cols
        row = i // cols
        x = pad + col * (cell_w + pad) + (cell_w - tw) // 2
        y = pad + row * (cell_h + pad) + (cell_h - th) // 2
        panel.paste(blurred, (x, y))
    return panel


# ── text panel ────────────────────────────────────────────────────────────────
def draw_text_panel(draw: ImageDraw.ImageDraw, fonts, entry: dict, x0: int, y0: int, w: int):
    y = y0

    def put(text, font, color, indent=0, gap=6):
        nonlocal y
        draw.text((x0 + indent, y), text, font=font, fill=color)
        y += font.size + gap

    def wrap_put(text, font, color, indent=0, gap=8, max_lines=None):
        nonlocal y
        # rough chars-per-line estimate
        avg_char_w = max(1, font.size * 0.55)
        cpl = max(1, int((w - indent) / avg_char_w))
        lines = textwrap.wrap(text, width=cpl)
        if max_lines:
            lines = lines[:max_lines]
        for line in lines:
            draw.text((x0 + indent, y), line, font=font, fill=color)
            y += font.size + 4
        y += gap

    # timestamp
    put(entry["timestamp"].replace("T", "  ").replace("Z", ""), fonts["ts"], TS_COL, gap=20)

    fields = [
        ("activity", entry["activity"],  ACTIVITY_COL),
        ("location", entry["location"],  LOCATION_COL),
        ("objects",  entry["objects"],   OBJECTS_COL),
        ("social",   entry["social"],    SOCIAL_COL),
        ("notable",  entry["notable"],   NOTABLE_COL),
    ]

    for key, val, col in fields:
        key_w = int(fonts["key"].getlength(key)) + 12
        draw.text((x0, y), key, font=fonts["key"], fill=LABEL_COL)
        # first line of value next to key
        avg_char_w = max(1, fonts["val"].size * 0.55)
        cpl = max(1, int((w - key_w) / avg_char_w))
        val_lines = textwrap.wrap(val, width=cpl)
        draw.text((x0 + key_w, y), val_lines[0] if val_lines else "", font=fonts["val"], fill=col)
        y += fonts["val"].size + 4
        for vl in val_lines[1:]:
            draw.text((x0 + key_w, y), vl, font=fonts["val"], fill=col)
            y += fonts["val"].size + 4
        y += 2

    y += 14
    draw.line([x0, y, x0 + w, y], fill=(40, 40, 52), width=1)
    y += 14

    wrap_put(entry["description"], fonts["desc"], DESC_COL, max_lines=11)


# ── full frame ────────────────────────────────────────────────────────────────
def render_frame(entry: dict, all_times: list[str], current_idx: int,
                 date_str: str, fonts) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    draw_timeline(draw, fonts, entry["time_display"], date_str, all_times, current_idx)

    thumb_y0 = TIMELINE_H + PADDING
    thumb_h  = H - thumb_y0 - PADDING * 2
    thumbs = load_thumbnails(entry["session"], entry["timestamp"])
    thumb_panel = compose_thumbnails(thumbs, THUMB_AREA_W - PADDING, thumb_h)
    img.paste(thumb_panel, (PADDING, thumb_y0))

    # session label
    draw.text((PADDING, H - PADDING - fonts["session"].size),
              entry["session"], font=fonts["session"], fill=TS_COL)

    draw_text_panel(draw, fonts, entry, TEXT_AREA_X, thumb_y0, TEXT_AREA_W)
    return img


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    OUT_DIR.mkdir(exist_ok=True)
    fonts = load_fonts()

    log_file = LOGS_DIR / "2026-03-22.md"
    entries = parse_log(log_file)
    print(f"Parsed {len(entries)} entries from {log_file.name}")

    if not entries:
        print("No entries parsed — check regex against log format")
        return

    preview = entries[:8]
    all_times = [e["time_display"] for e in entries]
    date_str = log_file.stem

    frames = []
    for i, entry in enumerate(preview):
        print(f"  [{i+1}/{len(preview)}] {entry['timestamp']}  ({len(load_thumbnails(entry['session'], entry['timestamp']))} thumbs)")
        frame = render_frame(entry, all_times, i, date_str, fonts)
        out_path = OUT_DIR / f"frame_{i:03d}.png"
        frame.save(out_path)
        frames.append(frame)

    print(f"\nSaved {len(frames)} frames to {OUT_DIR}")

    print("Assembling video...")
    from moviepy import ImageClip, concatenate_videoclips
    clips = [ImageClip(np.array(f)).with_duration(5) for f in frames]
    video = concatenate_videoclips(clips, method="compose")
    video.write_videofile(str(OUT_VIDEO), fps=24, codec="libx264", audio=False, logger="bar")
    print(f"\nDone → {OUT_VIDEO}")


if __name__ == "__main__":
    main()
