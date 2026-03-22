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
import threading

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
EVENTS_FILE  = Path(os.environ.get("EVENTS_FILE",  "~/.spaceselflog/events.jsonl")).expanduser()
PORT         = int(os.environ.get("PORT", 8000))

_events_lock = threading.Lock()

def _append_event(type: str, **kwargs) -> None:
    """Append a structured event to events.jsonl (thread-safe)."""
    entry = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "type": type}
    entry.update(kwargs)
    line = json.dumps(entry, ensure_ascii=False)
    try:
        EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _events_lock:
            with EVENTS_FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception as e:
        log.warning("Failed to write event log: %s", e)

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

Respond with a single JSON object and nothing else:
{
  "activity": "<current action or task, e.g. 'cooking', 'desk work', 'walking outside'>",
  "location": "<environment or place type, e.g. 'home kitchen', 'office', 'outdoors'>",
  "objects": "<notable objects relevant to the user's context or habits>",
  "social_context": "<alone / with others; if others, describe visible interaction>",
  "notable_events": "<transitions, significant actions, or moments worth remembering>",
  "observation": "<one paragraph, 4–6 sentences, past tense, third person — faithful description first, then interpretive annotation relevant to personalization>"
}

Guidelines:
- Use IMU and audio tags to ground your interpretation \
(e.g. stationary + speech detected → likely in conversation).
- Set any field to "not observed" if the frames and sensor tags do not provide \
sufficient evidence — do not guess.
- Do not repeat the prior summary verbatim; only reference it for continuity.\
"""

_DEFAULT_PATTERN_PROMPT = """\
You are maintaining a persistent behavioral profile for a personal AI \
agent whose job is to proactively help its user — anticipating needs, \
offering timely suggestions, and adapting responses to what is actually \
happening in the user's life. This profile is injected into every agent \
session, so it must be concise and high-signal.

Inputs:
1. Current profile (empty on first run)
2. Today's insights summary

Update rules:
- Merge new evidence into existing entries. Do not simply append.
- For each entry, note how many days it has been observed (e.g., \
  "cooks dinner ~18:00 — observed 5 of 9 days"). This replaces \
  vague confidence language.
- Remove or revise entries clearly contradicted by new evidence.
- Be specific: "works at desk 09:00–12:00 most weekdays" not \
  "works in mornings".
- Apply the same filter as the insights file: could the agent use \
  this pattern to help the user — answer a question better, make a \
  timely suggestion, or anticipate a need? If not, omit it.

Structure the profile into whatever sections best organize the \
current evidence. Do not force empty sections. Sections will \
naturally emerge and evolve as evidence accumulates.

Guidelines:
- Third person. Markdown only, no preamble.
- Keep the total file concise — this consumes context budget on \
  every turn of every session.\
"""

_INSIGHT_PROMPT = """\
You are distilling today's physical-world perception logs into a daily \
summary for a personal AI agent whose job is to proactively help its \
user — anticipating needs, offering timely suggestions, and adapting \
responses to what is actually happening in the user's life. This \
summary is the agent's only window into the physical world, so include \
anything that could inform a helpful action.

Inputs:
1. Previous version of today's insights file (empty on first run)
2. Perception logs since the last run

Carry forward previous highlights that still pass the filter. Drop an \
item only when later observations clearly contradict or supersede it, \
not simply because it is from earlier in the day.

## Current State (as of [timestamp of most recent log entry])
2-3 sentences. What is the user doing, where, with whom, and in what \
mode (focused, relaxed, transitioning, social)?

## Today's Highlights
Bullet list. For each candidate item, ask: could the agent use this to \
help the user — answer a question better, make a timely suggestion, or \
anticipate an upcoming need? If not, omit it.

Each item should be specific to today — a behavior, schedule deviation, \
object, or event that suggests a need or preference. Typical days \
produce 3-8 items; fewer is fine.

