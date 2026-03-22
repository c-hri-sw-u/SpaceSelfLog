**Path B: All Decision Points**

**Layer 1: Capture**

- 🔒 Primary modality: egocentric vision via smartphone
- Vision
  - 🔒 Capture mode: adaptive interval (minInterval, trigger-driven ramp)
  - 🧪 maxInterval — default 20s, tunable
  - 🧪 Ramp-up curve shape — controlled by rampRatio (geometric sequence from minInterval to maxInterval)
- Audio
  - 🔒 Audio as trigger: VAD onset/offset → adjusts capture interval to minInterval + notifies Layer 1.5
  - 👉 Audio as data: VAD tag + noise level tag (quiet/moderate/loud) (attached to each frame; speaker count excluded — VLM infers social context from visual frame)
  - 🧪 transcriptionEnabled — off / on (default off; gated by VAD onset/offset via SFSpeechRecognizer)
  - 🧪 vadSensitivity — Low / Med / High (controls vadThreshold, speechOnsetFrames, speechOffsetFrames)
- IMU
  - 🔒 IMU as trigger: motion state change → adjusts capture interval to minInterval + notifies Layer 1.5
  - 🔒 IMU as data: binary — stationary / sustained_motion (attached to each frame; activity classification excluded — phone wearing posture makes CMMotionActivityManager unreliable; VLM determines specific activity from visual frame)
  - 🧪 sustainedMotionThreshold — duration of high-variance motion required before trigger fires

**Layer 1.5: Preprocessing**

- 🔒 Batch boundary: two-stage process —
  - Stage 1: sensor trigger (VAD onset/offset or motion state change) proposes a cut
  - Stage 2: similarity verification confirms or rejects (compare current frame vs. last frame in buffer; fallback to last batch tail if buffer is empty)
  - Time window forces a cut regardless of triggers (firstBatchWindowSeconds for first batch; maxWindowSeconds for subsequent)
- 🧪 ssimBoundaryThreshold — scene-change cut sensitivity; fallback: upgrade to embedding similarity (MobileNet/CLIP)
- 🧪 firstBatchWindowSeconds — force-cut window for first batch of session
- 🧪 maxWindowSeconds — force-cut window for all subsequent batches
- 🔒 Frame filters: black + blur + trigger inheritance + importance scoring + deduplication (applied in sequence)
- 🧪 Importance score weights — wVisual / wAudio / wIMU / wSparsity, all tunable
- 🧪 ssimDedupThreshold — similarity above which a lower-scoring frame is dropped vs. an already-kept frame
- 🧪 Dynamic K — K = clamp(⌈duration_min × kDensityPerMin⌉, kMin, kMax)
- 🧪 scoreThreshold — frames at or above this score are guaranteed inclusion regardless of K

**Layer 2: Inference**

- 👉 Inference batch: 1:1 with preprocess batch
- 🧪 Merge / split — add if 1:1 fails
- 👉 VLM provider — configurable via provider + model (default: openrouter / claude-sonnet-4-6)
- 🔒 Cross-batch context: prior batch summary (1 paragraph), per session
- 🔒 Output format: structured JSON (activity, location, objects, social_context, notable_events, observation)
- 🧪 prompt wording — iterate during Phase 0, frozen during Phase 1
- 🔒 Output length constraint — observation field: 1 short paragraph (4-6 sentences) per batch

**Layer 3: Memory Integration**

- 🔒 Strategy: direct write to memory/ subdirectories (three-tier)
  - physical-logs/ — real-time append after each VLM batch (full-volume record)
  - physical-insights/ — rolling update triggered when insight_min_batches OR insight_min_minutes elapsed since last update (intra-day distillation)
  - physical-pattern.md — nightly job at nightly_hour maintains cross-day persistent patterns
- 🧪 insight_min_batches — min batches received before auto-triggering insight update
- 🧪 insight_min_minutes — min minutes elapsed before auto-triggering insight update
- 🧪 nightly_hour — local hour at which nightly pattern update runs
- 🧪 insight_prompt wording; pattern_prompt wording; pattern file presence vs. absence comparison
- 🔒 Retention: 14-day rolling

**Layer 3.5: Retrieval & Context Loading**

- 🔒 Three-tier visibility mapping:
  - physical-pattern.md → bootstrap injection (every turn, via agent:bootstrap hook)
  - physical-insights/ (today + yesterday) → session-start read (via AGENTS.md instruction)
  - physical-logs/ → on-demand retrieval (automatic memory_search indexing)
- 🔒 Proactive cron — included from Phase 1 start
- 🧪 Proactive cron frequency — tuned during Phase 0

---

🔒 Locked · 👉 Recommended default (3) · 🧪 Experiment variable (17: maxInterval, rampRatio, transcriptionEnabled, vadSensitivity, sustainedMotionThreshold, ssimBoundaryThreshold, firstBatchWindowSeconds, maxWindowSeconds, importance score weights, ssimDedupThreshold, dynamic K (kMin/kMax/kDensityPerMin), scoreThreshold, merge/split, prompt wording, insight_prompt wording, pattern_prompt wording, cron frequency)
