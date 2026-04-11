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

import os, sys, json, base64, logging, uuid, time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import threading
import urllib.request as _urllib_req
import urllib.error   as _urllib_err

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
EVENTS_FILE           = Path(os.environ.get("EVENTS_FILE",  "~/.spaceselflog/events.jsonl")).expanduser()
PENDING_COMMENTS_FILE = Path(os.environ.get("PENDING_COMMENTS_FILE", "~/.spaceselflog/pending_comments.jsonl")).expanduser()
ITERATION_LOG_FILE    = Path(os.environ.get("ITERATION_LOG_FILE", "~/.spaceselflog/iteration_log.jsonl")).expanduser()
JOURNAL_FILE          = Path(os.environ.get("JOURNAL_FILE", "~/.spaceselflog/journal.jsonl")).expanduser()
TRANSCRIPTS_DIR       = Path(os.environ.get("TRANSCRIPTS_DIR", "~/.spaceselflog/transcripts")).expanduser()
OPENCLAW_SESSIONS_DIR = Path(os.environ.get("OPENCLAW_SESSIONS_DIR", "~/.openclaw/agents/main/sessions")).expanduser()
# Support multiple session keys (comma-separated)
OPENCLAW_SESSION_KEYS = os.environ.get("OPENCLAW_SESSION_KEYS", "agent:main:telegram:group:-5158989830,agent:main:main").split(",")
# Cron job labels to include in transcript (comma-separated, matched against sessions.json "label" field)
OPENCLAW_CRON_LABELS  = [l.strip() for l in os.environ.get("OPENCLAW_CRON_LABELS", "Cron: Physical Insight Check").split(",") if l.strip()]
HOOK_CONFIG_FILE      = Path(os.environ.get("HOOK_CONFIG_FILE", "~/.spaceselflog/hook-config.json")).expanduser()
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

_INCREMENTAL_INSIGHT_PROMPT = """\
You are adding to today's physical-world summary for a personal AI agent.
This summary is the agent's only window into the physical world, so
anything that could inform a helpful action should be captured.

Inputs:
1. Today's existing summary (current state + highlights — for context and deduplication)
2. New perception logs since the last update

Respond using exactly these two markdown sections and nothing else:

## Current State
<2-3 sentences: what the user is doing right now, where, with whom, and in what mode>

## New Highlights
- <highlight text>
- <highlight text>

Guidelines:
- New Highlights: only items from the new logs not already covered by
  existing highlights. Write (none) if nothing new is worth noting.
- For each candidate, ask: could the agent use this to answer a question
  better, make a timely suggestion, or anticipate an upcoming need?
  If not, omit.
- Each item should be specific to today — a behavior, schedule deviation,
  object, or event that suggests a need or preference.
- Write for the agent, not for a diary.
- No patterns or habits — those belong in the pattern file.
- Do not describe what is on screen unless it reveals a habit, preference, or need.
- Third person.\
"""

_CONSOLIDATION_INSIGHT_PROMPT = """\
You are consolidating today's accumulated physical-world highlights for
a personal AI agent. This summary is the agent's only window into the
physical world — err toward keeping an item rather than dropping it.

Input: the full accumulated "Today's Highlights" bullet list.
Output: only the consolidated bullet list — no header, no preamble,
no current state.

Merge rules:
- Combine items that describe the same activity or theme across different
  times into one entry that preserves key specifics.
- Drop an item only when a later entry clearly contradicts or supersedes
  it — not simply because it is from earlier in the day.
- For each surviving item, ask: could the agent use this to help the
  user today or tomorrow? If not, drop it.

Guidelines:
- Write for the agent, not for a diary.
- Typical days produce 3-8 items after consolidation; fewer is fine.
- No patterns or habits — those belong in the pattern file.
- Third person.\
"""

_DEFAULT_TIMELINE_PROMPT = """\
You are reconstructing a structured daily timeline from a series of \
"current state" snapshots captured throughout the day. Each snapshot \
has a timestamp and a brief description of what the user was doing.

Input: the full states file for a given date (markdown with ## HH:MM \
headers and body text).

Output: a single JSON object with this schema (and nothing else):
{
  "date": "YYYY-MM-DD",
  "segments": [
    {
      "start_time": "HH:MM",
      "end_time": "HH:MM",
      "activity": "<short label>",
      "location": "<where>",
      "social": "<alone / with others / ...>",
      "summary": "<1-2 sentence description>"
    }
  ],
  "day_summary": "<2-3 sentence overview of how the day went>"
}

Rules:
- Merge consecutive states that describe the same activity into one \
segment.
- Set end_time to the timestamp of the next segment's start (or the \
last known state time for the final segment).
- If there is a gap between states (e.g. no data 12:00–14:00), \
create a gap segment with activity "unknown" rather than merging \
across it.
- Keep the JSON compact. No markdown fences.\
"""

# Keep old name as alias so any saved config value in insight_prompt still works
_INSIGHT_PROMPT = _INCREMENTAL_INSIGHT_PROMPT

_INSIGHT_MIN_BATCHES    = 5
_INSIGHT_MIN_MINUTES    = 30
_CONSOLIDATION_EVERY_N  = 4

_DEFAULTS: dict = {
    "provider":            "openrouter",
    "api_key":             os.environ.get("OPENROUTER_API_KEY")
                           or os.environ.get("ANTHROPIC_API_KEY", ""),
    "model":               os.environ.get("VLM_MODEL", "anthropic/claude-sonnet-4-6"),
    "text_provider":       os.environ.get("TEXT_PROVIDER", ""),
    "text_api_key":        os.environ.get("TEXT_API_KEY", ""),
    "text_model":          os.environ.get("TEXT_MODEL", ""),
    "openclaw_memory_dir": os.environ.get("OPENCLAW_MEMORY_DIR", ""),
    "project_dir":         os.environ.get("PROJECT_DIR", ""),
    "frames_dir":          os.environ.get("FRAMES_DIR",
                               str(Path("~/.spaceselflog/frames").expanduser())),
    "prompt":               _DEFAULT_PROMPT,
    "incremental_prompt":   _INCREMENTAL_INSIGHT_PROMPT,
    "consolidation_prompt": _CONSOLIDATION_INSIGHT_PROMPT,
    "pattern_prompt":       _DEFAULT_PATTERN_PROMPT,
    "timeline_prompt":      _DEFAULT_TIMELINE_PROMPT,
    "nightly_hour":         2,
    "insight_min_batches":  _INSIGHT_MIN_BATCHES,
    "insight_min_minutes":  _INSIGHT_MIN_MINUTES,
    "consolidation_every_n": _CONSOLIDATION_EVERY_N,
    "telegram_bot_token":  os.environ.get("TELEGRAM_BOT_TOKEN", ""),
    "telegram_chat_id":    os.environ.get("TELEGRAM_CHAT_ID", ""),
    "telegram_gap_minutes": 30,
    "hook_insight_interval_minutes": 30,
    "email_to":            os.environ.get("ALERT_EMAIL_TO", ""),
    "email_smtp_host":     os.environ.get("ALERT_SMTP_HOST", "smtp.gmail.com"),
    "email_smtp_port":     int(os.environ.get("ALERT_SMTP_PORT", "587")),
    "email_smtp_user":     os.environ.get("ALERT_SMTP_USER", ""),
    "email_smtp_password": os.environ.get("ALERT_SMTP_PASSWORD", ""),
}


