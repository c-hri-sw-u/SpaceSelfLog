# SpaceSelfLogVisualizer 使用说明（Python + Flask & 离线回补）

可视化前端始终优先使用 `Images_censored`。若会话目录中不存在该目录，前端会自动调用本地 Python+Flask 后端生成打码图片，再进行展示。

此外提供 Python 版离线回补脚本 `offline_backfill.py`，用于遍历 `Images/`，对缺失的分析结果补齐并写入 `Data/analysis_results.json`。

## 安装依赖

```bash
cd SpaceSelfLogVisualizer
pip3 install -r requirements.txt

# 如 YOLO 运行时提示缺少 torch，可按需安装 CPU 版：
# pip3 install torch torchvision
```

## 后端服务（Flask）

- 启动：
  ```bash
  # 默认端口 5100，可通过环境变量 PORT 指定
  PORT=5100 python3 server.py
  ```
- 模型切换：支持通过环境变量指定 YOLO 权重文件（YOLOv8/YOLO11 均可）
  - 默认已使用本地 `SpaceSelfLogVisualizer/yolov11n.pt`，无需配置环境变量。
  - 如需更换其他权重（例如 `yolov8n.pt` 或 `yolo11s.pt`），可直接修改 `server.py` 中的 `YOLO_WEIGHTS` 路径或设置环境变量 `YOLO_WEIGHTS`。
- 误检抑制（可选环境变量调优）：
  - `SCREEN_CONF_THRES`（默认 `0.5`）：提高置信度阈值可减少将柜子/垃圾桶误判为 `tv`/`laptop`/`cell phone`。
  - `SCREEN_AREA_MIN_FRAC`/`SCREEN_AREA_MAX_FRAC`（默认 `0.01`/`0.6`）：过滤过小或过大的候选框。
  - `SCREEN_TEXTURE_VAR_MIN`（默认 `10.0`）：纹理方差过低的平面（柜门、墙面）将被过滤。

- 手机漏检优化（环境变量可调，默认已更宽松）：
  - `CELL_CONF_THRES`（默认 `0.40`）：手机最低置信度。
  - `CELL_AREA_MIN_FRAC`（默认 `0.002`）：手机最小占画面比例（更小也可被检测）。
  - `CELL_MAX_FRAC`（默认 `0.20`）：手机最大占画面比例（避免特写误分类）。
  - `CELL_TEXTURE_VAR_MIN`（默认 `2.0`）：手机屏幕纹理阈值更低（屏幕熄灭也可通过）。
  - 说明：若仍有漏检，可进一步将 `CELL_AREA_MIN_FRAC` 调低至 `0.001`，或将 `CELL_CONF_THRES` 降至 `0.35`。
- 会话根目录：默认 `BASE_DATA_DIR=/Users/chriswu/Documents/GitHub/SpaceSelfLog/Data`
  - 可通过环境变量覆盖：
    ```bash
    BASE_DATA_DIR="/绝对路径/Data" PORT=5100 python3 server.py
    ```
- 端口说明：若本机 5000 端口被占用（常见于系统服务），请使用 5100 或其他端口，并将前端 `script.js` 的 `SERVER_BASE` 一并调整。
- 前端行为：
  - 选择会话根目录（例如 `Data/2025-11-09_11-01-25`）后，前端会：
    - 读取 `Data/analysis_results.json`
    - 调用后端 `POST /ensure_censored { slug }`，生成 `Images_censored`
    - 通过后端 `/file?path=...` 统一加载打码后的图片

## 离线回补（Python 版）

- 提示：API Key 优先级 `--api_key > 环境变量 > 密钥文件`
  - Gemini：`GEMINI_API_KEY` 或 `.gemini_key`
  - OpenRouter：`OPENROUTER_API_KEY` 或 `.openrouter_key`

- OpenRouter（默认 provider）：
  ```bash
  python3 offline_backfill.py \
    --images_dir "/绝对路径/Data/2025-11-09_11-01-25/Images" \
    --json_file "/绝对路径/Data/2025-11-09_11-01-25/Data/analysis_results.json" \
    --provider openrouter
  ```

- Gemini：
  ```bash
  GEMINI_API_KEY="你的key" python3 offline_backfill.py \
    --images_dir "/绝对路径/Data/2025-11-09_11-01-25/Images" \
    --json_file "/绝对路径/Data/2025-11-09_11-01-25/Data/analysis_results.json" \
    --provider gemini
  ```

- 常用参数：
  - `--images_dir` 必填，`Images` 目录绝对路径
  - `--json_file`  必填，`analysis_results.json` 绝对路径
  - `--provider`   可选，`gemini | openrouter`（默认 `openrouter`）
  - `--preset_slug` 当 `openrouter` 时可选（默认 `space-self-log`）
  - `--prompt`     可选，默认与 App 一致：`Based on the image, guess what I'm doing, return only one word (English)`
  - `--dry_run`    可选，仅打印缺失项不写入
  - `--api_key` / `--key_file` 可选，覆盖或提供密钥

## JSON 写入与规则

- 输出保持为**数组**；字段与 App 对齐：
  - `id`、`captureTime`、`responseTime`、`inferenceTimeMs`、`isSuccess`、`imagePath`、`modelOutput`、`formattedOutput`
- 已有记录判断：使用记录中的 `imagePath` 的文件名（`basename`）与 `Images/` 子目录的文件名比对。
- 时间处理：
  - 从文件名提取时间戳（10 位秒或 13 位毫秒）作为 `captureTime` 基准；失败回退为当前时间。
  - `captureTime` / `responseTime` 写入为 `timeIntervalSinceReferenceDate`（相对 2001-01-01 的秒）。
  - `inferenceTimeMs = responseTime - captureTime`（毫秒）。
- 失败策略：当模型调用异常，仍追加失败条目，`formattedOutput=api failed`，`modelOutput` 为错误信息。

## 密钥文件与忽略

- 在 `SpaceSelfLogVisualizer` 下可放置：
  - `.openrouter_key` 或 `.gemini_key`
  - 内容可以是纯密钥或 `KEY=VALUE` 格式（将自动解析）。
- 建议加入 `.gitignore`（本仓库已默认忽略）：
  ```
  SpaceSelfLogVisualizer/.openrouter_key
  SpaceSelfLogVisualizer/.gemini_key
  SpaceSelfLogVisualizer/.env
  ```

## 兼容的 Node 版（可选/遗留）

仍保留 `offline_backfill.js` 以便需要时使用：

```bash
node offline_backfill.js \
  --imagesDir "/绝对路径/Images" \
  --jsonFile "/绝对路径/Data/analysis_results.json" \
  --provider openrouter
```

推荐优先使用 Python 版本以统一依赖与运行环境。

## 注意事项

- 离线回补仅**追加缺失**记录，不会改写或删除既有记录。
- 若现有 JSON 格式异常，将作为空数组继续并重写为数组格式。
- 批量运行可能受到 API 频率限制，必要时可分批或加入等待策略。