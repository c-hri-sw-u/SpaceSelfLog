# conda activate SpaceSelfLogVisualizer

import os
import io
from typing import List, Tuple

from flask import Flask, request, jsonify, send_file, abort, make_response
from flask_cors import CORS
import cv2
import numpy as np
import base64
from PIL import Image
import json

# YOLO（ultralytics）：允许通过环境变量切换权重（支持 YOLOv8/YOLO11 等）
YOLO_MODEL = None
YOLO_WEIGHTS = os.path.join(os.path.dirname(__file__), 'yolov11s.pt')
try:
    from ultralytics import YOLO
    YOLO_MODEL = YOLO(YOLO_WEIGHTS)  # 将自动下载缺失权重或加载本地文件
    print(f"[INFO] YOLO 模型已加载：{YOLO_WEIGHTS}")
except Exception as e:
    YOLO_MODEL = None
    print(f"[WARN] YOLO 模型加载失败：{e}. 屏幕检测将禁用。")

# 人脸检测：Haar
FACE_CASCADE = cv2.CascadeClassifier(
    cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
)

BASE_DATA_DIR = os.environ.get(
    'BASE_DATA_DIR',
    '/Users/chriswu/Documents/GitHub/SpaceSelfLog/Data'
)

app = Flask(__name__)
# 更显式的 CORS 配置，允许跨域 POST/GET/OPTIONS，且允许 Content-Type 头
CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

# 兜底：所有响应添加 CORS 头，避免某些情况下缺失
@app.after_request
def add_cors_headers(resp):
    try:
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    except Exception:
        pass
    return resp

def _cors_preflight_ok():
    resp = make_response("", 204)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp

SCREEN_CLASSES = {'cell phone', 'laptop', 'tv'}
# 兼容不同权重的类别命名差异（如 tvmonitor、cellphone 等）
SCREEN_SYNONYMS = {
    'tvmonitor': 'tv',
    'cellphone': 'cell phone',
    'mobile phone': 'cell phone',
}
# 置信度与几何/纹理过滤（可通过环境变量调整）
# 通用阈值
CONF_THRES = float(os.environ.get('SCREEN_CONF_THRES', '0.5'))
AREA_MIN_FRAC = float(os.environ.get('SCREEN_AREA_MIN_FRAC', '0.01'))
AREA_MAX_FRAC = float(os.environ.get('SCREEN_AREA_MAX_FRAC', '0.6'))
TEXTURE_VAR_MIN = float(os.environ.get('SCREEN_TEXTURE_VAR_MIN', '10.0'))

# cell phone 专属更宽松的默认阈值（避免漏检）
CELL_CONF_THRES = float(os.environ.get('CELL_CONF_THRES', '0.20'))
CELL_AREA_MIN_FRAC = float(os.environ.get('CELL_AREA_MIN_FRAC', '0.001'))
CELL_MAX_FRAC = float(os.environ.get('CELL_MAX_FRAC', '0.25'))
CELL_TEXTURE_VAR_MIN = float(os.environ.get('CELL_TEXTURE_VAR_MIN', '0.5'))

# laptop/tv 的最小面积，可按需调整
LAPTOP_AREA_MIN_FRAC = float(os.environ.get('LAPTOP_AREA_MIN_FRAC', '0.01'))
TV_AREA_MIN_FRAC = float(os.environ.get('TV_AREA_MIN_FRAC', '0.02'))

def _reasonable_screen(cname: str, xyxy: np.ndarray, img_bgr: np.ndarray) -> bool:
    H, W = img_bgr.shape[:2]
    x1, y1, x2, y2 = map(int, xyxy)
    w = max(1, x2 - x1)
    h = max(1, y2 - y1)
    area = w * h
    frac = area / float(W * H)
    aspect = w / float(h)

    # 面积过滤
    if cname == 'cell phone':
        if frac < CELL_AREA_MIN_FRAC or frac > CELL_MAX_FRAC:
            return False
    elif cname == 'laptop':
        if frac < LAPTOP_AREA_MIN_FRAC or frac > AREA_MAX_FRAC:
            return False
    elif cname == 'tv':
        if frac < TV_AREA_MIN_FRAC or frac > AREA_MAX_FRAC:
            return False
    else:
        if frac < AREA_MIN_FRAC or frac > AREA_MAX_FRAC:
            return False

    # 长宽比过滤
    if cname in ('tv', 'laptop'):
        if not (0.8 <= aspect <= 3.2):
            return False
    elif cname == 'cell phone':
        if not (0.3 <= aspect <= 3.2):
            return False

    # 纹理过滤：屏幕通常存在一定纹理/内容；纯平面（柜门、墙面）常见方差很低
    try:
        roi_w = min(w, W)
        roi_h = min(h, H)
        x1c = max(0, min(x1, W - roi_w))
        y1c = max(0, min(y1, H - roi_h))
        x2c = x1c + roi_w
        y2c = y1c + roi_h
        # 注意：传入 BGR，这里用拉普拉斯方差衡量纹理强度
        gray = cv2.cvtColor(img_bgr[y1c:y2c, x1c:x2c], cv2.COLOR_BGR2GRAY)
        var = cv2.Laplacian(gray, cv2.CV_64F).var()
        thr = CELL_TEXTURE_VAR_MIN if cname == 'cell phone' else TEXTURE_VAR_MIN
        if var < thr:
            # 对手机场景，若方差极低但置信度很高，可放行（在 detect 阶段结合）
            return False
    except Exception:
        # 出错时不过滤，避免误丢真阳性
        pass
    return True

