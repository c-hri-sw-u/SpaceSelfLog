#!/usr/bin/env python3
"""
手动为指定日期生成 timeline.md 文件。
逻辑与 ingest_server.py 中的 _generate_daily_timeline() 完全一致。

用法:
    python3 scripts/generate_timeline.py 2026-04-24 2026-04-26
    python3 scripts/generate_timeline.py --dry-run 2026-04-24
"""

import sys
import json
import argparse
from pathlib import Path
from openai import OpenAI

# ── 路径配置 ──────────────────────────────────────────────────────────────────
CONFIG_FILE   = Path("~/.spaceselflog/config.json").expanduser()
NARRATIVE_DIR = Path("~/.openclaw/workspace/memory/physical-daily-narrative").expanduser()

# ── Timeline 生成 Prompt（与 ingest_server.py 保持一致）─────────────────────
TIMELINE_PROMPT = """\
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
      "standard_activity": "<one of: Focused Work | Learning & Review | Life Maintenance | Movement & Transit | Rest & Leisure | Sleep / Untracked | Fitness & Well-being>",
      "original_activity": "<short label describing the specific activity>",
      "location": "<where>",
      "social": "<alone / with others / ...>",
      "summary": "<1-2 sentence description>"
    }
  ],
  "day_summary": "<2-3 sentence overview of how the day went>"
}

Rules:
- Merge consecutive states that describe the same activity into one segment.
- Set end_time to the timestamp of the next segment's start (or the \
last known state time for the final segment).
- If there is a gap between states (e.g. no data 12:00–14:00), \
create a gap segment with standard_activity "Sleep / Untracked" rather than merging across it.
- standard_activity MUST be one of the 7 exact values listed above.
- Keep the JSON compact. No markdown fences.\
"""


def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


def strip_json_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove first and last fence lines
        lines = lines[1:] if lines[0].startswith("```") else lines
        lines = lines[:-1] if lines and lines[-1].strip() == "```" else lines
        text = "\n".join(lines).strip()
    return text