def _load_config() -> dict:
    cfg = dict(_DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            saved = json.loads(CONFIG_FILE.read_text())
            # Backward compat: migrate insight_prompt → incremental_prompt
            if "insight_prompt" in saved and "incremental_prompt" not in saved:
                saved["incremental_prompt"] = saved.pop("insight_prompt")
            cfg.update(saved)
        except Exception:
            pass
    return cfg


def _save_config(cfg: dict) -> None:
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    except Exception as e:
        log.error("Failed to write config file %s: %s", CONFIG_FILE, e)
        raise
    # Write hook-config.json so the OpenClaw hook can read settings without touching openclaw.json
    try:
        HOOK_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        HOOK_CONFIG_FILE.write_text(json.dumps({
            "intervalMinutes": cfg.get("hook_insight_interval_minutes", 30),
        }, indent=2))
    except Exception as e:
        log.warning("Failed to write hook-config.json: %s", e)


_config: dict = _load_config()

# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def _make_client(cfg: dict):
    if cfg.get("provider") == "anthropic":
        return anthropic_sdk.Anthropic(api_key=cfg["api_key"])
    return OpenAI(api_key=cfg["api_key"], base_url="https://openrouter.ai/api/v1")


def _text_cfg(cfg: dict) -> dict:
    return {
        "provider": cfg.get("text_provider") or cfg.get("provider"),
        "api_key":  cfg.get("text_api_key") or cfg.get("api_key"),
        "model":    cfg.get("text_model") or cfg.get("model"),
    }


_client = _make_client(_config)
_text_client = _make_client(_text_cfg(_config))

# ---------------------------------------------------------------------------
# Batch history  (in-memory, last 50)
# ---------------------------------------------------------------------------

_batches: deque = deque(maxlen=50)  # each entry: dict

# Heartbeat tracking
_last_heartbeat: float | None = None   # time.time() of last /heartbeat POST
_heartbeat_alerted: bool = False       # True while we are in "offline" alert state


def _record_batch(entry: dict) -> None:
    _batches.appendleft(entry)   # newest first


# ---------------------------------------------------------------------------
# Rolling insight state
# ---------------------------------------------------------------------------

_insight_lock         = threading.Lock()
_insight_batch_count  = 0               # batches since last insight update
_insight_last_time: datetime | None = None   # UTC time of last insight update
_insight_log_offset: dict[str, int] = {}     # date_str -> byte offset already incorporated
_insight_runs_today: dict[str, int]       = {}  # date_str -> incremental run count
_consolidation_runs_today: dict[str, int] = {}  # date_str -> consolidation pass count
_incremental_count: dict[str, int]        = {}  # date_str -> incremental runs since last consolidation


def _restore_insight_state_from_events() -> None:
    """Rebuild in-memory insight counters from events.jsonl on startup."""
    global _insight_batch_count, _insight_last_time, _pattern_last_run_date
    if not EVENTS_FILE.exists():
        return

    # Parse all events once
    events: list[dict] = []
    try:
        with EVENTS_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts_str = ev.get("ts", "")
                try:
                    ev["_ts"] = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue
                events.append(ev)
    except Exception as e:
        log.warning("Could not read events for state restore: %s", e)
        return

    today = datetime.now().strftime("%Y-%m-%d")
    every_n = int(_config.get("consolidation_every_n", _CONSOLIDATION_EVERY_N))

    # Pass 1: find today's insight/consolidation/batch events
    last_insight_ts: datetime | None = None
    last_consolidation_ts: datetime | None = None
    today_insight_runs = 0
    today_consolidations = 0
    today_batch_timestamps: list[datetime] = []

    for ev in events:
        ev_type = ev.get("type", "")
        # Use explicit "date" field for insight events (local date),
        # fall back to converting UTC ts to local date
        if "date" in ev:
            ev_local_date = ev["date"]
        else:
            ev_local_date = ev["_ts"].astimezone().strftime("%Y-%m-%d")

        # Pattern: track last run date globally
        if ev_type == "pattern" and ev.get("status") == "ok":
            _pattern_last_run_date = ev.get("date", ev_local_date)

        if ev_local_date != today:
            continue

        ts = ev["_ts"]
        if ev_type == "batch" and ev.get("status") == "ok":
            today_batch_timestamps.append(ts)

        if ev_type == "insight" and ev.get("status") == "ok":
            today_insight_runs += 1
            last_insight_ts = ts

        if ev_type == "insight_consolidation" and ev.get("status") == "ok":
            today_consolidations += 1
            last_consolidation_ts = ts

    # Pass 2: compute batches since last insight
    if last_insight_ts:
        _insight_last_time = last_insight_ts
        _insight_batch_count = sum(
            1 for bts in today_batch_timestamps if bts > last_insight_ts
        )
    else:
        _insight_batch_count = len(today_batch_timestamps)

    # Restore incremental_count: insight runs since last consolidation
    if last_consolidation_ts:
        incremental_since_consolidation = sum(
            1 for ev in events
            if ev.get("type") == "insight"
            and ev.get("status") == "ok"
            and ("date" in ev and ev["date"] == today
                 or "date" not in ev and ev["_ts"].astimezone().strftime("%Y-%m-%d") == today)
            and ev["_ts"] > last_consolidation_ts
        )
    else:
        incremental_since_consolidation = today_insight_runs
    _incremental_count[today] = incremental_since_consolidation

    _insight_runs_today[today] = today_insight_runs
    _consolidation_runs_today[today] = today_consolidations

    # Restore log offsets: point to end of today's physical-log file
    mem_dir = _config.get("openclaw_memory_dir", "")
    if mem_dir:
        log_file = Path(mem_dir).expanduser() / "physical-logs" / f"{today}.md"
        if log_file.exists():
            _insight_log_offset[today] = log_file.stat().st_size

    log.info("Restored insight state: batches_since=%d  last_insight=%s  runs_today=%d  incremental_since=%d  consolidations=%d  pattern_last=%s",
             _insight_batch_count,
             _insight_last_time.isoformat() if _insight_last_time else "never",
             today_insight_runs,
             incremental_since_consolidation,
             today_consolidations,
             _pattern_last_run_date or "never")


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder=str(Path(__file__).parent))

import importlib.util as _ilu, sys as _sys
_slides_spec = _ilu.spec_from_file_location("slides_routes", Path(__file__).parent.parent / "visualization" / "slides_routes.py")
_slides_mod  = _ilu.module_from_spec(_slides_spec); _slides_spec.loader.exec_module(_slides_mod)
app.register_blueprint(_slides_mod.bp, url_prefix="/slides")


@app.get("/")
def monitor():
    return send_file(Path(__file__).parent / "monitor.html")


