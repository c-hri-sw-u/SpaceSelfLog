#!/usr/bin/env python3
"""
Python 离线回补脚本：遍历会话目录的 Images/ 下所有 JPG；
读取 Data/analysis_results.json，按图片文件名判断是否已有记录；
对缺失图片，调用同样的模型接口（Gemini 或 OpenRouter 预置）生成结果；
追加写入 JSON（保持为数组），不会覆盖已有记录；
日期写入为 timeIntervalSinceReferenceDate（相对 2001-01-01 的秒），与 App 的 JSON 解码对齐。

用法示例：

python3 offline_backfill.py \
  --images_dir "/Users/chriswu/Documents/GitHub/SpaceSelfLog/Data/2025-11-09_11-01-25/Images" \
  --json_file "/Users/chriswu/Documents/GitHub/SpaceSelfLog/Data/2025-11-09_11-01-25/Data/analysis_results.json" \
  --provider openrouter

API Key 优先级：--api_key > 环境变量 > 密钥文件（.openrouter_key / .gemini_key）
"""

import os
import re
import json
import time
import base64
import argparse
import uuid
from typing import List, Dict, Any

import requests


APPLE_REF_OFFSET = 978307200  # seconds since 1970 to 2001-01-01


def parse_args():
    p = argparse.ArgumentParser(description='SpaceSelfLog Python 离线回补脚本')
    p.add_argument('--images_dir', required=True, help='Images 目录绝对路径')
    p.add_argument('--json_file', required=True, help='analysis_results.json 绝对路径')
    p.add_argument('--provider', default='openrouter', choices=['gemini', 'openrouter'], help='模型提供方')
    p.add_argument('--preset_slug', default='space-self-log', help='OpenRouter 预置名（默认 space-self-log）')
    p.add_argument('--prompt', default="Based on the image, guess what I'm doing, return only one word (English)", help='提示词')
    p.add_argument('--dry_run', action='store_true', help='仅打印缺失项，不写文件')
    p.add_argument('--api_key', help='直接传入 API Key')
    p.add_argument('--key_file', help='密钥文件路径（内容为纯 key 或 KEY=VALUE）')
    return p.parse_args()


def ensure(cond: bool, message: str):
    if not cond:
        raise SystemExit(message)


def read_key_from_file(file_path: str) -> str | None:
    try:
        if not file_path or not os.path.isfile(file_path):
            return None
        with open(file_path, 'r', encoding='utf-8') as f:
            raw = f.read().strip()
        if not raw:
            return None
        line = next((l for l in raw.splitlines() if l.strip()), raw)
        m = re.match(r'^[A-Za-z0-9_]+\s*=\s*(.+)$', line)
        key = m.group(1).strip() if m else line.strip()
        key = key.strip('"').strip("'")
        return key
    except Exception:
        return None


def list_jpg_files(dir_path: str) -> List[Dict[str, str]]:
    items = []
    for name in sorted(os.listdir(dir_path)):
        if name.lower().endswith(('.jpg', '.jpeg')):
            items.append({'name': name, 'abs': os.path.join(dir_path, name)})
    return items


def extract_basename_from_record_image_path(image_path: Any) -> str | None:
    if not isinstance(image_path, str):
        return None
    base = os.path.basename(image_path)
    if re.search(r'\.jpe?g$', base, re.IGNORECASE):
        return base
    return None


def build_existing_set(records: List[Dict[str, Any]]) -> set:
    s = set()
    for r in records:
        base = extract_basename_from_record_image_path(r.get('imagePath'))
        if base:
            s.add(base)
    return s


def parse_timestamp_from_filename(name: str) -> float | None:
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
    if ms <= 0:
        return None
    return ms / 1000.0


def to_apple_ref_secs(unix_secs: float) -> float:
    return unix_secs - APPLE_REF_OFFSET


def format_model_output(output: Any) -> str:
    if not isinstance(output, str):
        return 'unknown'
    cleaned = output.strip()
    first = (cleaned.split() or [''])[0]
    english_only = re.sub(r'[^A-Za-z]', '', first)
    return english_only.lower() if english_only else 'unknown'


def call_gemini(api_key: str, prompt: str, image_abs_path: str) -> str:
    endpoint = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}'
    with open(image_abs_path, 'rb') as f:
        img_b64 = base64.b64encode(f.read()).decode('ascii')
    body = {
        'contents': [
            {
                'parts': [
                    {'text': prompt},
                    {'inlineData': {'mimeType': 'image/jpeg', 'data': img_b64}},
                ],
            }
        ]
    }
    r = requests.post(endpoint, json=body, headers={'Content-Type': 'application/json'}, timeout=60)
    if not r.ok:
        raise RuntimeError(f'Gemini API HTTP {r.status_code}: {r.text}')
    j = r.json()
    text = (
        j.get('candidates', [{}])[0]
         .get('content', {})
         .get('parts', [{}])[0]
         .get('text', '')
    )
    if not text:
        raise RuntimeError('Gemini API invalid response')
    return text


def call_openrouter(api_key: str, prompt: str, image_abs_path: str, preset_slug: str = 'space-self-log') -> str:
    endpoint = 'https://openrouter.ai/api/v1/chat/completions'
    with open(image_abs_path, 'rb') as f:
        img_b64 = base64.b64encode(f.read()).decode('ascii')
    body = {
        'model': f'@preset/{preset_slug}',
        'messages': [
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': prompt},
                    {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{img_b64}', 'detail': 'auto'}},
                ],
            }
        ],
    }
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'}
    r = requests.post(endpoint, json=body, headers=headers, timeout=60)
    if not r.ok:
        raise RuntimeError(f'OpenRouter API HTTP {r.status_code}: {r.text}')
    j = r.json()
    text = (
        j.get('choices', [{}])[0]
         .get('message', {})
         .get('content', '')
    )
    if not text:
        raise RuntimeError('OpenRouter API invalid response')
    return text


