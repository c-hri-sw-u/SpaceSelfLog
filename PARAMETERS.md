# SpaceSelfLog Parameters Reference

Parameters marked **✓** are tunable live via the **capture web monitor** (StreamServer, iOS, `http://localhost:8080`).
Parameters marked **⚙** are tunable via the **server web monitor** (`http://localhost:8000`).

---

## Capture Pipeline (iOS)

### Frame Capture

| Parameter | Default | Tunable | Description |
|---|---|---|---|
| `minInterval` | 3 s | ✓ | Minimum capture interval; drop-to interval on trigger |
| `maxInterval` | 20 s | ✓ | Baseline capture interval (quiet, stable scene) |
| `rampRatio` | 1.67 | ✓ | Geometric ratio for ramp-up sequence back to maxInterval |

### Trigger / IMU

| Parameter | Default | Tunable | Description |
|---|---|---|---|
| `sustainedMotionThreshold` | 6 s | ✓ | Seconds of high-variance motion before IMU trigger fires |
| `varianceHighThreshold` | 0.012 g² | — | Variance above this starts the sustained-motion clock |
| `varianceLowThreshold` | 0.006 g² | — | Variance below this resets clock, reverts to stationary |

### Audio / VAD

| Parameter | Default | Tunable | Description |
|---|---|---|---|
| `vadSensitivity` | Med | ✓ | Preset: Low / Med / High (controls threshold + onset/offset frames) |
| `transcriptionEnabled` | false | ✓ | Enable on-device speech transcription (SFSpeechRecognizer) |
| `vadThreshold` (Low / Med / High) | 0.04 / 0.02 / 0.01 RMS | — | Set by vadSensitivity preset |
| `speechOnsetFrames` (Low / Med / High) | 5 / 3 / 2 | — | Set by vadSensitivity preset |
| `speechOffsetFrames` (Low / Med / High) | 20 / 15 / 10 | — | Set by vadSensitivity preset |

---

## Batch Processor (iOS)

### Batch Boundary

| Parameter | Default | Tunable | Description |
|---|---|---|---|
| `ssimBoundaryThreshold` | 0.85 | ✓ | VNFeaturePrint similarity below this triggers a scene-change cut |
| `firstBatchWindowSeconds` | 120 s | ✓ | Force-cut window for the very first batch of a session |
| `maxWindowSeconds` | 600 s | ✓ | Force-cut window for all subsequent batches |

### Frame Selection

| Parameter | Default | Tunable | Description |
|---|---|---|---|
| `ssimDedupThreshold` | 0.92 | ✓ | Drop a frame if similarity to any already-kept frame exceeds this |
| `kDensityPerMin` | 1.0 frames/min | ✓ | Target output density for dynamic K calculation |
| `kMin` | 2 | ✓ | Minimum frames output per batch |
| `kMax` | 12 | ✓ | Maximum frames output per batch |
| `scoreThreshold` | 0.50 | ✓ | Frames at or above this score are guaranteed inclusion |

### Importance Score Weights

| Parameter | Default | Tunable | Description |
|---|---|---|---|
| `wVisual` | 0.30 | — | Weight for sharpness (Laplacian variance) component |
| `wAudio` | 0.30 | — | Weight for audio state/transition component |
| `wIMU` | 0.20 | — | Weight for motion state/transition component |
| `wSparsity` | 0.20 | — | Weight for temporal spread component |

---

## Upload (iOS)

| Parameter | Default | Tunable | Description |
|---|---|---|---|
| `outboxEndpoint` | — | ✓ | HTTP POST destination (`http://…:8000/ingest`) |
| `maxRetries` | 3 | — | Upload attempts before dropping an outbox entry |

---

## Server

### Analysis

| Parameter | Default | Tunable | Description |
|---|---|---|---|
| `provider` | openrouter | ⚙ | API provider: `openrouter` or `anthropic` |
| `model` | claude-sonnet-4-6 | ⚙ | VLM model identifier |
| `api_key` | — | ⚙ | API key for selected provider |
| `prompt` | (default) | ⚙ | Per-batch VLM analysis prompt |
| `insight_prompt` | (default) | ⚙ | Rolling daily insight update prompt |
| `pattern_prompt` | (default) | ⚙ | Nightly behavioral pattern prompt |

### Auto-Insight Trigger

| Parameter | Default | Tunable | Description |
|---|---|---|---|
| `insight_min_batches` | 5 | ⚙ | Min batches received before auto-triggering insight update |
| `insight_min_minutes` | 30 | ⚙ | Min minutes elapsed before auto-triggering insight update |
| `nightly_hour` | 2 | ⚙ | Local hour (0–23) for nightly pattern update |

### Storage

| Parameter | Default | Tunable | Description |
|---|---|---|---|
| `frames_dir` | ~/.spaceselflog/frames | ⚙ | Where incoming frames are saved |
| `openclaw_memory_dir` | — | ⚙ | OpenClaw memory root (writes logs, insights, pattern) |