Guidelines:
- Write for the agent, not for a diary.
- No patterns or habits — that belongs in the separate pattern file.
- Third person. Markdown only, no preamble.\
"""

_INSIGHT_MIN_BATCHES  = 5
_INSIGHT_MIN_MINUTES  = 30

_DEFAULTS: dict = {
    "provider":            "openrouter",
    "api_key":             os.environ.get("OPENROUTER_API_KEY")
                           or os.environ.get("ANTHROPIC_API_KEY", ""),
    "model":               os.environ.get("VLM_MODEL", "anthropic/claude-sonnet-4-6"),
    "openclaw_memory_dir": os.environ.get("OPENCLAW_MEMORY_DIR", ""),
    "frames_dir":          os.environ.get("FRAMES_DIR",
                               str(Path("~/.spaceselflog/frames").expanduser())),
    "prompt":              _DEFAULT_PROMPT,
    "insight_prompt":      _INSIGHT_PROMPT,
    "pattern_prompt":      _DEFAULT_PATTERN_PROMPT,
    "nightly_hour":        2,
    "insight_min_batches": _INSIGHT_MIN_BATCHES,
    "insight_min_minutes": _INSIGHT_MIN_MINUTES,
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
# Rolling insight state
# ---------------------------------------------------------------------------

_insight_lock         = threading.Lock()
_insight_batch_count  = 0               # batches since last insight update
_insight_last_time: datetime | None = None   # UTC time of last insight update
_insight_log_offset: dict[str, int] = {}     # date_str -> byte offset already incorporated
_insight_runs_today: dict[str, int] = {}     # date_str -> successful run count


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
    allowed = {"provider", "api_key", "model", "openclaw_memory_dir", "frames_dir",
               "prompt", "insight_prompt", "pattern_prompt", "nightly_hour",
               "insight_min_batches", "insight_min_minutes"}
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
            date_str = batch_created.astimezone().strftime("%Y-%m-%d")
            threading.Thread(
                target=_maybe_update_today_insight,
                args=(date_str,),
                daemon=True,
            ).start()
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
        _append_event("batch", status="error", batch_id=batch_id,
                      session_id=session_id, frames=len(frame_paths), error=error_msg)
        return jsonify({"error": error_msg}), 500

    if mem_error:
        _append_event("batch", status="ok", batch_id=batch_id,
                      session_id=session_id, frames=len(frame_paths), mem_error=mem_error)
    else:
        _append_event("batch", status="ok", batch_id=batch_id,
                      session_id=session_id, frames=len(frame_paths))
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


_REQUIRED_JSON_FIELDS = {"activity", "location", "objects", "social_context",
                         "notable_events", "observation"}


def _strip_json_fences(text: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` wrappers if present."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]          # drop opening fence line
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]     # drop closing fence
    return text.strip()


def _validate_json(text: str) -> dict:
    """Parse and validate VLM JSON output. Raises ValueError on failure."""
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("top-level value is not a JSON object")
    missing = _REQUIRED_JSON_FIELDS - data.keys()
    if missing:
        raise ValueError(f"missing fields: {missing}")
    return data


def _run_vlm(frames: list[tuple[str, bytes]], frames_meta: list[dict],
             batch_created: datetime, input_frames: int,
             prior_summary: str | None, max_retries: int = 2) -> str:
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

    call = (_run_vlm_anthropic if _config.get("provider") == "anthropic"
            else _run_vlm_openrouter)

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        raw = call(frames, meta_by_file, preamble, t0)
        cleaned = _strip_json_fences(raw)
        try:
            _validate_json(cleaned)
            if attempt > 1:
                log.info("JSON validation passed on attempt %d", attempt)
            return cleaned
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            log.warning("JSON validation failed (attempt %d/%d): %s",
                        attempt, max_retries, e)

    raise ValueError(f"VLM returned invalid JSON after {max_retries} attempts: {last_error}")


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
    content.append({"type": "text", "text": "Write your JSON observation now. Output only the JSON object, no markdown fences or extra text."})

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
    content.append({"type": "text", "text": "Write your JSON observation now. Output only the JSON object, no markdown fences or extra text."})

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

    local_created = batch_created.astimezone()
    date_str = local_created.strftime("%Y-%m-%d")
    log_file = logs_dir / f"{date_str}.md"
    time_str = local_created.strftime("%H:%M")

    # Parse JSON output from VLM; fall back to raw text if malformed
    try:
        data = json.loads(summary)
        fields = ["activity", "location", "objects", "social_context", "notable_events"]
        meta   = "  |  ".join(f"**{f}:** {data[f]}" for f in fields if data.get(f) and data[f] != "not observed")
        body   = data.get("observation", summary)
        entry  = (f"\n## {time_str}  `{batch_id}`\n"
                  f"<!-- session={session_id}  frames={frame_count}/{input_frames} -->\n\n"
                  f"{meta}\n\n{body}\n")
    except (json.JSONDecodeError, KeyError):
        log.warning("VLM output was not valid JSON — writing raw text")
        entry  = (f"\n## {time_str}  `{batch_id}`\n"
                  f"<!-- session={session_id}  frames={frame_count}/{input_frames} -->\n\n"
                  f"{summary}\n")

    if not log_file.exists():
        log_file.write_text(f"# Physical Log — {date_str}\n")
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(entry)

    log.info("Memory write → %s", log_file)


# ---------------------------------------------------------------------------
# Rolling insight: physical-insights/YYYY-MM-DD.md
# ---------------------------------------------------------------------------

def _maybe_update_today_insight(date_str: str) -> None:
    """Increment batch counter; trigger insight update if conditions are met."""
    global _insight_batch_count, _insight_last_time, _insight_runs_today
    with _insight_lock:
        _insight_batch_count += 1
        now = datetime.now(timezone.utc)
        min_batches = int(_config.get("insight_min_batches", _INSIGHT_MIN_BATCHES))
        min_minutes = int(_config.get("insight_min_minutes", _INSIGHT_MIN_MINUTES))
        elapsed = (
            (now - _insight_last_time).total_seconds() / 60
            if _insight_last_time else float("inf")
        )
        should_update = (
            _insight_batch_count >= min_batches
            or elapsed >= min_minutes
        )
        if not should_update:
            return
        # Reset counters before triggering (so a slow update doesn't double-fire)
        _insight_batch_count = 0
        _insight_last_time   = now
        _insight_runs_today[date_str] = _insight_runs_today.get(date_str, 0) + 1

    # Run outside the lock — this is a slow LLM call
    try:
        _update_today_insight(date_str)
        _append_event("insight", status="ok", date=date_str,
                      run=_insight_runs_today.get(date_str, 1))
    except Exception as e:
        log.error("Insight update error: %s", e)
        _append_event("insight", status="error", date=date_str, error=str(e))


def _update_today_insight(date_str: str) -> None:
    """Incorporate new log entries into today's insight file (incremental)."""
    global _insight_log_offset

    mem_dir = _config.get("openclaw_memory_dir", "")
    if not mem_dir:
        return

    log_file = Path(mem_dir).expanduser() / "physical-logs" / f"{date_str}.md"
    if not log_file.exists():
        return

    # Read only new content since last update
    offset = _insight_log_offset.get(date_str, 0)
    with log_file.open("r", encoding="utf-8") as fh:
        fh.seek(offset)
        new_logs = fh.read()
    new_offset = log_file.stat().st_size

    if not new_logs.strip():
        return

    insights_dir = Path(mem_dir).expanduser() / "physical-insights"
    insights_dir.mkdir(parents=True, exist_ok=True)
    insight_file = insights_dir / f"{date_str}.md"

    existing_insight = ""
    if insight_file.exists():
        # Strip the auto-generated comment header before feeding to model
        text = insight_file.read_text(encoding="utf-8")
        existing_insight = "\n".join(
            line for line in text.splitlines() if not line.startswith("<!--")
        ).strip()

    if existing_insight:
        user_msg = (
            f"Existing summary for {date_str}:\n\n{existing_insight}\n\n"
            f"---\nNew perception logs to incorporate:\n\n{new_logs}"
        )
    else:
        user_msg = f"Physical perception logs for {date_str}:\n\n{new_logs}"

    insight_system = _config.get("insight_prompt") or _INSIGHT_PROMPT

    if _config.get("provider") == "anthropic":
        client = anthropic_sdk.Anthropic(api_key=_config["api_key"])
        r = client.messages.create(
            model=_config["model"], max_tokens=1024,
            system=insight_system,
            messages=[{"role": "user", "content": user_msg}],
        )
        insight = r.content[0].text.strip()
    else:
        r = _client.chat.completions.create(
            model=_config["model"], max_tokens=1024,
            messages=[
                {"role": "system", "content": insight_system},
                {"role": "user",   "content": user_msg},
            ],
        )
        insight = r.choices[0].message.content.strip()

    runs = _insight_runs_today.get(date_str, 1)
    now_str = datetime.now(timezone.utc).strftime("%H:%M UTC")
    insight_file.write_text(
        f"<!-- auto-generated by SpaceSelfLog — update #{runs} — last updated {now_str} -->\n\n"
        + insight + "\n",
        encoding="utf-8",
    )
    _insight_log_offset[date_str] = new_offset
    log.info("Insight updated → %s  (offset %d→%d)", insight_file, offset, new_offset)


