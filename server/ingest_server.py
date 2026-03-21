#!/usr/bin/env python3
"""
SpaceSelfLog Ingest Server
Layer 2 (VLM inference) + Layer 3 (OpenClaw memory write)

Routes
  GET  /               → monitor UI
  GET  /status         → health check
  POST /ingest         → receive batch from iOS OutboxManager
  GET  /api/config     → read current config
  POST /api/config     → save + apply config
  POST /api/test       → test API key / model
  GET  /api/batches    → recent batch history (last 50)
  GET  /api/frames/<session>/<batch>/<file>  → serve saved JPEG

Config (env vars or .env, overridden by ~/.spaceselflog/config.json via UI):
  OPENROUTER_API_KEY / ANTHROPIC_API_KEY
  OPENCLAW_MEMORY_DIR
  FRAMES_DIR      (default: ~/.spaceselflog/frames)
  CONTEXT_FILE    (default: ~/.spaceselflog/context.json)
  CONFIG_FILE     (default: ~/.spaceselflog/config.json)
  PORT            (default: 8000)
  VLM_MODEL       (default: anthropic/claude-sonnet-4-6)
"""

import os, sys, json, base64, logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import anthropic as anthropic_sdk
from openai import OpenAI
from flask import Flask, request, jsonify, send_file
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ---------------------------------------------------------------------------
# Paths & port (from env only; all other settings go through config.json)
# ---------------------------------------------------------------------------

CONFIG_FILE  = Path(os.environ.get("CONFIG_FILE",  "~/.spaceselflog/config.json")).expanduser()
CONTEXT_FILE = Path(os.environ.get("CONTEXT_FILE", "~/.spaceselflog/context.json")).expanduser()
PORT         = int(os.environ.get("PORT", 8000))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("ingest")

# ---------------------------------------------------------------------------
# Config management
# ---------------------------------------------------------------------------

_DEFAULT_PROMPT = """\
You are an egocentric perception system analyzing first-person video frames \
from a smartphone worn on the body. Your role is to surface information that \
a personal AI agent should know about its user — not just "what is happening" \
but "what does this reveal about the user's habits, preferences, environment, \
and current activity?"

Output exactly these fields. Mark any field "not observed" if the frames and \
sensor tags do not provide sufficient evidence — do not guess.

activity: <current action or task, e.g. "cooking", "desk work", "walking outside">
location: <environment or place type, e.g. "home kitchen", "office", "outdoors">
objects: <notable objects relevant to the user's context or habits>
social_context: <alone / with others; if others, describe visible interaction>
notable_events: <transitions, significant actions, or moments worth remembering>
observation: <one paragraph, 4–6 sentences, past tense, third person — \
faithful description first, then interpretive annotation relevant to personalization>

Guidelines:
- Use IMU and audio tags to ground your interpretation \
(e.g. stationary + speech detected → likely in conversation).
- If you cannot determine something, write "not observed" rather than guessing.
- Do not repeat the prior summary verbatim; only reference it for continuity.\
"""

_DEFAULTS: dict = {
    "provider":            "openrouter",
    "api_key":             os.environ.get("OPENROUTER_API_KEY")
                           or os.environ.get("ANTHROPIC_API_KEY", ""),
    "model":               os.environ.get("VLM_MODEL", "anthropic/claude-sonnet-4-6"),
    "openclaw_memory_dir": os.environ.get("OPENCLAW_MEMORY_DIR", ""),
    "frames_dir":          os.environ.get("FRAMES_DIR",
                               str(Path("~/.spaceselflog/frames").expanduser())),
    "prompt":              _DEFAULT_PROMPT,
}


def _load_config() -> dict:
    cfg = dict(_DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text()))
        except Exception:
            pass
    return cfg


def _save_config(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))


_config: dict = _load_config()

# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def _make_client(cfg: dict):
    if cfg.get("provider") == "anthropic":
        return anthropic_sdk.Anthropic(api_key=cfg["api_key"])
    return OpenAI(api_key=cfg["api_key"], base_url="https://openrouter.ai/api/v1")


