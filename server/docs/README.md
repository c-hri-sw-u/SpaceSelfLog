# SpaceSelfLog Ingest Server

Python/Flask 服务器，负责接收来自 iOS App 的视频帧批次，调用 VLM（视觉语言模型）分析内容，并将结构化物理世界日志写入 OpenClaw 的记忆目录。

---

## 这是什么

服务器分为三个处理层：

**Layer 1（iOS → Server）**：iOS 端的 `OutboxManager` 将采集到的关键帧批次（JPEG + 传感器元数据）以 Base64 编码打包，通过 `POST /ingest` 推送到服务器。

**Layer 2（VLM 推理）**：服务器调用 VLM（默认 `anthropic/claude-sonnet-4-6`，通过 OpenRouter 或 Anthropic 直连），对帧序列进行自我中心视角分析，输出包含 `activity`、`location`、`objects`、`social_context`、`notable_events`、`observation` 等字段的 JSON。

**Layer 3（OpenClaw 记忆写入）**：VLM 输出被追加到 OpenClaw 记忆目录下的 `physical-logs/YYYY-MM-DD.md`。每隔一定批次/时间，服务器还会自动触发增量式 insight 更新（写入 `physical-insights/`），并在凌晨执行一次 pattern 归纳（写入 `physical-pattern.md`）。

### 主要特性

- **Monitor UI**：浏览器访问 `/` 查看实时批次历史、帧缩略图、VLM 输出，以及对每条批次添加人工批注。
- **动态配置**：通过 Monitor UI 实时修改 API Key、模型、提示词、调度参数，无需重启。
- **Telegram 转录**：后台轮询 Telegram Bot，将对话记录按日期保存到 `~/.spaceselflog/transcripts/`，供 OpenClaw 分析使用。
- **设计迭代日志**：`/iteration-log` 提供一个轻量化实验记录界面，日志同步写入 `project_dir/design-iteration-log.md`。
- **自动民族志日志**：`/journal` 提供每日中段/日末研究反思记录界面。
- **OpenClaw 会话转录**：`/api/openclaw-transcript/today` 实时读取 OpenClaw 本地 session 文件，在 Monitor 中呈现完整的今日 AI 对话流。

---

## HTTP 路由

| Method | Path | 说明 |
|--------|------|------|
| `GET` | `/` | Monitor 监控 UI |
| `GET` | `/iteration-log` | 设计迭代日志 UI |
| `GET` | `/journal` | 自动民族志日志 UI |
| `GET` | `/status` | 健康检查（JSON） |
| `POST` | `/ingest` | 接收 iOS 批次 |
| `GET` | `/api/config` | 读取当前配置 |
| `POST` | `/api/config` | 保存并应用配置 |
| `POST` | `/api/test` | 测试 API Key / 模型连通性 |
| `GET` | `/api/batches` | 最近 50 条批次历史 |
| `GET` | `/api/frames/<session>/<batch>/<file>` | 获取已保存的 JPEG 帧 |
| `GET` | `/api/insight/status` | Insight 触发进度与今日运行次数 |
| `GET` | `/api/events` | 事件日志（最新在前） |
| `POST` | `/api/comment` | 对批次添加人工批注 |
| `GET` | `/api/memory/logs` | 列出所有 physical-log 日期 |
| `GET` | `/api/memory/logs/<date>` | 获取指定日期的 physical-log Markdown |
| `GET` | `/api/memory/insights` | 列出所有 physical-insight 日期 |
| `GET` | `/api/memory/insights/<date>` | 获取指定日期的 physical-insight Markdown |
| `GET` | `/api/memory/pattern` | 获取 physical-pattern.md |
| `GET` | `/api/iteration-log` | 获取所有迭代日志条目 |
| `POST` | `/api/iteration-log` | 保存迭代日志条目 |
| `GET` | `/api/journal` | 获取所有日志条目 |
| `POST` | `/api/journal` | 保存日志条目 |
| `GET` | `/api/transcripts/<date>` | 获取指定日期 Telegram 转录 |
| `GET` | `/api/transcripts/<date>/counts` | 对话/轮次统计 |
| `GET` | `/api/openclaw-transcript/today` | 今日 OpenClaw 会话事件流 |

---

## 本地运行

### 1. 安装依赖

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，至少填写：

```env
# 选其一（推荐 OpenRouter，支持更多模型）
OPENROUTER_API_KEY=sk-or-...
# 或者直连 Anthropic
# ANTHROPIC_API_KEY=sk-ant-...

# OpenClaw 记忆目录（物理日志将写入此处）
OPENCLAW_MEMORY_DIR=/Users/you/path/to/openclaw/memory

# 可选
PORT=8000
VLM_MODEL=anthropic/claude-sonnet-4-6
```

> API Key 也可在服务器启动后通过 Monitor UI（`/`）在线配置，无需重启。

### 3. 启动服务器

```bash
cd server
python ingest_server.py
```

服务器启动后访问 [http://localhost:8000](http://localhost:8000) 打开 Monitor UI。

---

## 远程运行（公网访问）


---

## 数据文件说明

服务器所有运行时数据默认写入 `~/.spaceselflog/`（可通过环境变量覆盖）：

| 文件/目录 | 内容 |
|-----------|------|
| `frames/<session>/<batch>/` | 保存的 JPEG 关键帧 + `manifest.json` |
| `context.json` | 各 session 的上一批次 VLM 摘要（用于连续性） |
| `events.jsonl` | 结构化事件日志（batch、insight、pattern…） |
| `pending_comments.jsonl` | 待纳入下次 insight 的人工批注 |
| `iteration_log.jsonl` | 设计迭代日志条目 |
| `journal.jsonl` | 研究日志条目 |
| `transcripts/<date>.jsonl` | Telegram 对话转录 |
| `config.json` | 通过 UI 保存的配置覆盖 |
| `hook-config.json` | 供 OpenClaw hook 读取的调度参数 |

OpenClaw 记忆目录（`OPENCLAW_MEMORY_DIR`）下：

| 文件/目录 | 内容 |
|-----------|------|
| `physical-logs/<date>.md` | 每批次 VLM 输出的原始日志 |
| `physical-insights/<date>.md` | 每日增量式 insight 摘要（自动更新） |
| `physical-pattern.md` | 跨日行为模式归纳（每晚凌晨更新） |
| `human-comments.md` | 所有人工批注的永久归档 |