# ---------------------------------------------------------------------------
# Nightly pattern update: physical-pattern.md
# ---------------------------------------------------------------------------

_pattern_last_run_date: str | None = None   # local date string of last successful run


def _run_nightly_pattern_update(date_str: str, extra_date_str: str | None = None) -> None:
    """Merge one or two days' insights into physical-pattern.md.

    date_str is always the primary date (yesterday when triggered after midnight).
    extra_date_str is an optional second date (today) to include when the trigger
    fires after midnight and today already has some logged activity.
    """
    global _pattern_last_run_date

    mem_dir = _config.get("openclaw_memory_dir", "")
    if not mem_dir:
        log.warning("Nightly pattern: openclaw_memory_dir not set — skipping")
        return

    insights_dir = Path(mem_dir).expanduser() / "physical-insights"

    insight_file = insights_dir / f"{date_str}.md"
    if not insight_file.exists():
        log.warning("Nightly pattern: no insight file for %s — skipping", date_str)
        return

    combined_insight = insight_file.read_text(encoding="utf-8").strip()
    if not combined_insight:
        return

    # Append today's partial insight if it exists and has content
    if extra_date_str:
        extra_file = insights_dir / f"{extra_date_str}.md"
        if extra_file.exists():
            extra_text = extra_file.read_text(encoding="utf-8").strip()
            if extra_text:
                combined_insight += f"\n\n---\nPartial insight for {extra_date_str}:\n\n{extra_text}"
                log.info("Nightly pattern: also including partial insight for %s", extra_date_str)

    pattern_file = Path(mem_dir).expanduser() / "physical-pattern.md"
    existing_pattern = ""
    if pattern_file.exists():
        text = pattern_file.read_text(encoding="utf-8")
        existing_pattern = "\n".join(
            line for line in text.splitlines() if not line.startswith("<!--")
        ).strip()

    dates_label = f"{date_str}" + (f" + {extra_date_str}" if extra_date_str else "")
    if existing_pattern:
        user_msg = (
            f"Current profile:\n\n{existing_pattern}\n\n"
            f"---\nNew daily insight ({dates_label}) to merge in:\n\n{combined_insight}"
        )
    else:
        user_msg = f"Daily insight ({dates_label}) — no existing profile yet:\n\n{combined_insight}"

    pattern_system = _config.get("pattern_prompt") or _DEFAULT_PATTERN_PROMPT

    try:
        if _config.get("provider") == "anthropic":
            client = anthropic_sdk.Anthropic(api_key=_config["api_key"])
            r = client.messages.create(
                model=_config["model"], max_tokens=2048,
                system=pattern_system,
                messages=[{"role": "user", "content": user_msg}],
            )
            updated = r.content[0].text.strip()
        else:
            r = _client.chat.completions.create(
                model=_config["model"], max_tokens=2048,
                messages=[
                    {"role": "system", "content": pattern_system},
                    {"role": "user",   "content": user_msg},
                ],
            )
            updated = r.choices[0].message.content.strip()

        pattern_file.write_text(
            f"<!-- auto-generated by SpaceSelfLog — last updated {date_str} -->\n\n"
            + updated + "\n",
            encoding="utf-8",
        )
        _pattern_last_run_date = date_str
        log.info("physical-pattern.md updated for %s", date_str)
        _append_event("pattern", status="ok", date=date_str,
                      extra_date=extra_date_str)

    except Exception as e:
        log.error("Nightly pattern update failed: %s", e)
        _append_event("pattern", status="error", date=date_str, error=str(e))


