#!/usr/bin/env python3
"""
Transform all "formattedOutput" fields in analysis_results.json into a dict
structure: {"activityLabel": <original_string>}. If an entry already has a
dict with key "activityLabel", it is left unchanged.

Usage:
  python3 transform_formatted_output.py /absolute/path/to/analysis_results.json

The script will:
- Create a backup next to the input file named analysis_results.backup.json
- Overwrite the original file with the transformed content
- Print a short report of changes
"""

import json
import os
import sys
from typing import Any, Dict


def transform_entry(entry: Dict[str, Any]) -> bool:
    """Transform one entry in-place. Returns True if modified."""
    key = "formattedOutput"
    if key not in entry:
        return False
    val = entry[key]
    # Already the desired dict structure
    if isinstance(val, dict) and "activityLabel" in val:
        return False
    # If string or any other non-dict type, wrap into dict
    # Preserve original value verbatim
    entry[key] = {"activityLabel": val}
    return True


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 transform_formatted_output.py /absolute/path/to/analysis_results.json")
        sys.exit(1)

    input_path = sys.argv[1]
    if not os.path.isabs(input_path):
        print("Please provide an absolute file path.")
        sys.exit(1)
    if not os.path.exists(input_path):
        print(f"File not found: {input_path}")
        sys.exit(1)

    # Load JSON array
    with open(input_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"JSON parse error: {e}")
            sys.exit(1)

    if not isinstance(data, list):
        print("Expected a JSON array at top-level.")
        sys.exit(1)

    # Backup
    backup_path = os.path.join(os.path.dirname(input_path), "analysis_results.backup.json")
    with open(backup_path, "w", encoding="utf-8") as bf:
        json.dump(data, bf, ensure_ascii=False, indent=2)

    # Transform
    modified_count = 0
    for entry in data:
        try:
            if isinstance(entry, dict):
                if transform_entry(entry):
                    modified_count += 1
        except Exception as e:
            print(f"Warning: failed to transform an entry: {e}")

    # Write back
    with open(input_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    total = len(data)
    untouched = total - modified_count
    print(f"Done. Total entries: {total}, modified: {modified_count}, untouched: {untouched}")
    print(f"Backup written to: {backup_path}")


if __name__ == "__main__":
    main()