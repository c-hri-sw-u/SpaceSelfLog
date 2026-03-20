#!/usr/bin/env python3
"""
修复 analysis_results.json 中的 captureTime：
- 根据图片文件名中的 Unix 时间戳（支持 10 位秒或 13 位毫秒）
- 转换为 Apple 参考时间秒（timeIntervalSinceReferenceDate = Unix - 978307200）
- 当与现值相差超过阈值（默认 0.5 秒）或现值不可用时进行更新

用法：
  python3 SpaceSelfLogVisualizer/fix_capture_time.py \
    --json_file \
    "/Users/chriswu/Documents/GitHub/SpaceSelfLog/Data/2025-11-09_11-01-25/Data/analysis_results.json" \
    [--threshold 0.5] [--dry_run]

会自动生成带时间戳的备份文件：analysis_results.json.bak.YYYYMMDDHHMMSS
"""

import os
import re
import json
import time
import argparse
from typing import Any, Dict, List


APPLE_REF_OFFSET = 978307200  # Unix(1970) 转 Apple 参考(2001)


def parse_args():
    p = argparse.ArgumentParser(description='修复 analysis_results.json 中的 captureTime')
    p.add_argument('--json_file', required=True, help='analysis_results.json 绝对路径')
    p.add_argument('--threshold', type=float, default=0.5, help='更新阈值（秒），默认 0.5 秒')
    p.add_argument('--dry_run', action='store_true', help='仅打印不写入')
    return p.parse_args()


def extract_basename(image_path: Any) -> str | None:
    if not isinstance(image_path, str):
        return None
    base = os.path.basename(image_path)
    return base or None


def parse_unix_secs_from_name(name: str) -> float | None:
    """
    优先匹配 analysis_<epoch>.jpg；若未命中，回退到任意 10/13 位数字。
    返回 Unix 秒（float）。
    """
    m = re.search(r'analysis_(\d{10,13})', name)
    if not m:
        m = re.search(r'(\d{10,13})(?=\D|$)', name)
    if not m:
        return None
    raw = m.group(1)
    if len(raw) == 13:
        ms = float(raw)
    elif len(raw) == 10:
        ms = float(raw) * 1000.0
    else:
        return None
    return ms / 1000.0


def to_apple_ref(unix_secs: float) -> float:
    return unix_secs - APPLE_REF_OFFSET


def load_json_array(path: str) -> List[Dict[str, Any]]:
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    # 若不是数组，尝试兼容包裹对象
    if isinstance(data, dict):
        for k in ('records', 'items', 'data'):
            v = data.get(k)
            if isinstance(v, list):
                return v
    raise ValueError('JSON 格式不是数组，无法修复')


def write_json_array(path: str, arr: List[Dict[str, Any]]):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(arr, f, ensure_ascii=False, indent=2)


def main():
    args = parse_args()
    json_path = args.json_file
    threshold = float(args.threshold)
    dry_run = args.dry_run

    if not os.path.isfile(json_path):
        raise SystemExit(f'JSON 文件不存在：{json_path}')

    try:
        records = load_json_array(json_path)
    except Exception as e:
        raise SystemExit(f'读取 JSON 失败：{e}')

    updated = 0
    skipped_no_ts = 0
    total = len(records)

    for i, r in enumerate(records):
        name = extract_basename(r.get('imagePath'))
        if not name:
            skipped_no_ts += 1
            continue
        unix_secs = parse_unix_secs_from_name(name)
        if unix_secs is None or unix_secs <= 0:
            skipped_no_ts += 1
            continue

        derived = to_apple_ref(unix_secs)
        cur = r.get('captureTime')
        cur_float = float(cur) if isinstance(cur, (int, float)) else None

        if cur_float is None or abs(cur_float - derived) > threshold:
            r['captureTime'] = derived
            updated += 1

    print(f'总记录：{total}；已更新：{updated}；跳过（无时间戳或不可解析）：{skipped_no_ts}')

    if dry_run:
        print('Dry-run 模式：不写入文件')
        return

    ts = time.strftime('%Y%m%d%H%M%S')
    backup = f'{json_path}.bak.{ts}'
    try:
        # 备份原文件
        with open(json_path, 'rb') as src, open(backup, 'wb') as dst:
            dst.write(src.read())
        # 写入更新
        write_json_array(json_path, records)
        print(f'已写入：{json_path}\n已生成备份：{backup}')
    except Exception as e:
        raise SystemExit(f'写入失败：{e}')


if __name__ == '__main__':
    main()