def _nightly_scheduler() -> None:
    """Background thread: trigger pattern update each night at configured hour."""
    import time as _time
    while True:
        _time.sleep(600)   # check every 10 minutes
        now_local = datetime.now()
        nightly_hour = int(_config.get("nightly_hour", 2))
        if now_local.hour != nightly_hour:
            continue
        from datetime import timedelta
        # If trigger fires after midnight, yesterday is the completed day;
        # today may already have partial activity worth including.
        # If trigger fires before midnight (e.g. 23:00), only today matters.
        if nightly_hour < 12:
            primary = (now_local - timedelta(days=1)).strftime("%Y-%m-%d")
            extra = now_local.strftime("%Y-%m-%d")
        else:
            primary = now_local.strftime("%Y-%m-%d")
            extra = None
        if _pattern_last_run_date == primary:
            continue   # already ran for this date
        log.info("Nightly scheduler: running pattern update for %s", primary)
        _run_nightly_pattern_update(primary, extra_date_str=extra)


# ---------------------------------------------------------------------------
# Memory read API
# ---------------------------------------------------------------------------

import re as _re

@app.get("/api/insight/status")
def get_insight_status():
    """Return current auto-insight trigger progress and today's run count."""
    with _insight_lock:
        now = datetime.now(timezone.utc)
        min_batches = int(_config.get("insight_min_batches", _INSIGHT_MIN_BATCHES))
        min_minutes = int(_config.get("insight_min_minutes", _INSIGHT_MIN_MINUTES))
        batches_since = _insight_batch_count
        minutes_since = (
            round((now - _insight_last_time).total_seconds() / 60, 1)
            if _insight_last_time else None
        )
        today = datetime.now().strftime("%Y-%m-%d")
        runs_today = _insight_runs_today.get(today, 0)
        last_run_at = _insight_last_time.isoformat() if _insight_last_time else None
    return jsonify({
        "runs_today":            runs_today,
        "batches_since":         batches_since,
        "min_batches":           min_batches,
        "minutes_since":         minutes_since,
        "min_minutes":           min_minutes,
        "last_run_at":           last_run_at,
        "pattern_last_run_date": _pattern_last_run_date,
    })