def generate_timeline(date_str: str, cfg: dict, dry_run: bool = False) -> bool:
    states_file = NARRATIVE_DIR / f"{date_str}-states.md"
    timeline_file = NARRATIVE_DIR / f"{date_str}-timeline.md"

    # ── 检查前置条件 ──
    if not states_file.exists():
        print(f"[{date_str}] ❌ states.md 不存在，跳过")
        return False

    if timeline_file.exists():
        print(f"[{date_str}] ⚠️  timeline.md 已存在，跳过（使用 --force 强制覆盖）")
        return False

    states_text = states_file.read_text(encoding="utf-8").strip()
    states_clean = "\n".join(
        line for line in states_text.splitlines()
        if not line.strip().startswith("<!--")
    ).strip()

    if not states_clean:
        print(f"[{date_str}] ❌ states.md 内容为空，跳过")
        return False

    print(f"[{date_str}] 📄 states.md 已读取（{len(states_clean)} 字符）")

    if dry_run:
        print(f"[{date_str}] 🔍 dry-run 模式，不调用 API")
        return True

    # ── 配置 API 客户端 ──
    provider = cfg.get("text_provider") or cfg.get("provider", "openrouter")
    api_key  = cfg.get("text_api_key") or cfg.get("api_key", "")
    model    = cfg.get("text_model") or cfg.get("model", "mistralai/mistral-small-2603")

    if not api_key:
        print(f"[{date_str}] ❌ 没有找到 API key，请检查 ~/.spaceselflog/config.json")
        return False

    if provider == "anthropic":
        import anthropic
        client_ant = anthropic.Anthropic(api_key=api_key)
        print(f"[{date_str}] 🤖 调用 Anthropic {model} ...")
        r = client_ant.messages.create(
            model=model, max_tokens=2048,
            system=TIMELINE_PROMPT,
            messages=[{"role": "user", "content": f"States file for {date_str}:\n\n{states_clean}"}],
        )
        raw = (r.content[0].text or "").strip()
    else:
        base_url = "https://openrouter.ai/api/v1"
        client_or = OpenAI(api_key=api_key, base_url=base_url)
        print(f"[{date_str}] 🤖 调用 OpenRouter {model} ...")
        r = client_or.chat.completions.create(
            model=model, max_tokens=8192,
            messages=[
                {"role": "system", "content": TIMELINE_PROMPT},
                {"role": "user",   "content": f"States file for {date_str}:\n\n{states_clean}"},
            ],
        )
        raw = (r.choices[0].message.content or "").strip()

    # ── 解析验证 JSON ──
    cleaned = strip_json_fences(raw)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"[{date_str}] ❌ JSON 解析失败: {e}")
        print("原始输出：", raw[:500])
        return False

    segments = parsed.get("segments", [])
    print(f"[{date_str}] ✅ 解析成功，共 {len(segments)} 个 segment")

    # ── 写入文件 ──
    timeline_file.write_text(
        f"<!-- auto-generated by SpaceSelfLog — {date_str} -->\n\n"
        + cleaned + "\n",
        encoding="utf-8",
    )
    print(f"[{date_str}] 💾 已写入: {timeline_file}")

    # ── 预览质量 ──
    from datetime import datetime, timedelta
    events = []
    for seg in segments:
        start = seg.get("start_time", "")
        end   = seg.get("end_time", "")
        act   = seg.get("standard_activity", "")
        if not start or not end or not act:
            continue
        try:
            start_dt = datetime.strptime(f"{date_str} {start}", "%Y-%m-%d %H:%M")
            end_dt   = datetime.strptime(f"{date_str} {end}",   "%Y-%m-%d %H:%M")
            if end_dt < start_dt:
                end_dt += timedelta(days=1)
            events.append({"start": start_dt, "end": end_dt, "activity": act})
        except Exception:
            continue

    date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
    boxes = []
    for hr in range(24):
        for m in (0, 15, 30, 45):
            slot_start = datetime(date_obj.year, date_obj.month, date_obj.day, hr, m)
            slot_end   = slot_start + timedelta(minutes=15)
            slot_act   = "Sleep / Untracked"
            for e in events:
                if max(slot_start, e["start"]) < min(slot_end, e["end"]):
                    slot_act = e["activity"]
                    if slot_act != "Sleep / Untracked":
                        break
            boxes.append(slot_act)

    non_sleep    = [b for b in boxes if b != "Sleep / Untracked"]
    active_ratio = len(non_sleep) / len(boxes)
    distinct     = len(set(non_sleep))
    passed       = active_ratio >= 0.10 and distinct >= 2
    print(f"[{date_str}] 📊 质量检查: active_ratio={active_ratio:.1%} ({len(non_sleep)}/96), "
          f"distinct_acts={distinct}, 通过过滤={'✅' if passed else '❌ 仍会被热图过滤'}")
    return True


def main():
    parser = argparse.ArgumentParser(description="手动生成 timeline.md")
    parser.add_argument("dates", nargs="+", help="要生成的日期，格式 YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="只检查文件，不调用 API")
    parser.add_argument("--force",   action="store_true", help="即使 timeline.md 已存在也覆盖")
    args = parser.parse_args()

    cfg = load_config()
    print(f"配置: provider={cfg.get('text_provider') or cfg.get('provider')}, "
          f"model={cfg.get('text_model') or cfg.get('model')}")
    print()

    for date_str in args.dates:
        # 如果 --force 则先删除已有文件
        if args.force:
            existing = NARRATIVE_DIR / f"{date_str}-timeline.md"
            if existing.exists():
                existing.unlink()
                print(f"[{date_str}] 🗑️  已删除旧 timeline.md")
        generate_timeline(date_str, cfg, dry_run=args.dry_run)
        print()


if __name__ == "__main__":
    main()
