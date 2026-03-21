#!/usr/bin/env python3
"""
SpaceSelfLog Ingest Server
Layer 2 (VLM inference) + Layer 3 (OpenClaw memory write)

Receives POST /ingest from the iOS OutboxManager, runs Claude on the batch,
and appends the result to OpenClaw's physical-logs/ directory.

Config (env vars, or .env file):
  ANTHROPIC_API_KEY   — required
  OPENCLAW_MEMORY_DIR — path to OpenClaw's memory/ directory (required)
  FRAMES_DIR          — where to persist received frames (default: ~/.spaceselflog/frames)
  CONTEXT_FILE        — path to prior-batch context JSON (default: ~/.spaceselflog/context.json)
  PORT                — listen port (default: 8000)
  VLM_MODEL           — Claude model ID (default: claude-sonnet-4-6)
"""

import os
import sys
import json
import base64
import logging
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv(Path(__file__).parent / ".env")

ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
OPENCLAW_MEMORY_DIR = Path(os.environ.get("OPENCLAW_MEMORY_DIR", "")).expanduser()
FRAMES_DIR          = Path(os.environ.get("FRAMES_DIR", "~/.spaceselflog/frames")).expanduser()
CONTEXT_FILE        = Path(os.environ.get("CONTEXT_FILE", "~/.spaceselflog/context.json")).expanduser()
PORT                = int(os.environ.get("PORT", 8000))
VLM_MODEL           = os.environ.get("VLM_MODEL", "claude-sonnet-4-6")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("ingest")

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


@app.get("/status")
def status():
    return jsonify({
        "ok": True,
        "model": VLM_MODEL,
        "openclaw_memory_dir": str(OPENCLAW_MEMORY_DIR),
        "frames_dir": str(FRAMES_DIR),
    })


@app.post("/ingest")
def ingest():
    payload = request.get_json(force=True, silent=True)
    if not payload:
        return jsonify({"error": "invalid JSON"}), 400

    batch_id   = payload.get("batch_id", "unknown")
    session_id = payload.get("session_id", "unknown")
    created_at = payload.get("created_at", datetime.now(timezone.utc).isoformat())
    frames_raw = payload.get("frames", [])
    frames_meta = payload.get("frames_meta", [])
    input_frames = payload.get("input_frames", len(frames_raw))

    if not frames_raw:
        return jsonify({"error": "no frames"}), 400

    log.info("Received batch %s  session=%s  frames=%d/%d",
             batch_id, session_id, len(frames_raw), input_frames)

    # 1. Save frames to disk
    batch_dir = FRAMES_DIR / session_id / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)

    frame_paths = []
    for f in frames_raw:
        filename = f.get("filename", f"frame_{len(frame_paths):02d}.jpg")
        data = base64.b64decode(f["jpeg_base64"])
        path = batch_dir / filename
        path.write_bytes(data)
        frame_paths.append((filename, data))

    log.info("Saved %d frames to %s", len(frame_paths), batch_dir)

    # 2. Load prior batch context
    prior_summary = load_prior_context(session_id)

    # 3. Run VLM
    try:
        batch_created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        summary = run_vlm(
            frames=[(fn, d) for fn, d in frame_paths],
            frames_meta=frames_meta,
            batch_created=batch_created,
            input_frames=input_frames,
            prior_summary=prior_summary,
        )
    except Exception as e:
        log.error("VLM error: %s", e)
        return jsonify({"error": f"VLM failed: {e}"}), 500

    log.info("VLM summary (%d chars): %s…", len(summary), summary[:120])

    # 4. Save new context for next batch
    save_prior_context(session_id, summary)

    # 5. Write to OpenClaw memory
    try:
        write_physical_log(
            batch_id=batch_id,
            session_id=session_id,
            batch_created=batch_created,
            summary=summary,
            frame_count=len(frame_paths),
            input_frames=input_frames,
        )
    except Exception as e:
        log.error("Memory write error: %s", e)
        return jsonify({"error": f"memory write failed: {e}"}), 500

    return jsonify({"ok": True, "batch_id": batch_id, "summary_chars": len(summary)})


# ---------------------------------------------------------------------------
# VLM inference
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an egocentric perception system analyzing first-person video frames \
from a smartphone worn on the body. Your task is to generate a concise, \
factual observation about the wearer's physical context and activities.