@app.get("/api/events")
def get_events():
    """Return recent events from events.jsonl (newest first, up to ?limit= entries)."""
    limit = min(int(request.args.get("limit", 200)), 1000)
    if not EVENTS_FILE.exists():
        return jsonify([])
    events = []
    with _events_lock:
        with EVENTS_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return jsonify(events[-limit:][::-1])  # newest first


@app.get("/api/memory/logs")
def list_log_dates():
    """Return sorted list of dates (desc) that have a physical-log file."""
    mem_dir = _config.get("openclaw_memory_dir", "")
    if not mem_dir:
        return jsonify([])
    logs_dir = Path(mem_dir).expanduser() / "physical-logs"
    if not logs_dir.exists():
        return jsonify([])
    dates = sorted([f.stem for f in logs_dir.glob("*.md")], reverse=True)
    return jsonify(dates)


@app.get("/api/memory/logs/<date>")
def get_log_file(date: str):
    """Return raw markdown content for a given date (YYYY-MM-DD)."""
    if not _re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        return "invalid date", 400
    mem_dir = _config.get("openclaw_memory_dir", "")
    if not mem_dir:
        return "openclaw_memory_dir not configured", 404
    log_file = Path(mem_dir).expanduser() / "physical-logs" / f"{date}.md"
    if not log_file.exists():
        return "not found", 404
    return log_file.read_text(encoding="utf-8"), 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.get("/api/memory/insights")
def list_insight_dates():
    """Return sorted list of dates (desc) that have a physical-insight file."""
    mem_dir = _config.get("openclaw_memory_dir", "")
    if not mem_dir:
        return jsonify([])
    insights_dir = Path(mem_dir).expanduser() / "physical-insights"
    if not insights_dir.exists():
        return jsonify([])
    dates = sorted([f.stem for f in insights_dir.glob("*.md")], reverse=True)
    return jsonify(dates)


@app.get("/api/memory/insights/<date>")
def get_insight_file(date: str):
    """Return raw markdown content for a given date's insight file."""
    if not _re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        return "invalid date", 400
    mem_dir = _config.get("openclaw_memory_dir", "")
    if not mem_dir:
        return "openclaw_memory_dir not configured", 404
    insight_file = Path(mem_dir).expanduser() / "physical-insights" / f"{date}.md"
    if not insight_file.exists():
        return "not found", 404
    return insight_file.read_text(encoding="utf-8"), 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.get("/api/memory/pattern")
def get_pattern_file():
    """Return raw markdown content of physical-pattern.md."""
    mem_dir = _config.get("openclaw_memory_dir", "")
    if not mem_dir:
        return "openclaw_memory_dir not configured", 404
    pattern_file = Path(mem_dir).expanduser() / "physical-pattern.md"
    if not pattern_file.exists():
        return "not found", 404
    return pattern_file.read_text(encoding="utf-8"), 200, {"Content-Type": "text/plain; charset=utf-8"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not _config.get("api_key"):
        log.warning("API key not set — configure via monitor at http://localhost:%d", PORT)
    log.info("Starting on port %d  provider=%s  model=%s",
             PORT, _config["provider"], _config["model"])
    Path(_config["frames_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    threading.Thread(target=_nightly_scheduler, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False)