_client = _make_client(_config)

# ---------------------------------------------------------------------------
# Batch history  (in-memory, last 50)
# ---------------------------------------------------------------------------

_batches: deque = deque(maxlen=50)  # each entry: dict


def _record_batch(entry: dict) -> None:
    _batches.appendleft(entry)   # newest first


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder=str(Path(__file__).parent))


@app.get("/")
def monitor():
    return send_file(Path(__file__).parent / "monitor.html")


@app.get("/status")
def status():
    cfg = _config
    return jsonify({
        "ok":                  True,
        "provider":            cfg.get("provider"),
        "model":               cfg.get("model"),
        "openclaw_memory_dir": cfg.get("openclaw_memory_dir"),
        "frames_dir":          cfg.get("frames_dir"),
        "batches_received":    len(_batches),
    })


# ---------------------------------------------------------------------------
# Config API
# ---------------------------------------------------------------------------

@app.get("/api/config")
def get_config():
    safe = dict(_config)
    # Mask key for display (show last 6 chars only)
    key = safe.get("api_key", "")
    safe["api_key_masked"] = ("•" * max(0, len(key) - 6) + key[-6:]) if key else ""
    return jsonify(safe)


@app.post("/api/config")
def post_config():
    global _config, _client
    body = request.get_json(force=True, silent=True) or {}
    # Merge into current config; ignore unknown keys
    allowed = {"provider", "api_key", "model", "openclaw_memory_dir", "frames_dir", "prompt"}
    for k in allowed:
        if k in body:
            _config[k] = body[k]
    _save_config(_config)
    _client = _make_client(_config)
    log.info("Config updated: provider=%s model=%s", _config["provider"], _config["model"])
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Test API
# ---------------------------------------------------------------------------

@app.post("/api/test")
def test_connection():
    body   = request.get_json(force=True, silent=True) or {}
    cfg    = {**_config, **{k: body[k] for k in ("provider", "api_key", "model") if k in body}}
    try:
        client = _make_client(cfg)
        if cfg.get("provider") == "anthropic":
            r     = client.messages.create(
                model=cfg["model"], max_tokens=16,
                messages=[{"role": "user", "content": "Reply with one word: ready"}])
            reply = r.content[0].text.strip()
        else:
            r     = client.chat.completions.create(
                model=cfg["model"], max_tokens=16,
                messages=[{"role": "user", "content": "Reply with one word: ready"}])
            reply = r.choices[0].message.content.strip()
        return jsonify({"ok": True, "reply": reply})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

@app.post("/ingest")
def ingest():
    payload = request.get_json(force=True, silent=True)
    if not payload:
        return jsonify({"error": "invalid JSON"}), 400

    batch_id     = payload.get("batch_id", "unknown")
    session_id   = payload.get("session_id", "unknown")
    created_at   = payload.get("created_at", datetime.now(timezone.utc).isoformat())
    frames_raw   = payload.get("frames", [])
    frames_meta  = payload.get("frames_meta", [])
    input_frames = payload.get("input_frames", len(frames_raw))

    if not frames_raw:
        return jsonify({"error": "no frames"}), 400

    log.info("Received batch %s  session=%s  frames=%d/%d",
             batch_id, session_id, len(frames_raw), input_frames)

    received_at = datetime.now(timezone.utc).isoformat()

    # 1. Save frames to disk
    frames_dir = Path(_config["frames_dir"])
    batch_dir  = frames_dir / session_id / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)

    frame_paths: list[tuple[str, bytes]] = []
    for f in frames_raw:
        filename = f.get("filename", f"frame_{len(frame_paths):02d}.jpg")
        data     = base64.b64decode(f["jpeg_base64"])
        (batch_dir / filename).write_bytes(data)
        frame_paths.append((filename, data))

    # Save manifest (payload minus the heavy base64 frames array)
    manifest = {k: v for k, v in payload.items() if k != "frames"}
    (batch_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False)
    )

    # 2. Load prior context
    prior_summary = _load_prior_context(session_id)

    # 3. Run VLM
    batch_created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    summary = error_msg = None
    try:
        summary = _run_vlm(
            frames=frame_paths,
            frames_meta=frames_meta,
            batch_created=batch_created,
            input_frames=input_frames,
            prior_summary=prior_summary,
        )
        _save_prior_context(session_id, summary)
        log.info("VLM ok — %d chars", len(summary))
    except Exception as e:
        error_msg = str(e)
        log.error("VLM error: %s", e)

    # 4. Write memory (only on success)
    mem_error = None
    if summary:
        try:
            _write_physical_log(
                batch_id=batch_id, session_id=session_id,
                batch_created=batch_created, summary=summary,
                frame_count=len(frame_paths), input_frames=input_frames,
            )
        except Exception as e:
            mem_error = str(e)
            log.error("Memory write error: %s", e)

    # 5. Record in history
    _record_batch({
        "batch_id":    batch_id,
        "session_id":  session_id,
        "received_at": received_at,
        "created_at":  created_at,
        "frame_count": len(frame_paths),
        "input_frames": input_frames,
        "filenames":   [fn for fn, _ in frame_paths],
        "summary":     summary,
        "status":      "error" if error_msg else "ok",
        "error":       error_msg or mem_error,
    })

    if error_msg:
        return jsonify({"error": error_msg}), 500
    return jsonify({"ok": True, "batch_id": batch_id, "summary": summary})