@app.get("/status")
def status():
    cfg = _config
    now = time.time()
    hb_age = round(now - _last_heartbeat) if _last_heartbeat else None
    return jsonify({
        "ok":                  True,
        "provider":            cfg.get("provider"),
        "model":               cfg.get("model"),
        "openclaw_memory_dir": cfg.get("openclaw_memory_dir"),
        "frames_dir":          cfg.get("frames_dir"),
        "batches_received":    len(_batches),
        "heartbeat_age":       hb_age,   # seconds since last heartbeat, or null
        "heartbeat_alerted":   _heartbeat_alerted,
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
    t_key = safe.get("text_api_key", "")
    safe["text_api_key_masked"] = ("•" * max(0, len(t_key) - 6) + t_key[-6:]) if t_key else ""
    # Return effective prompt values so the UI reflects what will actually be used.
    safe["prompt"]               = safe.get("prompt")               or _DEFAULT_PROMPT
    safe["incremental_prompt"]   = safe.get("incremental_prompt")   or _INCREMENTAL_INSIGHT_PROMPT
    safe["consolidation_prompt"] = safe.get("consolidation_prompt") or _CONSOLIDATION_INSIGHT_PROMPT
    safe["pattern_prompt"]       = safe.get("pattern_prompt")       or _DEFAULT_PATTERN_PROMPT
    safe["timeline_prompt"]      = safe.get("timeline_prompt")      or _DEFAULT_TIMELINE_PROMPT
    safe["config_file"]          = str(CONFIG_FILE)
    return jsonify(safe)


@app.post("/api/config")
def post_config():
    global _config, _client, _text_client
    body = request.get_json(force=True, silent=True) or {}
    # Merge into current config; ignore unknown keys
    allowed = {"provider", "api_key", "model", 
               "text_provider", "text_api_key", "text_model",
               "openclaw_memory_dir", "project_dir", "frames_dir",
               "prompt", "incremental_prompt", "consolidation_prompt", "pattern_prompt", "timeline_prompt",
               "nightly_hour", "insight_min_batches", "insight_min_minutes", "consolidation_every_n",
               "telegram_bot_token", "telegram_chat_id", "telegram_gap_minutes",
               "hook_insight_interval_minutes",
               "email_to", "email_smtp_host", "email_smtp_port",
               "email_smtp_user", "email_smtp_password"}
    for k in allowed:
        if k in body:
            _config[k] = body[k]
    try:
        _save_config(_config)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    _client = _make_client(_config)
    _text_client = _make_client(_text_cfg(_config))
    log.info("Config updated: provider=%s model=%s, text_provider=%s text_model=%s",
             _config["provider"], _config["model"],
             _text_cfg(_config)["provider"], _text_cfg(_config)["model"])
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Test API
# ---------------------------------------------------------------------------

@app.post("/api/test-email")
def test_email():
    cfg = _config
    if not cfg.get("email_to") or not cfg.get("email_smtp_host") or not cfg.get("email_smtp_user"):
        return jsonify({"ok": False, "error": "Email not configured"}), 400
    try:
        _send_alert_email(
            subject="[SpaceSelfLog] Test email",
            body="This is a test notification from SpaceSelfLog.",
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


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
# Heartbeat
# ---------------------------------------------------------------------------

@app.post("/heartbeat")
def heartbeat():
    global _last_heartbeat, _heartbeat_alerted
    _last_heartbeat = time.time()
    if _heartbeat_alerted:
        _heartbeat_alerted = False
        log.info("Heartbeat resumed — app is back online")
    return jsonify({"ok": True})


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
    vlm_ms: int | None = None
    vlm_model: str = _config.get("model", "")
    try:
        _t0 = time.monotonic()
        summary = _run_vlm(
            frames=frame_paths,
            frames_meta=frames_meta,
            batch_created=batch_created,
            input_frames=input_frames,
            prior_summary=prior_summary,
        )
        vlm_ms = int((time.monotonic() - _t0) * 1000)
        _save_prior_context(session_id, summary)
        log.info("VLM ok — %d chars  model=%s  %.1fs", len(summary), vlm_model, vlm_ms / 1000)
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
        "vlm_model":   vlm_model,
        "vlm_ms":      vlm_ms,
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


@app.delete("/api/batches/<batch_id>")
def delete_batch(batch_id: str):
    for i, b in enumerate(_batches):
        if b["batch_id"] == batch_id:
            del _batches[i]
            return jsonify({"ok": True})
    return jsonify({"error": "batch not found"}), 404


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
            log.warning("JSON validation failed (attempt %d/%d): %s — raw[:200]=%r",
                        attempt, max_retries, e, cleaned[:200])

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
    raw = (r.choices[0].message.content or "").strip()
    if not raw:
        raise ValueError("VLM returned empty response (possible rate limit or content filter)")
    return raw


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
    raw = (r.content[0].text or "").strip()
    if not raw:
        raise ValueError("VLM returned empty response (possible rate limit or content filter)")
    return raw


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


def _build_log_entry(batch_id, session_id, batch_created, summary,
                     frame_count, input_frames) -> tuple[str, str, str]:
    """Return (date_str, time_str, entry_text) for a physical log entry."""
    local_created = batch_created.astimezone()
    date_str = local_created.strftime("%Y-%m-%d")
    time_str = local_created.strftime("%H:%M")

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

    return date_str, time_str, entry


def _write_physical_log(batch_id, session_id, batch_created,
                        summary, frame_count, input_frames,
                        insert_sorted: bool = False) -> None:
    mem_dir = _config.get("openclaw_memory_dir", "")
    if not mem_dir:
        log.warning("openclaw_memory_dir not set — skipping memory write")
        return

    logs_dir = Path(mem_dir).expanduser() / "physical-logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    date_str, time_str, entry = _build_log_entry(
        batch_id, session_id, batch_created, summary, frame_count, input_frames)
    log_file = logs_dir / f"{date_str}.md"

    if not log_file.exists():
        log_file.write_text(f"# Physical Log — {date_str}\n")

    if not insert_sorted:
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(entry)
    else:
        # Insert entry in chronological order by HH:MM header.
        # Find the first existing section whose time is strictly after ours and
        # splice before it; if none, append.
        text = log_file.read_text(encoding="utf-8")
        # Match positions of every "## HH:MM" section header
        pattern = _re.compile(r'\n(?=## \d{2}:\d{2})')
        splits = [(m.start(), text[m.start():].split('\n')[1][3:8]) for m in pattern.finditer(text)]
        insert_pos = None
        for pos, hdr_time in splits:
            if hdr_time > time_str:
                insert_pos = pos
                break
        if insert_pos is None:
            with log_file.open("a", encoding="utf-8") as fh:
                fh.write(entry)
        else:
            new_text = text[:insert_pos] + entry + text[insert_pos:]
            log_file.write_text(new_text, encoding="utf-8")
        log.info("Memory write (sorted insert at %s) → %s", time_str, log_file)
        return

    log.info("Memory write → %s", log_file)


# ---------------------------------------------------------------------------
# Rolling insight: physical-insights/YYYY-MM-DD.md
# ---------------------------------------------------------------------------

def _find_section(sections: dict[str, str], keyword: str) -> tuple[str | None, str]:
    """Return (key, body) for the first section whose header contains keyword (case-insensitive).
    Returns (None, '') if not found."""
    key = next((k for k in sections if keyword in k.lower()), None)
    if key is None:
        return None, ""
    return key, sections[key].strip()


def _split_insight_sections(text: str) -> dict[str, str]:
    """Parse markdown sections from an insight file. Returns {header_text: body_text}.
    Comment lines (<!-- ... -->) are stripped before parsing."""
    lines = [l for l in text.splitlines() if not l.startswith("<!--")]
    text = "\n".join(lines).strip()

    sections: dict[str, str] = {}
    current_header: str | None = None
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            if current_header is not None:
                sections[current_header] = "\n".join(current_lines).strip()
            current_header = line[3:].strip()
            current_lines = []
        else:
            if current_header is not None:
                current_lines.append(line)

    if current_header is not None:
        sections[current_header] = "\n".join(current_lines).strip()

    return sections


_FATAL_TEXT_ERROR_PATTERNS = (
    "invalid api key", "incorrect api key", "authentication",
    "model not found", "does not exist", "invalid model",
    "no such model", "unknown model",
)


def _is_fatal_text_error(e: Exception) -> bool:
    msg = str(e).lower()
    code = getattr(e, "status_code", None) or getattr(e, "code", None)
    if code in (401, 403):
        return True
    return any(p in msg for p in _FATAL_TEXT_ERROR_PATTERNS)


def _call_vlm_as_text(system_prompt: str, user_msg: str, max_tokens: int) -> str:
    """Call the vision-model client for text-only inference (fallback path)."""
    if _config.get("provider") == "anthropic":
        r = _client.messages.create(
            model=_config["model"], max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        return (r.content[0].text or "").strip()
    r = _client.chat.completions.create(
        model=_config["model"], max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_msg},
        ],
    )
    return (r.choices[0].message.content or "").strip()


def _call_insight_vlm(system_prompt: str, user_msg: str, max_tokens: int = 1024) -> str:
    """Call the configured text LLM with retries.

    Error handling:
    - Fatal errors (invalid model / API key): email alert immediately, raise.
    - Transient errors: retry up to 3 times, then fall back to vision model.
    - Vision model also fails all retries: email alert, raise.
    """
    t_cfg = _text_cfg(_config)
    last_exc: Exception | None = None

    # --- text model (up to 3 attempts) ---
    for attempt in range(3):
        try:
            if t_cfg.get("provider") == "anthropic":
                r = _text_client.messages.create(
                    model=t_cfg["model"], max_tokens=max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_msg}],
                )
                return (r.content[0].text or "").strip()
            r = _text_client.chat.completions.create(
                model=t_cfg["model"], max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_msg},
                ],
            )
            return (r.choices[0].message.content or "").strip()
        except Exception as e:
            last_exc = e
            if _is_fatal_text_error(e):
                log.error("Text model fatal error (model/API invalid): %s", e)
                _send_alert_email(
                    "SpaceSelfLog: text model fatal error",
                    f"Text model failed with a fatal error (invalid model or API key).\n\n"
                    f"Model: {t_cfg.get('model')}\nError: {e}",
                )
                raise
            log.warning("Text model failed (attempt %d/3): %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(5 * (attempt + 1))

    # --- vision model fallback (up to 3 attempts) ---
    log.warning("Text model exhausted retries, falling back to vision model. Last error: %s", last_exc)
    for attempt in range(3):
        try:
            result = _call_vlm_as_text(system_prompt, user_msg, max_tokens)
            log.info("Vision model fallback succeeded (attempt %d/3)", attempt + 1)
            return result
        except Exception as e:
            last_exc = e
            log.warning("Vision model fallback failed (attempt %d/3): %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(5 * (attempt + 1))

    # --- both exhausted ---
    log.error("Text model and vision model fallback both failed: %s", last_exc)
    _send_alert_email(
        "SpaceSelfLog: text model + vision fallback both failed",
        f"Text model failed after 3 retries, then vision model fallback also failed after 3 retries.\n\n"
        f"Text model: {t_cfg.get('model')}\nVision model: {_config.get('model')}\nLast error: {last_exc}",
    )
    raise last_exc


def _maybe_update_today_insight(date_str: str) -> None:
    """Increment batch counter; trigger incremental update if conditions are met.
    After every consolidation_every_n incremental updates, run a consolidation pass."""
    global _insight_batch_count, _insight_last_time, _insight_runs_today, _incremental_count
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
        _incremental_count[date_str]  = _incremental_count.get(date_str, 0) + 1
        every_n = int(_config.get("consolidation_every_n", _CONSOLIDATION_EVERY_N))
        run_consolidation = (_incremental_count[date_str] >= every_n)
        if run_consolidation:
            _incremental_count[date_str] = 0

    # Run outside the lock — these are slow LLM calls
    try:
        _run_incremental_update(date_str)
        _append_event("insight", status="ok", date=date_str,
                      run=_insight_runs_today.get(date_str, 1))
    except Exception as e:
        log.error("Insight incremental update error: %s", e)
        _append_event("insight", status="error", date=date_str, error=str(e))
        return  # Don't consolidate if incremental failed

    if run_consolidation:
        try:
            _run_consolidation_pass(date_str)
        except Exception as e:
            log.error("Insight consolidation error: %s", e)
            _append_event("insight_consolidation", status="error", date=date_str, error=str(e))


def _run_incremental_update(date_str: str) -> None:
    """Read new log entries, generate new highlights + updated Current State, append to insight file."""
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

    existing_text = ""
    if insight_file.exists():
        existing_text = insight_file.read_text(encoding="utf-8")

    # Parse existing sections to extract accumulated highlights
    existing_sections = _split_insight_sections(existing_text)
    existing_highlights_key, existing_highlights_body = _find_section(existing_sections, "highlight")

    # Strip comment lines for context passed to VLM
    existing_insight_clean = "\n".join(
        l for l in existing_text.splitlines() if not l.startswith("<!--")
    ).strip()

    # Read and consume pending human comments
    pending_comments = []
    with _comments_lock:
        if PENDING_COMMENTS_FILE.exists():
            for line in PENDING_COMMENTS_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        pending_comments.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            if pending_comments:
                PENDING_COMMENTS_FILE.write_text("", encoding="utf-8")  # clear

    if existing_insight_clean:
        user_msg = (
            f"Today's existing summary for {date_str}:\n\n{existing_insight_clean}\n\n"
            f"---\nNew perception logs to process:\n\n{new_logs}"
        )
    else:
        user_msg = f"New perception logs for {date_str}:\n\n{new_logs}"

    if pending_comments:
        annotations = "\n\n".join(
            f"- [{c['ts']}] {c['comment']}"
            + (f"\n  (context: {c['batch_summary'][:150]})" if c.get('batch_summary') else "")
            for c in pending_comments
        )
        user_msg += f"\n\n---\nHuman annotations (prioritize incorporating these):\n\n{annotations}"
        log.info("Insight: including %d human comment(s)", len(pending_comments))

    incremental_system = _config.get("incremental_prompt") or _INCREMENTAL_INSIGHT_PROMPT

    def _parse_incremental_markdown(raw: str) -> tuple[str, str] | None:
        """Parse VLM markdown response into (current_state_body, new_highlights_body).
        Returns None if either section is missing."""
        sections = _split_insight_sections(raw)
        state_key,      state_body      = _find_section(sections, "current")
        highlights_key, highlights_body = _find_section(sections, "highlight")
        if state_key is None or highlights_key is None:
            return None
        return state_body, highlights_body

    # Retry once on section-parse failure
    parsed = None
    for attempt in range(2):
        raw = _call_insight_vlm(incremental_system, user_msg)
        parsed = _parse_incremental_markdown(raw)
        if parsed is not None:
            break
        if attempt == 0:
            log.warning("Insight incremental: section parse failed, retrying")
        else:
            log.error("Insight incremental: section parse failed after retry — skipping")
            return

    new_state_body, new_highlights_text = parsed

    # Code-append: preserve existing highlights, add new ones below
    merged_parts = [existing_highlights_body] if existing_highlights_body.strip() else []
    if new_highlights_text:
        merged_parts.append(new_highlights_text)
    merged_highlights = "\n".join(merged_parts)

    # Programmatic timestamp for Current State header
    time_str = datetime.now().strftime("%H:%M")

    # Write insight file
    runs = _insight_runs_today.get(date_str, 1)
    now_utc = datetime.now(timezone.utc).strftime("%H:%M UTC")
    header = f"<!-- auto-generated by SpaceSelfLog — update #{runs} — last updated {now_utc} -->"

    content_parts = [header, ""]
    if new_state_body:
        content_parts.append(f"## Current State (as of {time_str})\n{new_state_body}")
        content_parts.append("")
    if merged_highlights:
        content_parts.append(f"## Today's Highlights\n{merged_highlights}")
        content_parts.append("")

    insight_file.write_text("\n".join(content_parts), encoding="utf-8")
    _insight_log_offset[date_str] = new_offset
    log.info("Insight (incremental) → %s  (offset %d→%d)", insight_file, offset, new_offset)

    # Insert current state snapshot into daily narrative states file (sorted)
    if new_state_body:
        narrative_dir = Path(mem_dir).expanduser() / "physical-daily-narrative"
        narrative_dir.mkdir(parents=True, exist_ok=True)
        states_file = narrative_dir / f"{date_str}-states.md"
        if not states_file.exists():
            states_file.write_text(f"# Daily States — {date_str}\n", encoding="utf-8")
        _insert_state_sorted(states_file, time_str, f"\n## {time_str}\n{new_state_body}\n")
        log.info("Narrative state inserted → %s", states_file)


def _run_consolidation_pass(date_str: str) -> None:
    """Consolidate accumulated highlights: merge duplicates, remove superseded items.
    Current State section is preserved unchanged."""
    mem_dir = _config.get("openclaw_memory_dir", "")
    if not mem_dir:
        return

    insight_file = Path(mem_dir).expanduser() / "physical-insights" / f"{date_str}.md"
    if not insight_file.exists():
        return

    existing_text = insight_file.read_text(encoding="utf-8")
    existing_sections = _split_insight_sections(existing_text)

    highlights_key, existing_highlights = _find_section(existing_sections, "highlight")
    if not existing_highlights:
        return  # Nothing to consolidate

    # Preserve Current State section verbatim
    state_key, state_body = _find_section(existing_sections, "current")
    state_header = f"## {state_key}" if state_key else None

    user_msg = f"Today's accumulated highlights for {date_str}:\n\n{existing_highlights}"
    consolidation_system = _config.get("consolidation_prompt") or _CONSOLIDATION_INSIGHT_PROMPT
    consolidated_highlights = _call_insight_vlm(consolidation_system, user_msg).strip()

    runs = _insight_runs_today.get(date_str, 0)
    now_utc = datetime.now(timezone.utc).strftime("%H:%M UTC")
    header = f"<!-- auto-generated by SpaceSelfLog — update #{runs} (consolidated) — last updated {now_utc} -->"

    content_parts = [header, ""]
    if state_header and state_body:
        content_parts.append(f"{state_header}\n{state_body}")
        content_parts.append("")
    content_parts.append(f"## Today's Highlights\n{consolidated_highlights}")
    content_parts.append("")

    insight_file.write_text("\n".join(content_parts), encoding="utf-8")
    _consolidation_runs_today[date_str] = _consolidation_runs_today.get(date_str, 0) + 1
    log.info("Insight (consolidation) → %s  (pass #%d today)",
             insight_file, _consolidation_runs_today[date_str])
    _append_event("insight_consolidation", status="ok", date=date_str,
                  pass_num=_consolidation_runs_today[date_str])


# ---------------------------------------------------------------------------
# Daily timeline generation
# ---------------------------------------------------------------------------

def _generate_daily_timeline(date_str: str) -> None:
    """Read the states file for a date and generate a structured timeline JSON."""
    mem_dir = _config.get("openclaw_memory_dir", "")
    if not mem_dir:
        log.warning("Timeline generation: openclaw_memory_dir not set — skipping")
        return

    narrative_dir = Path(mem_dir).expanduser() / "physical-daily-narrative"
    states_file = narrative_dir / f"{date_str}-states.md"
    if not states_file.exists():
        log.info("Timeline generation: no states file for %s — skipping", date_str)
        return

    states_text = states_file.read_text(encoding="utf-8").strip()
    # Strip HTML comments
    states_clean = "\n".join(
        line for line in states_text.splitlines() if not line.startswith("<!--")
    ).strip()
    if not states_clean:
        return

    timeline_system = _config.get("timeline_prompt") or _DEFAULT_TIMELINE_PROMPT
    user_msg = f"States file for {date_str}:\n\n{states_clean}"

    try:
        raw = _call_insight_vlm(timeline_system, user_msg, max_tokens=2048)
        cleaned = _strip_json_fences(raw)
        # Validate it's valid JSON
        json.loads(cleaned)

        timeline_file = narrative_dir / f"{date_str}-timeline.md"
        timeline_file.write_text(
            f"<!-- auto-generated by SpaceSelfLog — {date_str} -->\n\n"
            + cleaned + "\n",
            encoding="utf-8",
        )
        log.info("Timeline generated → %s", timeline_file)
        _append_event("timeline", status="ok", date=date_str)
    except Exception as e:
        log.error("Timeline generation failed for %s: %s", date_str, e)
        _append_event("timeline", status="error", date=date_str, error=str(e))


# ---------------------------------------------------------------------------
# Nightly pattern update: physical-pattern.md
# ---------------------------------------------------------------------------

_pattern_last_run_date: str | None = None   # local date string of last successful run


def _run_nightly_pattern_update(date_str: str, extra_date_str: str | None = None) -> None:
    """Merge one or two days' insights into physical-pattern.md.

    date_str is always the primary date (yesterday when triggered after midnight).
    extra_date_str is an optional second date (today) to include when the trigger
    fires after midnight and today already has some logged activity.

    Flow:
      0. Generate timeline from states for primary date
      1. Read insight + states + timeline for primary date
      2. Optionally read insight + states + timeline for extra date
      3. Read existing physical-pattern.md
      4. Call LLM with all gathered context
      5. Overwrite physical-pattern.md
    """
    global _pattern_last_run_date

    mem_dir = _config.get("openclaw_memory_dir", "")
    if not mem_dir:
        log.warning("Nightly pattern: openclaw_memory_dir not set — skipping")
        return

    base_dir     = Path(mem_dir).expanduser()
    insights_dir = base_dir / "physical-insights"
    narrative_dir = base_dir / "physical-daily-narrative"

    # Step 0: Generate timeline from states for primary date
    _generate_daily_timeline(date_str)

    # Step 1: Read insight + states + timeline for primary date
    insight_file = insights_dir / f"{date_str}.md"
    if not insight_file.exists():
        log.warning("Nightly pattern: no insight file for %s — skipping", date_str)
        return

    combined_parts: list[str] = []

    insight_text = insight_file.read_text(encoding="utf-8").strip()
    if insight_text:
        combined_parts.append(f"### Daily Insight ({date_str})\n{insight_text}")

    states_file = narrative_dir / f"{date_str}-states.md"
    if states_file.exists():
        states_text = states_file.read_text(encoding="utf-8").strip()
        states_clean = "\n".join(
            line for line in states_text.splitlines() if not line.startswith("<!--")
        ).strip()
        if states_clean:
            combined_parts.append(f"### Daily States ({date_str})\n{states_clean}")

    timeline_file = narrative_dir / f"{date_str}-timeline.md"
    if timeline_file.exists():
        timeline_text = timeline_file.read_text(encoding="utf-8").strip()
        timeline_clean = "\n".join(
            line for line in timeline_text.splitlines() if not line.startswith("<!--")
        ).strip()
        if timeline_clean:
            combined_parts.append(f"### Daily Timeline ({date_str})\n{timeline_clean}")

    # Step 2: Optionally read insight + states + timeline for extra date
    if extra_date_str:
        _generate_daily_timeline(extra_date_str)

        extra_insight = insights_dir / f"{extra_date_str}.md"
        if extra_insight.exists():
            extra_text = extra_insight.read_text(encoding="utf-8").strip()
            if extra_text:
                combined_parts.append(f"### Partial Insight ({extra_date_str})\n{extra_text}")

        extra_states = narrative_dir / f"{extra_date_str}-states.md"
        if extra_states.exists():
            extra_states_text = extra_states.read_text(encoding="utf-8").strip()
            extra_states_clean = "\n".join(
                line for line in extra_states_text.splitlines() if not line.startswith("<!--")
            ).strip()
            if extra_states_clean:
                combined_parts.append(f"### Partial States ({extra_date_str})\n{extra_states_clean}")

        extra_timeline = narrative_dir / f"{extra_date_str}-timeline.md"
        if extra_timeline.exists():
            extra_tl_text = extra_timeline.read_text(encoding="utf-8").strip()
            extra_tl_clean = "\n".join(
                line for line in extra_tl_text.splitlines() if not line.startswith("<!--")
            ).strip()
            if extra_tl_clean:
                combined_parts.append(f"### Partial Timeline ({extra_date_str})\n{extra_tl_clean}")

    combined_input = "\n\n---\n\n".join(combined_parts)
    if not combined_input:
        return

    # Step 3: Read existing pattern
    pattern_file = base_dir / "physical-pattern.md"
    existing_pattern = ""
    if pattern_file.exists():
        text = pattern_file.read_text(encoding="utf-8")
        existing_pattern = "\n".join(
            line for line in text.splitlines() if not line.startswith("<!--")
        ).strip()

    # Step 4: Call LLM
    dates_label = f"{date_str}" + (f" + {extra_date_str}" if extra_date_str else "")
    if existing_pattern:
        user_msg = (
            f"Current profile:\n\n{existing_pattern}\n\n"
            f"---\nNew daily data ({dates_label}) to merge in:\n\n{combined_input}"
        )
    else:
        user_msg = f"Daily data ({dates_label}) — no existing profile yet:\n\n{combined_input}"

    pattern_system = _config.get("pattern_prompt") or _DEFAULT_PATTERN_PROMPT

    # Step 5: Write result
    try:
        updated = _call_insight_vlm(pattern_system, user_msg, max_tokens=2048)

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


HEARTBEAT_TIMEOUT = 180   # seconds without a heartbeat before alerting
HEARTBEAT_RECHECK = 60    # how often the monitor thread wakes up (seconds)


def _send_alert_email(subject: str, body: str) -> None:
    """Send an alert email using the configured SMTP settings. Silently skips if not configured."""
    import smtplib
    from email.message import EmailMessage
    cfg = _config
    to   = cfg.get("email_to", "").strip()
    host = cfg.get("email_smtp_host", "").strip()
    user = cfg.get("email_smtp_user", "").strip()
    pwd  = cfg.get("email_smtp_password", "").strip()
    port = int(cfg.get("email_smtp_port", 587))
    if not (to and host and user and pwd):
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"]    = user
        msg["To"]      = to
        msg.set_content(body)
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.ehlo()
            s.starttls()
            s.login(user, pwd)
            s.send_message(msg)
        log.info("Alert email sent to %s", to)
    except Exception as e:
        log.warning("Failed to send alert email: %s", e)


def _heartbeat_monitor() -> None:
    """Background thread: notify via macOS notification + email if app goes silent."""
    import time as _time, subprocess as _subprocess
    while True:
        _time.sleep(HEARTBEAT_RECHECK)
        global _heartbeat_alerted
        if _last_heartbeat is None:
            continue   # no heartbeat ever received — nothing to alert on
        age = _time.time() - _last_heartbeat
        if age > HEARTBEAT_TIMEOUT and not _heartbeat_alerted:
            _heartbeat_alerted = True
            mins = int(age // 60)
            log.warning("No heartbeat for %d min — sending notifications", mins)
            _subprocess.run([
                "osascript", "-e",
                f'display notification "No heartbeat for {mins}+ min — app may have crashed or closed" '
                f'with title "SpaceSelfLog" subtitle "App offline" sound name "Funk"'
            ], check=False)
            _send_alert_email(
                subject="[SpaceSelfLog] App offline",
                body=f"No heartbeat received for {mins}+ minutes.\nThe app may have crashed or been closed.",
            )


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
        runs_today           = _insight_runs_today.get(today, 0)
        consolidations_today = _consolidation_runs_today.get(today, 0)
        incremental_since    = _incremental_count.get(today, 0)
        every_n              = int(_config.get("consolidation_every_n", _CONSOLIDATION_EVERY_N))
        last_run_at = _insight_last_time.isoformat() if _insight_last_time else None
    return jsonify({
        "runs_today":            runs_today,
        "consolidations_today":  consolidations_today,
        "incremental_since":     incremental_since,
        "consolidation_every_n": every_n,
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


_comments_lock = threading.Lock()


@app.post("/api/comment")
def post_comment():
    """Save a human annotation for a batch."""
    body = request.get_json(force=True, silent=True) or {}
    batch_id = (body.get("batch_id") or "").strip()
    comment  = (body.get("comment")  or "").strip()
    if not batch_id or not comment:
        return jsonify({"error": "batch_id and comment required"}), 400

    # Find batch in memory to get summary snippet and update its comment field
    batch_summary = ""
    for b in _batches:
        if b["batch_id"] == batch_id:
            batch_summary = (b.get("summary") or "")[:300]
            b["comment"] = comment
            break

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = {
        "ts":            ts,
        "batch_id":      batch_id,
        "batch_summary": batch_summary,
        "comment":       comment,
    }

    # 1. Append to pending (for next insight run)
    line = json.dumps(entry, ensure_ascii=False)
    try:
        PENDING_COMMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _comments_lock:
            with PENDING_COMMENTS_FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception as e:
        log.error("Failed to write pending comment: %s", e)
        return jsonify({"error": str(e)}), 500

    # 2. Append to permanent archive in memory dir
    mem_dir = _config.get("openclaw_memory_dir", "")
    if mem_dir:
        archive_file = Path(mem_dir).expanduser() / "human-comments.md"
        try:
            archive_file.parent.mkdir(parents=True, exist_ok=True)
            block = (
                f"\n## {ts}\n"
                f"**Batch**: `{batch_id}`\n\n"
                + (f"**Context**: {batch_summary}\n\n" if batch_summary else "")
                + f"**Comment**: {comment}\n\n---"
            )
            with _comments_lock:
                with archive_file.open("a", encoding="utf-8") as f:
                    f.write(block + "\n")
        except Exception as e:
            log.warning("Failed to write comment archive: %s", e)

    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Batch retry
# ---------------------------------------------------------------------------

@app.post("/api/retry/<batch_id>")
def retry_batch(batch_id: str):
    """Re-run VLM on a previously failed batch using saved frames on disk."""
    # Find the batch record in memory
    rec = None
    for b in _batches:
        if b["batch_id"] == batch_id:
            rec = b
            break
    if rec is None:
        return jsonify({"error": "batch not found"}), 404

    session_id = rec["session_id"]
    frames_dir = Path(_config["frames_dir"])
    batch_dir  = frames_dir / session_id / batch_id

    # Load saved frames from disk
    manifest_path = batch_dir / "manifest.json"
    if not manifest_path.exists():
        return jsonify({"error": "manifest not found on disk"}), 404

    try:
        manifest = json.loads(manifest_path.read_text())
    except Exception as e:
        return jsonify({"error": f"failed to read manifest: {e}"}), 500

    frames_meta  = manifest.get("frames_meta", [])
    created_at   = manifest.get("created_at", rec.get("created_at", datetime.now(timezone.utc).isoformat()))
    input_frames = manifest.get("input_frames", rec.get("input_frames", 0))

    # Reload frame files in order
    frame_paths: list[tuple[str, bytes]] = []
    for fn in (rec.get("filenames") or []):
        fpath = batch_dir / fn
        if fpath.exists():
            frame_paths.append((fn, fpath.read_bytes()))
    if not frame_paths:
        return jsonify({"error": "no frame files found on disk"}), 404

    batch_created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    prior_summary = _load_prior_context(session_id)

    vlm_model = _config.get("model", "")
    vlm_ms: int | None = None
    try:
        _t0 = time.monotonic()
        summary = _run_vlm(
            frames=frame_paths,
            frames_meta=frames_meta,
            batch_created=batch_created,
            input_frames=input_frames,
            prior_summary=prior_summary,
        )
        vlm_ms = int((time.monotonic() - _t0) * 1000)
        _save_prior_context(session_id, summary)
        log.info("Retry VLM ok — batch=%s  model=%s  %.1fs", batch_id, vlm_model, vlm_ms / 1000)
    except Exception as e:
        log.error("Retry VLM error: %s", e)
        rec["status"] = "error"
        rec["error"]  = str(e)
        return jsonify({"error": str(e)}), 500

    # Write to physical log, inserting in chronological order
    mem_error = None
    try:
        _write_physical_log(
            batch_id=batch_id, session_id=session_id,
            batch_created=batch_created, summary=summary,
            frame_count=len(frame_paths), input_frames=input_frames,
            insert_sorted=True,
        )
        date_str = batch_created.astimezone().strftime("%Y-%m-%d")
        threading.Thread(
            target=_maybe_update_today_insight,
            args=(date_str,),
            daemon=True,
        ).start()
    except Exception as e:
        mem_error = str(e)
        log.error("Retry memory write error: %s", e)

    # Update record in-place
    rec["summary"]   = summary
    rec["status"]    = "ok"
    rec["error"]     = mem_error
    rec["vlm_model"] = vlm_model
    rec["vlm_ms"]    = vlm_ms

    _append_event("batch", status="ok", batch_id=batch_id,
                  session_id=session_id, frames=len(frame_paths), retried=True)
    return jsonify({**rec})


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
# Daily narrative API
# ---------------------------------------------------------------------------

@app.get("/api/memory/narrative/dates")
def list_narrative_dates():
    """Return sorted list of dates (desc) that have any narrative files."""
    mem_dir = _config.get("openclaw_memory_dir", "")
    if not mem_dir:
        return jsonify([])
    narrative_dir = Path(mem_dir).expanduser() / "physical-daily-narrative"
    if not narrative_dir.exists():
        return jsonify([])
    dates: set[str] = set()
    for f in narrative_dir.glob("*-states.md"):
        dates.add(f.stem.replace("-states", ""))
    for f in narrative_dir.glob("*-timeline.md"):
        dates.add(f.stem.replace("-timeline", ""))
    return jsonify(sorted(dates, reverse=True))


@app.get("/api/memory/narrative/<date>/states")
def get_narrative_states(date: str):
    """Return raw markdown content of daily states file."""
    if not _re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        return "invalid date", 400
    mem_dir = _config.get("openclaw_memory_dir", "")
    if not mem_dir:
        return "openclaw_memory_dir not configured", 404
    states_file = Path(mem_dir).expanduser() / "physical-daily-narrative" / f"{date}-states.md"
    if not states_file.exists():
        return "not found", 404
    return states_file.read_text(encoding="utf-8"), 200, {"Content-Type": "text/plain; charset=utf-8"}


def _insert_state_sorted(file_path: Path, time_str: str, entry: str) -> None:
    """Insert a ## HH:MM entry into a markdown file in chronological order."""
    text = file_path.read_text(encoding="utf-8")
    pattern = _re.compile(r'\n(?=## \d{1,2}:\d{2})')
    insert_pos = None
    for m in pattern.finditer(text):
        hdr_line = text[m.start() + 1:].split('\n')[0]  # "## HH:MM"
        hdr_time = hdr_line[3:].strip()                   # "HH:MM"
        if hdr_time > time_str:
            insert_pos = m.start()
            break
    if insert_pos is None:
        with file_path.open("a", encoding="utf-8") as f:
            f.write(entry)
    else:
        file_path.write_text(text[:insert_pos] + entry + text[insert_pos:], encoding="utf-8")


@app.post("/api/memory/narrative/<date>/states")
def add_narrative_state(date: str):
    """Manually insert a state entry to the daily states file (sorted by time).
    Accepts {time_start, time_end?, text} where time_end is optional.
    If time_end is provided, writes entries at both start and end times."""
    if not _re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        return jsonify({"error": "invalid date"}), 400
    body = request.get_json(force=True, silent=True) or {}
    time_start = (body.get("time_start") or "").strip()
    time_end   = (body.get("time_end") or "").strip()
    text       = (body.get("text") or "").strip()
    if not time_start or not text:
        return jsonify({"error": "time_start and text required"}), 400

    mem_dir = _config.get("openclaw_memory_dir", "")
    if not mem_dir:
        return jsonify({"error": "openclaw_memory_dir not configured"}), 404

    narrative_dir = Path(mem_dir).expanduser() / "physical-daily-narrative"
    narrative_dir.mkdir(parents=True, exist_ok=True)
    states_file = narrative_dir / f"{date}-states.md"

    if not states_file.exists():
        states_file.write_text(f"# Daily States — {date}\n", encoding="utf-8")

    # Insert start time entry sorted
    entry_start = f"\n## {time_start}\n{text}\n"
    _insert_state_sorted(states_file, time_start, entry_start)

    # Insert end time entry sorted (if different)
    if time_end and time_end != time_start:
        entry_end = f"\n## {time_end}\n{text}\n"
        _insert_state_sorted(states_file, time_end, entry_end)

    log.info("Manual state added for %s at %s%s", date, time_start,
             f"-{time_end}" if time_end else "")
    return jsonify({"ok": True})


def _rewrite_state_section(states_file: Path, time_key: str,
                               new_body: str | None, delete: bool = False) -> bool:
    """Rewrite or delete a ## HH:MM section in a states markdown file.
    Returns True if the section was found and modified/deleted, False otherwise."""
    text = states_file.read_text(encoding="utf-8")
    # Match: \n## HH:MM\n...content...\n (up to next \n## or end of file)
    pattern = _re.compile(
        r'\n## ' + _re.escape(time_key) + r'\n([\s\S]*?)(?=\n## |\Z)')
    m = pattern.search(text)
    if not m:
        return False
    if delete:
        result = text[:m.start()] + text[m.end():]
    else:
        result = text[:m.start()] + f"\n## {time_key}\n{new_body}\n" + text[m.end():]
    states_file.write_text(result, encoding="utf-8")
    return True


@app.put("/api/memory/narrative/<date>/states/<time>")
def update_narrative_state(date: str, time: str):
    """Update the text of a specific state entry identified by its ## HH:MM header."""
    if not _re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        return jsonify({"error": "invalid date"}), 400
    if not _re.match(r'^\d{1,2}:\d{2}$', time):
        return jsonify({"error": "invalid time"}), 400
    body = request.get_json(force=True, silent=True) or {}
    new_text = (body.get("text") or "").strip()
    if not new_text:
        return jsonify({"error": "text required"}), 400

    mem_dir = _config.get("openclaw_memory_dir", "")
    if not mem_dir:
        return jsonify({"error": "openclaw_memory_dir not configured"}), 404
    states_file = Path(mem_dir).expanduser() / "physical-daily-narrative" / f"{date}-states.md"
    if not states_file.exists():
        return jsonify({"error": "not found"}), 404

    if not _rewrite_state_section(states_file, time, new_text):
        return jsonify({"error": "entry not found"}), 404
    log.info("State updated for %s at %s", date, time)
    return jsonify({"ok": True})


@app.delete("/api/memory/narrative/<date>/states/<time>")
def delete_narrative_state(date: str, time: str):
    """Delete a specific state entry identified by its ## HH:MM header."""
    if not _re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        return jsonify({"error": "invalid date"}), 400
    if not _re.match(r'^\d{1,2}:\d{2}$', time):
        return jsonify({"error": "invalid time"}), 400
    mem_dir = _config.get("openclaw_memory_dir", "")
    if not mem_dir:
        return jsonify({"error": "openclaw_memory_dir not configured"}), 404
    states_file = Path(mem_dir).expanduser() / "physical-daily-narrative" / f"{date}-states.md"
    if not states_file.exists():
        return jsonify({"error": "not found"}), 404

    if not _rewrite_state_section(states_file, time, "", delete=True):
        return jsonify({"error": "entry not found"}), 404
    log.info("State deleted for %s at %s", date, time)
    return jsonify({"ok": True})


@app.get("/api/memory/narrative/<date>/timeline")
def get_narrative_timeline(date: str):
    """Return raw content of daily timeline file (JSON in markdown)."""
    if not _re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        return "invalid date", 400
    mem_dir = _config.get("openclaw_memory_dir", "")
    if not mem_dir:
        return "openclaw_memory_dir not configured", 404
    timeline_file = Path(mem_dir).expanduser() / "physical-daily-narrative" / f"{date}-timeline.md"
    if not timeline_file.exists():
        return "not found", 404
    return timeline_file.read_text(encoding="utf-8"), 200, {"Content-Type": "text/plain; charset=utf-8"}


# ---------------------------------------------------------------------------
# Design iteration log
# ---------------------------------------------------------------------------

_iteration_log_lock = threading.Lock()


@app.get("/iteration-log")
def iteration_log_ui():
    return send_file(Path(__file__).parent / "iteration_log.html")


@app.get("/api/iteration-log")
def get_iteration_log():
    """Return all iteration log entries (newest first)."""
    if not ITERATION_LOG_FILE.exists():
        return jsonify([])
    entries = []
    with _iteration_log_lock:
        with ITERATION_LOG_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    entries.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return jsonify(entries)


@app.post("/api/iteration-log")
def post_iteration_log():
    """Save a new iteration log entry to JSONL and append to markdown."""
    body = request.get_json(force=True, silent=True) or {}
    required = {"variable", "change_description", "rationale"}
    missing = required - body.keys()
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    entry = {
        "ts":                 datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "variable":           body.get("variable", "").strip(),
        "change_description": body.get("change_description", "").strip(),
        "rationale":          body.get("rationale", "").strip(),
        "before_output":      body.get("before_output", "").strip(),
        "after_output":       body.get("after_output", "").strip(),
    }

    # Write to JSONL
    ITERATION_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _iteration_log_lock:
        with ITERATION_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Also append markdown to project dir if configured
    proj_dir = _config.get("project_dir", "")
    if proj_dir:
        md_path = Path(proj_dir).expanduser() / "design-iteration-log.md"
        local_ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [f"\n## {local_ts} — {entry['variable']}\n"]
        lines.append(f"**Change:** {entry['change_description']}\n\n")
        lines.append(f"**Rationale:** {entry['rationale']}\n")
        if entry["before_output"]:
            lines.append(f"\n**Before:**\n{entry['before_output']}\n")
        if entry["after_output"]:
            lines.append(f"\n**After:**\n{entry['after_output']}\n")
        try:
            md_path.parent.mkdir(parents=True, exist_ok=True)
            with md_path.open("a", encoding="utf-8") as f:
                f.write("".join(lines))
        except Exception as e:
            log.warning("Failed to write iteration log markdown: %s", e)

    log.info("Iteration log entry saved: %s", entry["variable"])
    return jsonify({"ok": True, "entry": entry})


# ---------------------------------------------------------------------------
# Autoethnographic journal
# ---------------------------------------------------------------------------

_journal_lock = threading.Lock()


@app.get("/journal")
def journal_ui():
    return send_file(Path(__file__).parent / "journal.html")


@app.get("/api/journal")
def get_journal():
    """Return all journal entries (newest first)."""
    if not JOURNAL_FILE.exists():
        return jsonify([])
    entries = []
    with _journal_lock:
        with JOURNAL_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    entries.sort(key=lambda e: (e.get("date", ""), e.get("entry_type", "")), reverse=True)
    return jsonify(entries)


@app.post("/api/journal")
def post_journal():
    """Save a journal entry to JSONL and write markdown to project dir."""
    body = request.get_json(force=True, silent=True) or {}
    if not body.get("date") or not body.get("entry_type") or not body.get("phase"):
        return jsonify({"error": "Missing required fields: date, entry_type, phase"}), 400
    if body["entry_type"] not in ("midday", "endofday"):
        return jsonify({"error": "entry_type must be midday or endofday"}), 400

    entry = {
        "ts":         datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "date":       body["date"],
        "entry_type": body["entry_type"],
        "phase":      body["phase"],
        "data":       body.get("data", {}),
    }

    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _journal_lock:
        with JOURNAL_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Write markdown to project dir if configured
    proj_dir = _config.get("project_dir", "")
    if proj_dir:
        journal_dir = Path(proj_dir).expanduser() / "journal"
        journal_dir.mkdir(parents=True, exist_ok=True)
        slug = "midday" if entry["entry_type"] == "midday" else "endofday"
        md_path = journal_dir / f"{entry['date']}-{slug}.md"
        try:
            md_path.write_text(_journal_to_markdown(entry), encoding="utf-8")
        except Exception as e:
            log.warning("Failed to write journal markdown: %s", e)

    log.info("Journal entry saved: %s %s", entry["date"], entry["entry_type"])
    return jsonify({"ok": True, "entry": entry})


def _journal_to_markdown(entry: dict) -> str:
    d    = entry["data"]
    date = entry["date"]
    phase = entry["phase"]
    lines = []

    if entry["entry_type"] == "midday":
        lines.append(f"# Mid-day Check-in — {date}  ({phase})\n")
        lines.append(f"_Saved at {entry['ts']}_\n")

        assessments = d.get("interaction_assessments", [])
        if assessments:
            lines.append("\n## Interaction Assessments\n")
            for i, a in enumerate(assessments, 1):
                lines.append(f"### Interaction {i}\n")
                if a.get("description"):
                    lines.append(f"**Description:** {a['description']}\n\n")
                lines.append(f"**Physical context surfaced:** {a.get('surfaced', '—')}\n\n")
                lines.append(f"**Useful:** {a.get('useful', '—')}\n")
                if a.get("notes"):
                    lines.append(f"\n**Notes:** {a['notes']}\n")
                lines.append("\n")

        if d.get("probe_intent"):
            lines.append("\n## Structured Probe Intent\n")
            lines.append(d["probe_intent"] + "\n")

    else:  # endofday
        lines.append(f"# End-of-day Reflection — {date}  ({phase})\n")
        lines.append(f"_Saved at {entry['ts']}_\n")

        util = d.get("utilization_summary", {})
        if util:
            lines.append("\n## Utilization Summary\n")
            lines.append("| Method | Surfaced | Total |\n")
            lines.append("|--------|----------|-------|\n")
            for method in ("passive", "probe", "proactive"):
                row = util.get(method, {})
                lines.append(f"| {method.capitalize()} | {row.get('surfaced', 0)} | {row.get('total', 0)} |\n")

        for field, label in [
            ("missed_opportunities", "Missed Opportunities"),
            ("noise_irrelevance",    "Noise / Irrelevance"),
            ("pipeline_behavior",    "Pipeline Behavior"),
            ("reflection",           "Reflection"),
        ]:
            if d.get(field):
                lines.append(f"\n## {label}\n")
                lines.append(d[field] + "\n")

        if phase == "Phase 0" and d.get("pipeline_modifications"):
            lines.append("\n## Pipeline Modifications (narrative)\n")
            lines.append(d["pipeline_modifications"] + "\n")
        elif phase.startswith("Phase 1") and d.get("issues_not_acted_on"):
            lines.append("\n## Issues Observed But Not Acted On\n")
            lines.append(d["issues_not_acted_on"] + "\n")

    return "".join(lines)


# ---------------------------------------------------------------------------
# Telegram transcript capture
# ---------------------------------------------------------------------------

_tg_lock             = threading.Lock()
_tg_offset           = 0        # Telegram update_id watermark
_tg_last_msg_time: datetime | None = None
_tg_current_conv_id  = ""


def _tg_api(token: str, method: str, **params) -> dict:
    url  = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(params).encode() if params else None
    req  = _urllib_req.Request(
        url, data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with _urllib_req.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _save_tg_message(ts_utc: datetime, role: str, text: str, conv_id: str) -> None:
    date_str = ts_utc.astimezone().strftime("%Y-%m-%d")
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts":              ts_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "role":            role,
        "text":            text,
        "conversation_id": conv_id,
    }
    with _tg_lock:
        with (TRANSCRIPTS_DIR / f"{date_str}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _telegram_poller() -> None:
    """Background thread: long-poll Telegram getUpdates and save to transcripts."""
    global _tg_offset, _tg_last_msg_time, _tg_current_conv_id
    import time as _time

    while True:
        token   = _config.get("telegram_bot_token", "")
        chat_id = str(_config.get("telegram_chat_id", ""))
        if not token or not chat_id:
            _time.sleep(15)
            continue
        try:
            result = _tg_api(token, "getUpdates",
                             offset=_tg_offset, timeout=20,
                             allowed_updates=["message"])
            if not result.get("ok"):
                _time.sleep(5)
                continue
            for update in result.get("result", []):
                _tg_offset = update["update_id"] + 1
                msg = update.get("message")
                if not msg:
                    continue
                if str(msg.get("chat", {}).get("id")) != chat_id:
                    continue
                text = (msg.get("text") or "").strip()
                if not text:
                    continue
                from_info = msg.get("from", {})
                role = "assistant" if from_info.get("is_bot") else "user"
                ts   = datetime.fromtimestamp(msg["date"], tz=timezone.utc)

                # New conversation if gap > telegram_gap_minutes
                gap_min = int(_config.get("telegram_gap_minutes", 30))
                if (_tg_last_msg_time is None
                        or (ts - _tg_last_msg_time).total_seconds() > gap_min * 60):
                    _tg_current_conv_id = str(uuid.uuid4())[:8]
                _tg_last_msg_time = ts

                _save_tg_message(ts, role, text, _tg_current_conv_id)
                log.info("Telegram [%s] %s: %.80s", _tg_current_conv_id, role, text)

        except _urllib_err.URLError as e:
            log.warning("Telegram poll network error: %s", e)
            _time.sleep(10)
        except Exception as e:
            log.warning("Telegram poll error: %s", e)
            _time.sleep(5)


@app.get("/api/transcripts/<date>/counts")
def get_transcript_counts(date: str):
    """Return conversation and turn counts for a given date."""
    if not _re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        return jsonify({"error": "invalid date"}), 400
    path = TRANSCRIPTS_DIR / f"{date}.jsonl"
    if not path.exists():
        return jsonify({"conversations": 0, "turns": 0, "user_turns": 0})
    convs: set = set()
    turns = user_turns = 0
    with _tg_lock:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    m = json.loads(line)
                    convs.add(m.get("conversation_id", ""))
                    turns += 1
                    if m.get("role") == "user":
                        user_turns += 1
                except json.JSONDecodeError:
                    pass
    return jsonify({"conversations": len(convs), "turns": turns, "user_turns": user_turns})


@app.get("/api/transcripts/<date>")
def get_transcript(date: str):
    """Return full transcript for a given date as a list of messages."""
    if not _re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        return jsonify({"error": "invalid date"}), 400
    path = TRANSCRIPTS_DIR / f"{date}.jsonl"
    if not path.exists():
        return jsonify([])
    messages = []
    with _tg_lock:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return jsonify(messages)


# ---------------------------------------------------------------------------
# OpenClaw session transcript (reads local .jsonl session files directly)
# ---------------------------------------------------------------------------

HOOK_EVENTS_FILE = Path(os.environ.get("HOOK_EVENTS_FILE", "~/.spaceselflog/hook-events.jsonl")).expanduser()
_hook_events_lock = threading.Lock()


def _local_date(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d")
    except Exception:
        return ts[:10]


def _read_openclaw_session_events(session_file: Path, today_local: str, session_key: str = "") -> list[dict]:
    """Read all events from one OpenClaw session JSONL file, filtered to today (local date)."""
    events = []
    try:
        with session_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts = obj.get("timestamp", "")
                kind = obj.get("type", "")

                # Session-level metadata (no timestamp filter — always show session start)
                if kind == "session":
                    events.append({
                        "ts": ts or obj.get("ts", ""),
                        "kind": "session_start",
                        "data": {k: v for k, v in obj.items() if k not in ("type",)},
                        "session_key": session_key,
                    })
                    continue

                if kind in ("model_change", "thinking_level_change", "custom"):
                    if _local_date(ts) != today_local:
                        continue
                    events.append({"ts": ts, "kind": kind, "data": obj, "session_key": session_key})
                    continue

                if kind != "message":
                    continue

                if _local_date(ts) != today_local:
                    continue

                msg = obj.get("message", {})
                role = msg.get("role", "")
                content = msg.get("content", [])

                if role == "user":
                    # Extract text, strip OpenClaw metadata injections
                    text_parts = [c.get("text", "") for c in content
                                  if isinstance(c, dict) and c.get("type") == "text"]
                    text = " ".join(text_parts).strip()
                    events.append({"ts": ts, "kind": "user_message", "data": {"text": text}, "session_key": session_key})

                elif role == "assistant":
                    # Split into sub-events: text blocks, tool calls, thinking blocks
                    for c in content:
                        if not isinstance(c, dict):
                            continue
                        ctype = c.get("type")
                        if ctype == "text":
                            if c.get("text", "").strip():
                                events.append({"ts": ts, "kind": "assistant_text",
                                               "data": {"text": c["text"]}, "session_key": session_key})
                        elif ctype == "toolCall":
                            events.append({"ts": ts, "kind": "tool_call", "data": {
                                "id":        c.get("id"),
                                "name":      c.get("name"),
                                "arguments": c.get("arguments", {}),
                            }, "session_key": session_key})
                        elif ctype == "thinking":
                            events.append({"ts": ts, "kind": "thinking",
                                           "data": {"text": c.get("thinking", c.get("text", ""))}, "session_key": session_key})

                elif role == "toolResult":
                    text_parts = [c.get("text", "") for c in content
                                  if isinstance(c, dict) and c.get("type") == "text"]
                    events.append({"ts": ts, "kind": "tool_result", "data": {
                        "tool_call_id": msg.get("toolCallId"),
                        "tool_name":    msg.get("toolName"),
                        "text":         "\n".join(text_parts),
                    }, "session_key": session_key})

    except Exception as e:
        log.warning("Failed to read session file %s: %s", session_file, e)
    return events


def _read_hook_events(today_local: str) -> list[dict]:
    """Read hook injection events from hook-events.jsonl, filtered to today."""
    events = []
    if not HOOK_EVENTS_FILE.exists():
        return events
    with _hook_events_lock:
        with HOOK_EVENTS_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if _local_date(obj.get("ts", "")) == today_local:
                    events.append({"ts": obj["ts"], "kind": "hook_inject", "data": obj})
    return events


@app.get("/api/openclaw-transcript/today")
def get_openclaw_transcript_today():
    """
    Return today's full event stream from OpenClaw session files + hook injection log.
    Handles /reset by including both the current session file and any .reset.{today}* files.
    Now supports multiple session keys for tracking both group chat and proactive hooks.
    """
    today_local = datetime.now().strftime("%Y-%m-%d")
    yesterday_local = (datetime.fromtimestamp(datetime.now().timestamp() - 86400)
                       .strftime("%Y-%m-%d"))

    session_files_map: dict[str, Path] = {}  # session_key -> Path

    sessions_index = OPENCLAW_SESSIONS_DIR / "sessions.json"
    if sessions_index.exists():
        try:
            with sessions_index.open("r", encoding="utf-8") as f:
                index = json.load(f)
            # Read all configured session keys
            for session_key in OPENCLAW_SESSION_KEYS:
                session_key = session_key.strip()
                session_info = index.get(session_key, {})
                current_file = session_info.get("sessionFile", "")
                if current_file:
                    p = Path(current_file)
                    if p.exists():
                        session_files_map[session_key] = p
            # Include cron run sessions whose label matches OPENCLAW_CRON_LABELS
            if OPENCLAW_CRON_LABELS:
                # Build set of cron job keys whose label matches
                matching_cron_keys = set()
                for session_key, session_info in index.items():
                    if ":cron:" not in session_key or ":run:" in session_key:
                        continue
                    label = session_info.get("label", "")
                    if label in OPENCLAW_CRON_LABELS:
                        matching_cron_keys.add(session_key)
                # Now find all run sessions for those matching cron jobs
                for session_key, session_info in index.items():
                    if session_key in session_files_map:
                        continue
                    if ":run:" not in session_key:
                        continue
                    cron_key = session_key.split(":run:")[0]
                    if cron_key not in matching_cron_keys:
                        continue
                    current_file = session_info.get("sessionFile", "")
                    if not current_file:
                        run_id = session_key.split(":run:")[-1]
                        current_file = str(OPENCLAW_SESSIONS_DIR / f"{run_id}.jsonl")
                    if current_file:
                        p = Path(current_file)
                        if p.exists():
                            session_files_map[session_key] = p
        except Exception as e:
            log.warning("Failed to read sessions.json: %s", e)

    # Also include .reset files
    reset_files: list[Path] = []
    if OPENCLAW_SESSIONS_DIR.exists():
        for f in OPENCLAW_SESSIONS_DIR.iterdir():
            if ".reset." in f.name and (today_local in f.name or yesterday_local in f.name):
                if f not in session_files_map.values():
                    reset_files.append(f)

    all_events: list[dict] = []
    # Read events from each session, passing the session_key
    for session_key, sf in session_files_map.items():
        all_events.extend(_read_openclaw_session_events(sf, today_local, session_key))
    # Read reset files without session_key
    for rf in reset_files:
        all_events.extend(_read_openclaw_session_events(rf, today_local, ""))
    all_events.extend(_read_hook_events(today_local))
    all_events.sort(key=lambda e: e.get("ts", ""))
    return jsonify(all_events)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not _config.get("api_key"):
        log.warning("API key not set — configure via monitor at http://localhost:%d", PORT)
    log.info("Starting on port %d  provider=%s  model=%s",
             PORT, _config["provider"], _config["model"])
    Path(_config["frames_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    _restore_insight_state_from_events()
    threading.Thread(target=_nightly_scheduler, daemon=True).start()
    threading.Thread(target=_telegram_poller, daemon=True).start()
    threading.Thread(target=_heartbeat_monitor, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False)