def compute_epoch_from(json_item: Dict[str, Any], file_name: str | None) -> float:
    if file_name:
        m = re.match(r'analysis_(\d+)\.jpg$', file_name)
        if m:
            return float(m.group(1))
    ct = json_item.get('captureTime')
    rt = json_item.get('responseTime')
    if isinstance(ct, (int, float)):
        return float(ct) + APPLE_REF_OFFSET
    if isinstance(rt, (int, float)):
        return float(rt) + APPLE_REF_OFFSET
    return float('nan')


def main():
    args = parse_args()
    images_dir = args.images_dir
    json_file = args.json_file
    provider = args.provider.lower()
    prompt = args.prompt
    dry_run = args.dry_run
    preset_slug = args.preset_slug

    ensure(os.path.isdir(images_dir), f'Images 目录不存在：{images_dir}')
    ensure(provider in ('gemini', 'openrouter'), 'provider 仅支持 gemini | openrouter')

    # 读取 API Key：参数 > 环境变量 > 密钥文件
    script_dir = os.path.dirname(__file__)
    candidate_key_file = args.key_file or (
        os.path.join(script_dir, '.gemini_key') if provider == 'gemini' else os.path.join(script_dir, '.openrouter_key')
    )
    file_key = read_key_from_file(candidate_key_file)
    env_key = os.environ.get('GEMINI_API_KEY') if provider == 'gemini' else os.environ.get('OPENROUTER_API_KEY')
    api_key = args.api_key or env_key or file_key
    ensure(bool(api_key), f'缺少 API Key：使用 --api_key、--key_file 或设置环境变量 {"GEMINI_API_KEY" if provider=="gemini" else "OPENROUTER_API_KEY"}')
    if file_key:
        print(f'已从密钥文件读取 API Key：{candidate_key_file}')

    # 读取现有 JSON
    records: List[Dict[str, Any]] = []
    if os.path.isfile(json_file):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                parsed = json.load(f)
            if isinstance(parsed, list):
                records = parsed
            else:
                print('现有 JSON 不是数组，按空数组处理并重新创建为数组格式')
                records = []
        except Exception as e:
            print(f'读取现有 JSON 失败，按空数组处理：{e}')
            records = []

    existing = build_existing_set(records)
    images = list_jpg_files(images_dir)
    images_sorted = []
    for it in images:
        ts = parse_timestamp_from_filename(it['name'])
        images_sorted.append({'name': it['name'], 'abs': it['abs'], 'ts_ms': (ts or 0.0) * 1000.0})
    images_sorted.sort(key=lambda x: x['ts_ms'])

    missing = [it for it in images_sorted if os.path.basename(it['name']) not in existing]
    print(f'总图片数：{len(images)}；已有记录：{len(existing)}；缺失：{len(missing)}')

    if dry_run:
        for m in missing:
            print(f'缺失记录：{m["name"]}')
        print('dry_run 模式，未写入文件。')
        return

    # 逐个补齐
    for item in missing:
        name = item['name']
        abs_path = item['abs']
        cap_ts = parse_timestamp_from_filename(name) or (time.time())
        start_ms = time.time() * 1000.0
        try:
            if provider == 'gemini':
                output = call_gemini(api_key=api_key, prompt=prompt, image_abs_path=abs_path)
            else:
                output = call_openrouter(api_key=api_key, prompt=prompt, image_abs_path=abs_path, preset_slug=preset_slug)
            formatted = format_model_output(output)
            resp_ts = time.time()
            inference_ms = int((resp_ts - cap_ts) * 1000.0)
            record = {
                'id': str(uuid.uuid4()),
                'captureTime': to_apple_ref_secs(cap_ts),
                'responseTime': to_apple_ref_secs(resp_ts),
                'inferenceTimeMs': inference_ms,
                'isSuccess': (formatted != 'unknown' and ('failed' not in formatted)),
                'imagePath': abs_path,
                'modelOutput': output,
                # New dict structure
                'formattedOutput': { 'activityLabel': formatted },
            }
            records.append(record)
            existing.add(name)
            print(f'补齐 {name} -> {formatted}，耗时 {int(time.time()*1000 - start_ms)}ms')
        except Exception as err:
            resp_ts = time.time()
            failure = f'API call failed: {err}'
            inference_ms = int((resp_ts - cap_ts) * 1000.0)
            record = {
                'id': str(uuid.uuid4()),
                'captureTime': to_apple_ref_secs(cap_ts),
                'responseTime': to_apple_ref_secs(resp_ts),
                'inferenceTimeMs': inference_ms,
                'isSuccess': False,
                'imagePath': abs_path,
                'modelOutput': failure,
                # Standardize failure formattedOutput as dict
                'formattedOutput': { 'activityLabel': 'api failed' },
            }
            records.append(record)
            existing.add(name)
            print(f'补齐 {name} 失败，已记录失败条目：{err}')

    # 写回 JSON
    try:
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        print(f'已写入 {len(records)} 条记录 -> {json_file}')
    except Exception as e:
        raise SystemExit(f'写入 JSON 失败：{e}')


if __name__ == '__main__':
    main()