# ---------------------------------------------------------------------------
# Batch history API
# ---------------------------------------------------------------------------

@app.get("/api/batches")
def get_batches():
    return jsonify(list(_batches))


# ---------------------------------------------------------------------------
# Frame file serving
# ---------------------------------------------------------------------------

@app.get("/api/frames/<session_id>/<batch_id>/<filename>")
def serve_frame(session_id: str, batch_id: str, filename: str):
    path = Path(_config["frames_dir"]) / session_id / batch_id / filename
    if not path.exists():
        return "not found", 404
    return send_file(path, mimetype="image/jpeg")


# ---------------------------------------------------------------------------
# VLM inference
# ---------------------------------------------------------------------------

def _system_prompt() -> str:
    return _config.get("prompt") or _DEFAULT_PROMPT


def _build_preamble(frames_meta: list[dict], batch_created: datetime,
                    input_frames: int, frame_count: int,
                    prior_summary: str | None) -> str:
    duration_hint = ""
    times = [m.get("captured_at") for m in frames_meta if m.get("captured_at")]
    if len(times) >= 2:
        t0   = datetime.fromisoformat(times[0].replace("Z", "+00:00"))
        t1   = datetime.fromisoformat(times[-1].replace("Z", "+00:00"))
        secs = int((t1 - t0).total_seconds())
        duration_hint = f" spanning ~{secs}s"

    text = (f"Batch captured at {batch_created.strftime('%Y-%m-%d %H:%M')} UTC"
            f"{duration_hint}. "
            f"{frame_count} key frames selected from {input_frames} total, "
            f"presented in chronological order.\n")
    if prior_summary:
        text += f"\nPrior batch summary (for continuity):\n{prior_summary}\n"
    text += "\nFrames follow, each labeled with its index, relative timestamp, and sensor tags:\n"
    return text


def _frame_annotation(idx: int, total: int, meta: dict, t0: datetime) -> str:
    audio    = meta.get("audio_tags", {})
    imu      = meta.get("imu_tags", {})
    ts_str   = meta.get("captured_at", "")
    rel_secs = 0
    if ts_str:
        try:
            t = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            rel_secs = max(0, int((t - t0).total_seconds()))
        except ValueError:
            pass
    return (f"[Frame {idx + 1}/{total}  +{rel_secs}s  "
            f"motion={imu.get('motion_state','?')}  "
            f"speech={audio.get('speech_detected','?')}  "
            f"noise={audio.get('noise_level','?')}]")


