import os
import json
import glob
import time
from pathlib import Path
from openai import OpenAI

# 1. Load config from SpaceSelfLog's ingest_server config file
config_path = Path("~/.spaceselflog/config.json").expanduser()
with open(config_path, "r", encoding="utf-8") as f:
    cfg = json.load(f)

# 2. Initialize the OpenAI client using the user's OpenRouter configuration
api_key = cfg.get("api_key")
base_url = "https://openrouter.ai/api/v1" if cfg.get("provider") == "openrouter" else "https://api.openai.com/v1"
model_name = cfg.get("model", "gpt-4o")

print(f"[*] Loaded API Key for {cfg.get('provider')} using model: {model_name}")

client = OpenAI(
    api_key=api_key,
    base_url=base_url
)

ALLOWED_TAGS = [
    "Focused Work",
    "Learning & Review",
    "Life Maintenance",
    "Movement & Transit",
    "Rest & Leisure",
    "Sleep / Untracked"
]

SYSTEM_PROMPT = f"""
You are an intelligent data extraction AI.
Your job is to read user-provided daily narrative logs (states) and summarize them into a highly structured JSON timeline.
You MUST output raw JSON only, without any markdown formatting wrappers.

The JSON MUST conform exactly to this schema:
{{
  "date": "YYYY-MM-DD",
  "segments": [
    {{
      "start_time": "HH:MM",
      "end_time": "HH:MM",
      "standard_activity": "<MUST BE ONE OF THE ALLOWED TAGS>",
      "original_activity": "Short summarizing string of the activity",
      "location": "location mentioned",
      "social": "alone/with others",
      "summary": "1-2 sentence description"
    }}
  ],
  "day_summary": "1 paragraph summary of the entire day"
}}

IMPORTANT: The "standard_activity" field MUST be EXACTLY one of the following exact strings. Do not invent new tags:
{json.dumps(ALLOWED_TAGS, ensure_ascii=False)}

Here are the specific definitions for these tags to guide your classification:
1. "Focused Work" - Used for active technical creation, coding, technical writing, system analysis, and high-cognitive debugging sessions.
2. "Learning & Review" - Used for reading textbooks, reviewing documentation, architectural review, or studying.
3. "Life Maintenance" - Used for cooking, eating meals, bathroom breaks, household chores, managing mail, and daily domestic setups.
4. "Movement & Transit" - Used for commuting, cycling, walking to places, transitions between rooms, or staging.
5. "Rest & Leisure" - Used for passive digital consumption (YouTube, TV, monitoring dashboards passively), winding down, scrolling on the phone, snacking without working.
6. "Sleep / Untracked" - Used for periods of sleep, offline rest, or when there is a prolonged gap with no data.

If there are prolonged untracked gaps, fill them with a segment tagged as "Sleep / Untracked".
"""

def process_file(states_path, timeline_path):
    print(f"Processing {os.path.basename(states_path)}...")
    with open(states_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    max_retries = 3
    # Use the model_name loaded from the global config.

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": content}
                ],
                temperature=0.1
            )
            
            raw_output = response.choices[0].message.content.strip()
            
            # Clean up markdown code blocks if the model outputs them maliciously
            if raw_output.startswith("```json"):
                raw_output = raw_output[7:-3].strip()
            elif raw_output.startswith("```"):
                raw_output = raw_output[3:-3].strip()
                
            data = json.loads(raw_output)
            
            # Strict Validation of standard_activity tags
            segments = data.get("segments", [])
            for i, segment in enumerate(segments):
                if segment.get("standard_activity") not in ALLOWED_TAGS:
                    raise ValueError(f"Invalid tag generated at segment {i}: {segment.get('standard_activity')}")
            
            # Write out success
            with open(timeline_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            print(f"  ✓ Successfully generated {os.path.basename(timeline_path)}")
            return
            
        except Exception as e:
            print(f"  ✗ Attempt {attempt + 1} failed: {e}")
            time.sleep(2)
            
    print(f"FAILED to process {states_path} after {max_retries} retries.")

def main():
    base_dir = "/Users/mia/.openclaw/workspace/memory/physical-daily-narrative"
    state_files = glob.glob(os.path.join(base_dir, "*-states.md"))
    
    # Sort files to process them chronologically
    state_files.sort()
    
    print(f"Found {len(state_files)} state files. Starting generation pipeline...\n")
    
    for state_file in state_files:
        timeline_file = state_file.replace("-states.md", "-timeline.md")
        process_file(state_file, timeline_file)

if __name__ == "__main__":
    main()