Guidelines:
- Write exactly one paragraph of 4–6 sentences.
- Use past tense, third person ("the wearer").
- Be specific about what is visible: environment, objects, people, actions.
- Note social context (alone, with others) and any transitions.
- Do not speculate beyond what the frames and sensor tags show.
- Do not repeat the prior summary verbatim; only reference it for continuity.\
"""


def run_vlm(
    frames: list[tuple[str, bytes]],
    frames_meta: list[dict],
    batch_created: datetime,
    input_frames: int,
    prior_summary: str | None,
) -> str:
    """Call Claude with the batch frames and return a 1-paragraph summary."""

    # Build a lookup so we can match meta by filename
    meta_by_filename: dict[str, dict] = {m["filename"]: m for m in frames_meta}

    # Construct the message content
    content: list[dict] = []

    # Preamble
    duration_hint = ""
    if frames_meta:
        times = [m.get("captured_at") for m in frames_meta if m.get("captured_at")]
        if len(times) >= 2:
            t0 = datetime.fromisoformat(times[0].replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(times[-1].replace("Z", "+00:00"))
            secs = int((t1 - t0).total_seconds())
            duration_hint = f" spanning ~{secs}s"

    preamble = (
        f"Batch captured at {batch_created.strftime('%Y-%m-%d %H:%M')} UTC"
        f"{duration_hint}. "
        f"{len(frames)} key frames selected from {input_frames} total.\n"
    )

    if prior_summary:
        preamble += f"\nPrior batch summary (for continuity):\n{prior_summary}\n"

    preamble += "\nFrames follow, each annotated with sensor tags:\n"
    content.append({"type": "text", "text": preamble})

    # Add each frame + its sensor annotation
    for filename, jpeg_bytes in frames:
        meta = meta_by_filename.get(filename, {})
        audio = meta.get("audio_tags", {})
        imu   = meta.get("imu_tags", {})
        ts    = meta.get("captured_at", "")
        score = meta.get("score_total", "")

        annotation = (
            f"[{filename}  t={ts}  "
            f"motion={imu.get('motion_state','?')}  "
            f"speech={audio.get('speech_detected','?')}  "
            f"noise={audio.get('noise_level','?')}  "
            f"score={score}]"
        )
        content.append({"type": "text", "text": annotation})
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.b64encode(jpeg_bytes).decode(),
            },
        })

    content.append({
        "type": "text",
        "text": "Write your one-paragraph observation now.",
    })

    response = client.messages.create(
        model=VLM_MODEL,
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )

    return response.content[0].text.strip()


# ---------------------------------------------------------------------------
# Prior-batch context
# ---------------------------------------------------------------------------

def load_prior_context(session_id: str) -> str | None:
    if not CONTEXT_FILE.exists():
        return None
    try:
        data = json.loads(CONTEXT_FILE.read_text())
        return data.get(session_id)
    except Exception:
        return None


def save_prior_context(session_id: str, summary: str) -> None:
    CONTEXT_FILE.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if CONTEXT_FILE.exists():
        try:
            data = json.loads(CONTEXT_FILE.read_text())
        except Exception:
            pass
    data[session_id] = summary
    CONTEXT_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Layer 3: Write to OpenClaw memory
# ---------------------------------------------------------------------------

def write_physical_log(
    batch_id: str,
    session_id: str,
    batch_created: datetime,
    summary: str,
    frame_count: int,
    input_frames: int,
) -> None:
    """Append a log entry to physical-logs/YYYY-MM-DD.md in OpenClaw memory."""
    if not OPENCLAW_MEMORY_DIR or not str(OPENCLAW_MEMORY_DIR):
        log.warning("OPENCLAW_MEMORY_DIR not set — skipping memory write")
        return

    logs_dir = OPENCLAW_MEMORY_DIR / "physical-logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    date_str = batch_created.strftime("%Y-%m-%d")
    log_file = logs_dir / f"{date_str}.md"

    time_str = batch_created.strftime("%H:%M")

    entry = (
        f"\n## {time_str}  `{batch_id}`\n"
        f"<!-- session={session_id}  frames={frame_count}/{input_frames} -->\n\n"
        f"{summary}\n"
    )

    # Create file with header if new
    if not log_file.exists():
        log_file.write_text(f"# Physical Log — {date_str}\n")

    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(entry)

    log.info("Wrote log entry to %s", log_file)


# ---------------------------------------------------------------------------
# Startup checks
# ---------------------------------------------------------------------------

def check_config() -> bool:
    ok = True
    if not ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY is not set")
        ok = False
    if not str(OPENCLAW_MEMORY_DIR):
        log.warning("OPENCLAW_MEMORY_DIR is not set — memory writes will be skipped")
    else:
        log.info("OpenClaw memory dir: %s", OPENCLAW_MEMORY_DIR)
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    CONTEXT_FILE.parent.mkdir(parents=True, exist_ok=True)
    return ok


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not check_config():
        sys.exit(1)
    log.info("Starting ingest server on port %d  model=%s", PORT, VLM_MODEL)
    app.run(host="0.0.0.0", port=PORT, debug=False)