def _run_vlm(frames: list[tuple[str, bytes]], frames_meta: list[dict],
             batch_created: datetime, input_frames: int,
             prior_summary: str | None) -> str:
    meta_by_file = {m["filename"]: m for m in frames_meta}
    preamble     = _build_preamble(frames_meta, batch_created, input_frames,
                                   len(frames), prior_summary)

    # Compute t0 from the first frame's captured_at (fallback: batch_created)
    times = [m.get("captured_at") for m in frames_meta if m.get("captured_at")]
    t0 = batch_created
    if times:
        try:
            t0 = datetime.fromisoformat(times[0].replace("Z", "+00:00"))
        except ValueError:
            pass

    if _config.get("provider") == "anthropic":
        return _run_vlm_anthropic(frames, meta_by_file, preamble, t0)
    return _run_vlm_openrouter(frames, meta_by_file, preamble, t0)


def _run_vlm_openrouter(frames, meta_by_file, preamble, t0) -> str:
    total   = len(frames)
    content: list[dict] = [{"type": "text", "text": preamble}]
    for idx, (filename, jpeg_bytes) in enumerate(frames):
        meta = meta_by_file.get(filename, {})
        content.append({"type": "text", "text": _frame_annotation(idx, total, meta, t0)})
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{base64.b64encode(jpeg_bytes).decode()}"},
        })
    content.append({"type": "text", "text": "Write your structured observation now, following the output format exactly."})

    r = _client.chat.completions.create(
        model=_config["model"], max_tokens=512,
        messages=[{"role": "system", "content": _system_prompt()},
                  {"role": "user",   "content": content}],
    )
    return r.choices[0].message.content.strip()


def _run_vlm_anthropic(frames, meta_by_file, preamble, t0) -> str:
    total   = len(frames)
    content: list[dict] = [{"type": "text", "text": preamble}]
    for idx, (filename, jpeg_bytes) in enumerate(frames):
        meta = meta_by_file.get(filename, {})
        content.append({"type": "text", "text": _frame_annotation(idx, total, meta, t0)})
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg",
                       "data": base64.b64encode(jpeg_bytes).decode()},
        })
    content.append({"type": "text", "text": "Write your structured observation now, following the output format exactly."})

    r = _client.messages.create(
        model=_config["model"], max_tokens=512,
        system=_system_prompt(),
        messages=[{"role": "user", "content": content}],
    )
    return r.content[0].text.strip()


# ---------------------------------------------------------------------------
# Prior-batch context
# ---------------------------------------------------------------------------

def _load_prior_context(session_id: str) -> str | None:
    if not CONTEXT_FILE.exists():
        return None
    try:
        return json.loads(CONTEXT_FILE.read_text()).get(session_id)
    except Exception:
        return None


def _save_prior_context(session_id: str, summary: str) -> None:
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
# Layer 3: OpenClaw memory write
# ---------------------------------------------------------------------------

_ISO = "%Y-%m-%dT%H:%M:%SZ"


def _write_physical_log(batch_id, session_id, batch_created,
                         summary, frame_count, input_frames) -> None:
    mem_dir = _config.get("openclaw_memory_dir", "")
    if not mem_dir:
        log.warning("openclaw_memory_dir not set — skipping memory write")
        return

    logs_dir = Path(mem_dir).expanduser() / "physical-logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    date_str = batch_created.strftime("%Y-%m-%d")
    log_file = logs_dir / f"{date_str}.md"
    time_str = batch_created.strftime("%H:%M")

    entry = (f"\n## {time_str}  `{batch_id}`\n"
             f"<!-- session={session_id}  frames={frame_count}/{input_frames} -->\n\n"
             f"{summary}\n")

    if not log_file.exists():
        log_file.write_text(f"# Physical Log — {date_str}\n")
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(entry)

    log.info("Memory write → %s", log_file)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not _config.get("api_key"):
        log.warning("API key not set — configure via monitor at http://localhost:%d", PORT)
    log.info("Starting on port %d  provider=%s  model=%s",
             PORT, _config["provider"], _config["model"])
    Path(_config["frames_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    app.run(host="0.0.0.0", port=PORT, debug=False)