def mosaic_region(img: np.ndarray, x1: int, y1: int, x2: int, y2: int, downscale: int = 16):
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(img.shape[1], int(x2)), min(img.shape[0], int(y2))
    if x2 <= x1 or y2 <= y1:
        return
    roi = img[y1:y2, x1:x2]
    h, w = roi.shape[:2]
    small_w = max(1, w // downscale)
    small_h = max(1, h // downscale)
    small = cv2.resize(roi, (small_w, small_h), interpolation=cv2.INTER_LINEAR)
    mosaic = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
    img[y1:y2, x1:x2] = mosaic

def detect_screen_boxes(img_bgr: np.ndarray) -> List[Tuple[int, int, int, int]]:
    boxes = []
    if YOLO_MODEL is None:
        return boxes
    # ultralytics 期望 RGB
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    results = YOLO_MODEL(img_rgb, verbose=False)
    for r in results:
        # 统一 names 为字典
        names_raw = getattr(r, 'names', {})
        if isinstance(names_raw, dict):
            names_map = names_raw
        else:
            try:
                names_map = {i: n for i, n in enumerate(list(names_raw))}
            except Exception:
                names_map = {}
        if not hasattr(r, 'boxes') or r.boxes is None:
            continue
        xyxy = r.boxes.xyxy.cpu().numpy()
        conf = r.boxes.conf.cpu().numpy()
        cls = r.boxes.cls.cpu().numpy().astype(int)
        for i in range(len(xyxy)):
            cname = names_map.get(int(cls[i]), '')
            cname = SCREEN_SYNONYMS.get(cname, cname)
            # 按类别应用不同的最低置信度
            min_conf = (
                CELL_CONF_THRES if cname == 'cell phone' else
                CONF_THRES
            )
            if conf[i] < min_conf:
                continue
            if cname in SCREEN_CLASSES:
                if _reasonable_screen(cname, xyxy[i], img_bgr):
                    x1, y1, x2, y2 = xyxy[i]
                    boxes.append((int(x1), int(y1), int(x2), int(y2)))
    return boxes

def detect_face_boxes(img_bgr: np.ndarray) -> List[Tuple[int, int, int, int]]:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    faces = FACE_CASCADE.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(60, 60))
    boxes = []
    for (x, y, w, h) in faces:
        boxes.append((x, y, x + w, y + h))
    return boxes

def censor_image(img_bgr: np.ndarray) -> np.ndarray:
    boxes = []
    boxes += detect_screen_boxes(img_bgr)
    boxes += detect_face_boxes(img_bgr)
    # 对所有框应用马赛克
    for (x1, y1, x2, y2) in boxes:
        mosaic_region(img_bgr, x1, y1, x2, y2, downscale=16)
    return img_bgr

def process_session(session_slug: str) -> int:
    session_dir = os.path.join(BASE_DATA_DIR, session_slug)
    images_dir = os.path.join(session_dir, 'Images')
    censored_dir = os.path.join(session_dir, 'Images_censored')

    if not os.path.isdir(session_dir):
        raise FileNotFoundError(f'会话目录不存在：{session_dir}')
    if not os.path.isdir(images_dir):
        raise FileNotFoundError(f'缺少 Images 目录：{images_dir}')
    os.makedirs(censored_dir, exist_ok=True)

    count = 0
    for name in sorted(os.listdir(images_dir)):
        if not name.lower().endswith(('.jpg', '.jpeg')):
            continue
        src = os.path.join(images_dir, name)
        dst = os.path.join(censored_dir, name)
        if os.path.isfile(dst):
            continue
        img = cv2.imread(src)
        if img is None:
            continue
        censored = censor_image(img)
        ok = cv2.imwrite(dst, censored, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        if ok:
            count += 1
    return count

def is_safe_path(p: str) -> bool:
    try:
        real = os.path.realpath(p)
        base = os.path.realpath(BASE_DATA_DIR)
        return real.startswith(base + os.sep) or real == base
    except Exception:
        return False

def session_paths(slug: str):
    session_dir = os.path.join(BASE_DATA_DIR, slug)
    images_dir = os.path.join(session_dir, 'Images')
    censored_dir = os.path.join(session_dir, 'Images_censored')
    data_dir = os.path.join(session_dir, 'Data')
    json_path = os.path.join(data_dir, 'analysis_results.json')
    return session_dir, images_dir, censored_dir, json_path

def _safe_json_read(path: str):
    try:
        if not os.path.isfile(path) or not is_safe_path(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def _safe_json_write(path: str, obj):
    try:
        if not is_safe_path(path):
            return False
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def _load_mask_png_to_array(mask_b64: str) -> np.ndarray:
    # mask_b64 can be data URL or plain base64
    try:
        if mask_b64.startswith('data:'):
            header, b64 = mask_b64.split(',', 1)
        else:
            b64 = mask_b64
        data = base64.b64decode(b64)
        with Image.open(io.BytesIO(data)) as im:
            im = im.convert('RGBA')
            arr = np.array(im)
        # Use alpha channel as mask
        alpha = arr[:, :, 3]
        return alpha
    except Exception:
        return np.zeros((1, 1), dtype=np.uint8)

def mosaic_with_mask(img_bgr: np.ndarray, mask: np.ndarray, downscale: int = 16) -> np.ndarray:
    H, W = img_bgr.shape[:2]
    # Resize mask to image size if needed
    if mask.shape[0] != H or mask.shape[1] != W:
        mask = cv2.resize(mask, (W, H), interpolation=cv2.INTER_NEAREST)
    # Create pixelated version of the whole image
    small_w = max(1, W // downscale)
    small_h = max(1, H // downscale)
    small = cv2.resize(img_bgr, (small_w, small_h), interpolation=cv2.INTER_AREA)
    pixelated = cv2.resize(small, (W, H), interpolation=cv2.INTER_NEAREST)
    # Combine: where mask > 0, take pixelated
    m = (mask > 0).astype(np.uint8)
    if m.max() == 0:
        return img_bgr
    m3 = np.repeat(m[:, :, None], 3, axis=2)
    out = img_bgr.copy()
    out[m3.astype(bool)] = pixelated[m3.astype(bool)]
    return out

@app.route('/ensure_censored', methods=['POST', 'OPTIONS'])
def ensure_censored():
    # 处理浏览器的预检请求
    if request.method == 'OPTIONS':
        return _cors_preflight_ok()
    # 同时支持 JSON、FormData 与 query 传参，避免为降低预检而改用表单后无法解析
    data = request.get_json(silent=True) or {}
    slug = data.get('slug') or request.form.get('slug') or request.args.get('slug')
    if not slug or '/' in slug or '\\' in slug:
        return jsonify({'error': '缺少或非法 slug'}), 400
    try:
        processed = process_session(slug)
        return jsonify({
            'status': 'ok',
            'processed_count': processed,
            'session_dir': os.path.join(BASE_DATA_DIR, slug)
        })
    except FileNotFoundError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/delete_entry', methods=['POST', 'OPTIONS'])
def delete_entry():
    if request.method == 'OPTIONS':
        return _cors_preflight_ok()
    data = request.get_json(silent=True) or {}
    slug = data.get('slug')
    filename = data.get('filename')
    entry_id = data.get('id')
    if not slug or not filename:
        return jsonify({'error': 'Missing slug or filename'}), 400
    if '/' in slug or '\\' in slug:
        return jsonify({'error': 'Illegal slug'}), 400
    session_dir, images_dir, censored_dir, json_path = session_paths(slug)
    try:
        # Delete files if exist
        img_path = os.path.join(images_dir, filename)
        cens_path = os.path.join(censored_dir, filename)
        deleted = {
            'images': False,
            'censored': False,
            'json_removed': False
        }
        if is_safe_path(img_path) and os.path.isfile(img_path):
            os.remove(img_path)
            deleted['images'] = True
        if is_safe_path(cens_path) and os.path.isfile(cens_path):
            os.remove(cens_path)
            deleted['censored'] = True
        # Update JSON: remove entries that map to this filename or id
        def _match_filename(entry: dict, fname: str) -> bool:
            try:
                p = entry.get('imagePath') or ''
                base = os.path.basename(p) if isinstance(p, str) else ''
                if base == fname:
                    return True
                # If path contains the filename anywhere
                if isinstance(p, str) and fname in p:
                    return True
                # Derive from captureTime / responseTime (CFAbsoluteTime + 978307200)
                def _mk(n):
                    try:
                        epoch = int(round(float(n) + 978307200))
                        return f"analysis_{epoch}.jpg"
                    except Exception:
                        return None
                ct = entry.get('captureTime')
                rt = entry.get('responseTime')
                cand1 = _mk(ct) if ct is not None else None
                cand2 = _mk(rt) if rt is not None else None
                if cand1 == fname or cand2 == fname:
                    return True
            except Exception:
                pass
            return False
        if os.path.isfile(json_path) and is_safe_path(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    arr = json.load(f)
                if isinstance(arr, list):
                    before = len(arr)
                    def to_keep(e):
                        # Prefer strict id match when provided
                        if entry_id and isinstance(e, dict) and e.get('id') == entry_id:
                            return False
                        if filename and _match_filename(e, filename):
                            return False
                        return True
                    new_arr = [e for e in arr if to_keep(e)]
                    if len(new_arr) != before:
                        with open(json_path, 'w', encoding='utf-8') as f:
                            json.dump(new_arr, f, ensure_ascii=False, indent=2)
                        deleted['json_removed'] = True
                        deleted['json_removed_count'] = before - len(new_arr)
            except Exception as e:
                return jsonify({'error': f'Failed to update JSON: {e}'}), 500
        return jsonify({'status': 'ok', 'deleted': deleted, 'session_dir': session_dir})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/censor_manual', methods=['POST', 'OPTIONS'])
def censor_manual():
    if request.method == 'OPTIONS':
        return _cors_preflight_ok()
    data = request.get_json(silent=True) or {}
    slug = data.get('slug')
    filename = data.get('filename')
    mask_b64 = data.get('mask')
    mode = (data.get('mode') or 're').lower()
    if not slug or not filename or not mask_b64:
        return jsonify({'error': 'Missing slug, filename or mask'}), 400
    if '/' in slug or '\\' in slug:
        return jsonify({'error': 'Illegal slug'}), 400
    session_dir, images_dir, censored_dir, json_path = session_paths(slug)
    try:
        # Choose base image according to mode: 're' -> Images, 'add' -> Images_censored
        if mode == 'add':
            src = os.path.join(censored_dir, filename)
        else:
            src = os.path.join(images_dir, filename)
        dst = os.path.join(censored_dir, filename)
        if not is_safe_path(src) or not os.path.isfile(src):
            if mode == 'add':
                return jsonify({'error': 'Censored base not found for Add mode'}), 404
            return jsonify({'error': 'Source image not found'}), 404
        os.makedirs(censored_dir, exist_ok=True)
        img = cv2.imread(src)
        if img is None:
            return jsonify({'error': 'Failed to read image'}), 500
        mask = _load_mask_png_to_array(mask_b64)
        out = mosaic_with_mask(img, mask, downscale=16)
        ok = cv2.imwrite(dst, out, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        if not ok:
            return jsonify({'error': 'Failed to write censored image'}), 500
        return jsonify({'status': 'ok', 'censored_path': dst, 'session_dir': session_dir, 'mode': mode})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/file', methods=['GET', 'OPTIONS'])
def file():
    if request.method == 'OPTIONS':
        return _cors_preflight_ok()
    path = request.args.get('path', '')
    if not path or not is_safe_path(path):
        return abort(403)
    if not os.path.isfile(path):
        return abort(404)
    # 按原始文件类型回传
    return send_file(path)

@app.route('/get_annotation', methods=['GET', 'OPTIONS'])
def get_annotation():
    if request.method == 'OPTIONS':
        return _cors_preflight_ok()
    slug = request.args.get('slug')
    if not slug or '/' in slug or '\\' in slug:
        return jsonify({'error': 'Illegal slug'}), 400
    session_dir, images_dir, censored_dir, json_path = session_paths(slug)
    data_dir = os.path.join(session_dir, 'Data')
    anno_path = os.path.join(data_dir, 'manual_annotation.json')
    if not os.path.isfile(anno_path):
        return jsonify({'error': 'annotation not found'}), 404
    arr = _safe_json_read(anno_path)
    if not isinstance(arr, list):
        return jsonify({'error': 'invalid annotation json'}), 500
    return jsonify({'status': 'ok', 'path': anno_path, 'count': len(arr), 'data': arr})

def _normalize_formatted_to_obj(fo):
    if isinstance(fo, dict):
        return fo
    if isinstance(fo, str):
        try:
            parsed = json.loads(fo)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}

@app.route('/ensure_annotation', methods=['POST', 'OPTIONS'])
def ensure_annotation():
    if request.method == 'OPTIONS':
        return _cors_preflight_ok()
    data = request.get_json(silent=True) or {}
    slug = data.get('slug') or request.form.get('slug') or request.args.get('slug')
    if not slug or '/' in slug or '\\' in slug:
        return jsonify({'error': 'Illegal slug'}), 400
    session_dir, images_dir, censored_dir, json_path = session_paths(slug)
    data_dir = os.path.join(session_dir, 'Data')
    anno_path = os.path.join(data_dir, 'manual_annotation.json')
    try:
        if os.path.isfile(anno_path):
            arr = _safe_json_read(anno_path)
            if not isinstance(arr, list):
                return jsonify({'error': 'invalid annotation json'}), 500
            return jsonify({'status': 'ok', 'created': False, 'path': anno_path, 'count': len(arr)})
        src_arr = _safe_json_read(json_path)
        if not isinstance(src_arr, list):
            return jsonify({'error': 'analysis_results.json missing or invalid'}), 404
        new_arr = []
        for e in src_arr:
            if not isinstance(e, dict):
                continue
            ne = dict(e)
            fo = e.get('formattedOutput') or e.get('formatted')
            fo_obj = _normalize_formatted_to_obj(fo)
            anno = {}
            for k, v in fo_obj.items():
                anno[k] = v
                anno[f"{k}Checked"] = False
            ne['annotation'] = anno
            ne['annotationChecked'] = False
            new_arr.append(ne)
        if not _safe_json_write(anno_path, new_arr):
            return jsonify({'error': 'failed to write annotation file'}), 500
        return jsonify({'status': 'ok', 'created': True, 'path': anno_path, 'count': len(new_arr)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/update_annotation', methods=['POST', 'OPTIONS'])
def update_annotation():
    if request.method == 'OPTIONS':
        return _cors_preflight_ok()
    data = request.get_json(silent=True) or {}
    slug = data.get('slug')
    entry_id = data.get('id')
    updates = data.get('updates') or {}
    if not slug or not entry_id:
        return jsonify({'error': 'missing slug or id'}), 400
    if '/' in slug or '\\' in slug:
        return jsonify({'error': 'Illegal slug'}), 400
    session_dir, images_dir, censored_dir, json_path = session_paths(slug)
    anno_path = os.path.join(session_dir, 'Data', 'manual_annotation.json')
    if not os.path.isfile(anno_path):
        return jsonify({'error': 'annotation file not found'}), 404
    arr = _safe_json_read(anno_path)
    if not isinstance(arr, list):
        return jsonify({'error': 'invalid annotation json'}), 500
    idx = None
    for i, e in enumerate(arr):
        if isinstance(e, dict) and e.get('id') == entry_id:
            idx = i
            break
    if idx is None:
        return jsonify({'error': 'entry id not found'}), 404
    e = arr[idx]
    anno = e.get('annotation')
    if not isinstance(anno, dict):
        anno = {}
        e['annotation'] = anno
    # Apply annotation value changes
    if isinstance(updates.get('annotation'), dict):
        for k, v in updates['annotation'].items():
            anno[k] = v
    # Apply per-key check flags
    if isinstance(updates.get('checks'), dict):
        for k, v in updates['checks'].items():
            anno[f"{k}Checked"] = bool(v)
    # Apply global annotationChecked
    if 'annotationChecked' in updates:
        e['annotationChecked'] = bool(updates.get('annotationChecked'))
    # Persist
    if not _safe_json_write(anno_path, arr):
        return jsonify({'error': 'failed to write annotation json'}), 500
    return jsonify({'status': 'ok', 'updated': {'id': entry_id, 'annotation': anno, 'annotationChecked': e.get('annotationChecked', False)}})

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'base': BASE_DATA_DIR})

if __name__ == '__main__':
    # 允许通过环境变量 PORT 指定端口，默认改为 5100 以规避本机 5000 端口占用
    port = int(os.environ.get('PORT', '5100'))
    app.run(host='127.0.0.1', port=port, debug=True)
