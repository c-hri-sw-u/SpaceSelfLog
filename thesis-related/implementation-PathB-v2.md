**Path B: All Decision Points**

**Layer 1: Capture**

- 🔒 Primary modality: egocentric vision via smartphone
- Vision
  - 🔒 Capture mode: adaptive interval (min 3s, trigger-driven ramp)
  - 🧪 max_interval — 15s / 20s / 30s
  - 🧪 Ramp-up curve shape (e.g., 3s → 5s → 8s → 15s → 30s)
- Audio
  - 🔒 Audio as trigger: VAD onset/offset → adjusts capture interval to min_interval + notifies Layer 1.5
  - 👉 Audio as data: VAD tag + noise level tag (quiet/moderate/loud) (attached to each frame; speaker count excluded — VLM infers social context from visual frame)
  - 🧪 Audio transcription — on / off (default off; on-demand at batch boundary via SFSpeechRecognizer)
- IMU
  - 🔒 IMU as trigger: motion state change → adjusts capture interval to min_interval + notifies Layer 1.5
  - 🔒 IMU as data: binary — stationary / sustained_motion (attached to each frame; activity classification excluded — phone wearing posture makes CMMotionActivityManager unreliable; VLM determines specific activity from visual frame)

**Layer 1.5: Preprocessing**

- 🔒 Batch boundary: two-stage process —
  - Stage 1: sensor trigger (VAD onset/offset or motion state change) proposes a cut
  - Stage 2: SSIM visual verification confirms or rejects (compare current frame vs. last batch tail)
  - Max window forces a cut regardless of triggers
- 🧪 SSIM threshold — tune during study; fallback: upgrade to embedding similarity (MobileNet/CLIP)
- 🧪 Max window size — 10 / 15 min
- 🔒 Frame filters: black + blur + deduplication + importance scoring (applied in sequence)
- 🧪 Importance score weights — w1(visual)=0.3 / w2(audio)=0.3 / w3(imu)=0.2 / w4(sparsity)=0.2, all tunable
- 🧪 Target key frames per batch — K = 4-8

**Layer 2: Inference**

- 👉 Inference batch: 1:1 with preprocess batch
- 🧪 Merge / split — add if 1:1 fails
- ❓ VLM provider — Claude / GPT-4V
- 🔒 Cross-batch context: prior batch summary (1 paragraph)
- 🔒 Output format: structured with optional fields
- 🧪 Prompt wording — iterate during Phase 0, frozen during Phase 1
- 🔒 Output length constraint — 1 short paragraph (4-6 sentences) per batch

**Layer 3: Memory Integration**

- 🔒 Strategy: direct write to memory/ subdirectories (three-tier)
  - physical-logs/ — real-time append after each VLM batch (full-volume record)
  - physical-insights/ — nightly job distills day's logs (daily distillation)
  - physical-pattern.md — nightly job maintains cross-day persistent patterns
- 👉 Nightly summarization: enabled (two outputs: daily insights file + pattern file updates)
- 🧪 Nightly prompt wording; pattern file presence vs. absence comparison
- 🔒 Retention: 14-day rolling

**Layer 3.5: Retrieval & Context Loading**

- 🔒 Three-tier visibility mapping:
  - physical-pattern.md → bootstrap injection (every turn, via agent:bootstrap hook)
  - physical-insights/ (today + yesterday) → session-start read (via AGENTS.md instruction)
  - physical-logs/ → on-demand retrieval (automatic memory_search indexing)
- 🔒 Proactive cron — included from Phase 1 start
- 🧪 Proactive cron frequency — tuned during Phase 0

---

🔒 Locked (majority of decisions) · 👉 Recommended default (2) · 🧪 Experiment variable (11: max_interval, ramp curve, SSIM threshold, max window, importance score weights, K frames, transcription on/off, merge/split, prompt wording, nightly prompt, cron frequency) · ❓ Open (1: VLM provider)
