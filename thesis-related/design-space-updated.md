# System Design Space: Egocentric Perception Pipeline for OpenClaw

> This document maps every design decision in the pipeline, discusses trade-offs for each option, and marks which choices are **locked**, which are **recommended defaults**, and which are **design variables to explore during the experiment**.

---

## Overview: The Core Coupling

This system is not a linear pipeline. The central design tension is that **capture rate, preprocessing strategy, and inference strategy are mutually constrained**. A decision at any layer restricts or enables options at adjacent layers. The document is organized by layer, but cross-references between layers are marked with → arrows.

**The architecture uses batch inference.** Frames are accumulated into batches, preprocessed to extract key frames, then sent to the VLM as a group. This enables higher capture rates, lower API cost, and native cross-frame reasoning. Per-frame inference (Path A from earlier iterations) is excluded by design argument: it bounds capture rate to API latency, prevents cross-frame reasoning, and produces inferior information density at higher cost.

The pipeline has four layers: Layer 1 (Capture) produces raw timestamped frames with sensor metadata; Layer 1.5 (Preprocessing) defines batch boundaries and filters frames; Layer 2 (Inference) sends key frames to a VLM for structured text output; Layer 3 (Memory Integration) writes VLM output into OpenClaw's memory directory.

**Key architectural insight: Layer 1 and Layer 1.5 are two independent loops.** Layer 1 is a continuous data producer (capture frames into a buffer at adaptive intervals). Layer 1.5 is a passive data consumer (awakened by sensor triggers or max window timeout to process buffered frames). Sensor triggers adjust capture density but do not directly cut batches—batch boundaries are determined by Layer 1.5 through visual verification.

---

## Layer 1: Capture

**Output:** Raw timestamped frames + continuous Audio/IMU state (readable on demand)

### 1.1 Vision Capture

**🔒 Locked:** Egocentric vision is the primary modality. Smartphone worn on body as hardware proxy for smart glasses.

**👉 Capture mode: Adaptive Interval**

A dynamically adjusting capture frequency driven by scene change signals:

- **max_interval (🧪):** Low-frequency baseline when the scene is stable. Recommended starting range: 15–30 seconds. Guarantees continuous coverage of static scenes—pattern-level information (cooking at the same time daily, habitual desk objects) depends on long-term low-frequency accumulation and cannot be abandoned.
- **min_interval:** High-frequency burst when the scene is active. Recommended: 3 seconds.
- **Trigger sources:** VAD onset/offset, motion state change (stationary ↔ sustained_motion).
- **Behavior:** Default runs at max_interval. Trigger fires → immediately drop to min_interval for dense capture. After several consecutive frames with no new trigger → interval gradually ramps back up (e.g., 3s → 5s → 8s → 15s → 30s). If a trigger fires during ramp-up → immediately return to min_interval.

**Design rationale:** Dense capture serves event detection (what happened during a scene transition); low-frequency baseline serves pattern accumulation (what are the user's daily routines). These contribute to personalization differently and are both necessary.

**Note on sensor-frame relationship:** Audio and IMU sample continuously in the background (AVAudioEngine tap ~100ms, accelerometer ~100ms), maintaining rolling state via sliding windows. Vision capture is discrete. Each time a frame is captured, the current audio and IMU state is read and attached as metadata. The interval ramp-up sequence need not be multiples of any sensor window—it follows experiential tuning (e.g., 3s → 5s → 8s → 15s → 30s).

**Note on trigger-frame quality:** Frames captured at the instant of a trigger (e.g., motion onset) may suffer motion blur. This is handled by Layer 1.5's blur detection, not at the capture layer.

**🧪 Experiment variables:** max_interval (15s / 20s / 30s); ramp-up curve shape.

### 1.2 Audio Channel

**🔒 Locked:** Supplementary modality. Audio never competes with vision as the primary data source.

Audio serves **two distinct roles** in the pipeline:

**Implementation:** A single `AVAudioEngine` tap produces three outputs simultaneously:

1. **VAD** — libfvad (WebRTC VAD standalone fork), via existing Swift package or C bridging. Processes each audio frame (~10-30ms) and returns speech/not-speech. Serves as both **trigger** (onset/offset signals adjust capture interval and notify Layer 1.5) and **tag** (attached to each captured frame).

2. **Noise Level** — RMS → dB computed from the same tap, smoothed over a 3-second sliding window, mapped to quiet/moderate/loud. Serves only as **tag**.

3. **Transcription** — `SFSpeechRecognizer`, default **off**. Triggered on-demand at Layer 1.5 batch boundary, processing only VAD-marked speech segments. 🧪 Experiment variable: enable in later study phases to compare personalization quality with vs. without conversation content.

**Speaker count: excluded.** No lightweight iOS solution exists. The VLM can infer social context (alone, small group, crowd) from the visual frame directly.

**Audio as trigger:** VAD onset/offset is the sole audio trigger. Noise level change was considered but rejected due to high false positive rate from transient sounds; noise level serves only as a tag.

### 1.3 IMU Channel

**🔒 Locked:** Supplementary modality.

**Implementation:** `CMAccelerometer` raw data (not `CMMotionActivityManager`—the phone's wearing posture does not match the system's built-in classifier assumptions).

Three-axis acceleration → composite magnitude → variance over a 2–3 second rolling window. Low variance = stationary; high variance sustained >5–8 seconds = sustained_motion; transient spikes = ignored.

**Output:** Binary motion state only.

```
imu_tags: {
    motion_state: "stationary" | "sustained_motion"
}
```

**Dual role:**
- **Trigger:** State transitions (stationary ↔ sustained_motion) adjust capture interval to min_interval and notify Layer 1.5.
- **Tag:** Current state attached to frame metadata for VLM context.

**Activity classification: excluded.** Phone wearing posture (body-mounted, not pocket/hand) makes `CMMotionActivityManager` classifications unreliable. The VLM can determine specific activity type (walking, cycling, cooking) from the visual frame; the IMU only needs to answer "moving or not."

### 1.4 Layer 1 Combined Output

Each captured frame carries attached metadata:

```
{
  timestamp: ISO-8601,
  image: raw frame (JPEG),
  audio_tags: {
    noise_level: "quiet" | "moderate" | "loud",
    speech_detected: bool,
    transcript?: string  // 🧪 optional, off by default
  },
  imu_tags: {
    motion_state: "stationary" | "sustained_motion"
  },
  current_interval: int  // current adaptive interval in seconds
}
```

**Note on `current_interval`:** This field carries information value for Layer 1.5. A small interval (e.g., 3s) indicates high frame density during an active period—deduplication can be aggressive. A large interval (e.g., 30s) indicates sparse sampling—each frame is precious and deduplication should be conservative. A sudden drop in interval also signals that a trigger just fired, which can inform batch boundary decisions.

---

## Layer 1.5: Preprocessing

Preprocessing serves two functions: **define batch boundaries** and **filter frames within each batch**. Layer 1.5 is a passive consumer of the frame buffer produced by Layer 1. It is awakened by two conditions: a sensor trigger notification from Layer 1, or a max window timeout.

### 1.5a Batch Boundary: Sensor Trigger + Visual Verification

Batch boundaries are determined through a **two-stage process**: sensor triggers propose a cut, and visual verification confirms or rejects it.

**Stage 1: Sensor trigger proposes a cut.** When Layer 1.5 is awakened by a sensor trigger (VAD onset/offset or motion state change), it examines the buffered frames since the last confirmed batch.

**Stage 2: Visual verification confirms or rejects.** The current frame(s) are compared against the last confirmed batch's tail frame(s) using **SSIM (Structural Similarity Index)**. If SSIM falls below a threshold (🧪), the scene has genuinely changed → cut a new batch. If SSIM remains above threshold (user shifted position but is still in the same scene) → frames stay in the buffer, awaiting the next trigger or max window timeout.

**Why SSIM:** More robust to lighting changes than raw pixel comparison; pure CPU/OpenCV computation with negligible power cost; only needs to confirm/deny a sensor-proposed cut (not independently discover scene changes).

**Fallback/upgrade path:** If SSIM produces too many false positives (lighting shifts, slight angle changes), upgrade to embedding similarity (MobileNet / CLIP vision encoder via Core ML) as a 🧪 experiment variable. The VLM at Layer 2 remains the ultimate backstop—even if scene change detection occasionally errs, it will not produce incorrect memory entries.

**Max window (🧪 10–15 min):** Regardless of triggers, a batch is force-cut after max_window elapses. This ensures static scenes (user at desk for hours) are not forgotten.

**Key distinction: Sensor Trigger ≠ Scene Change.** Sensor triggers are low-threshold guesses (biased toward over-triggering—cheap to capture extra frames and discard them). Scene change is a visual judgment made by Layer 1.5. Batch count sent to Layer 2 is determined by visual content change, not by sensor sensitivity.

**🧪 Experiment variables:** SSIM threshold; max window size (10 / 15 min); whether to upgrade to embedding similarity.

### 1.5b Frame Filtering Within Batch

Given a batch of N raw frames, select the K most informative ones.

| Filter | What it does | Why it matters |
|--------|-------------|----------------|
| **Black frame detection** | Discard frames that are mostly black (phone in pocket, camera covered) | Saves tokens; these frames carry zero information |
| **Blur detection** | Discard frames with high blur score (motion blur during walking) | Blurred frames confuse VLM; waste tokens |
| **Pixel similarity / deduplication** | Compare adjacent frames; drop near-duplicates | During static scenes (sitting at desk), consecutive frames are nearly identical |
| **Importance scoring** | Rank surviving frames by a composite importance score incorporating visual change, audio events, IMU transitions, and capture sparsity | These frames are more likely to contain information-rich context transitions |

**Recommended:** Apply all four filters in sequence. Order: black → blur → deduplication → importance scoring. The first three are pure subtraction (discard junk). The fourth is scored selection: each surviving frame receives a composite importance score, and the top-K frames are selected.

**Frame Importance Score:**

`score = w1 * visual + w2 * audio + w3 * imu + w4 * sparsity`

Four components, each normalized to 0–1:
- **visual:** Pixel difference from the preceding frame (already computed during deduplication), min-max normalized within the batch.
- **audio:** `speech_detected: false` = 0; `speech_detected: true` = 0.5; VAD transition point (onset/offset) = 1.0.
- **imu:** No state change = 0; motion state just transitioned = 1.0.
- **sparsity:** `current_interval / max_interval`, normalized to 0–1. Larger interval → frame is rarer → higher score.

Default weights (🧪 all tunable): `w1 = 0.3, w2 = 0.3, w3 = 0.2, w4 = 0.2`. Visual and audio weighted highest as they directly reflect scene content change. IMU and sparsity are auxiliary signals.

**Selection:** Rank all frames in batch by score descending, take top-K (K = 4–8, 🧪).

**Target output:** 4–8 key frames per batch with their attached metadata. Exact raw frame count per batch varies with adaptive interval and batch duration.

**Implementation note:** All filters are lightweight local computation (OpenCV pixel operations + threshold comparisons). No API calls. Cost ≈ negligible.

---

## Layer 2: Inference

**Output:** Structured text descriptions with timestamps and metadata, formatted as independent paragraphs suitable for direct writing into memory files

### 2.1 Inference Batch

👉 **1:1 mapping with preprocess batch.** Each batch from Layer 1.5 becomes one VLM call. Merging and splitting add complexity that is not justified until failure modes are observed during the experiment.

🧪 **Experiment variable:** Log cases where 1:1 produces incoherent summaries. Add merge/split only if needed.

### 2.2 VLM Call Design

🔒 **Locked:** Cloud API (Claude or GPT-4V). Local models insufficient for the structured reasoning required.

#### Batch Prompt

```
Input:  4-8 key frames + audio tags + IMU tags per frame + batch time range
Output: Observation paragraph: faithful description + interpretive annotation
```

| Design choice | Options | Trade-off |
|---------------|---------|-----------|
| **Frame ordering in prompt** | (a) Chronological with timestamps | VLM can reason about temporal sequence naturally |
| | (b) Chronological + explicit "describe the transition between frames" instruction | Better at capturing change, but longer prompt |
| **Cross-batch context** | (a) No context from prior batches | Each batch is self-contained; may miss ongoing activities |
| | (b) Include prior batch summary (1 paragraph) | Maintains continuity across batches; small token overhead |
| **Output format** | (a) Free-form paragraph | Flexible; VLM chooses what to emphasize |
| | (b) Structured fields: {activity, location, objects, social_context, notable_events} | Consistent; easier to parse for memory integration; may force VLM to hallucinate fields it can't observe |

**Recommended defaults:**
- Chronological frames + timestamps
- Include prior batch summary (1 paragraph) for continuity
- Structured output with optional fields (VLM can mark fields as "not observed" rather than hallucinate)

**→ Constraint from Layer 3:** VLM batch output writes directly into `physical-logs/` as independent markdown paragraphs. Each entry should be a **self-contained short paragraph with a timestamp header**, ensuring fine retrieval granularity after chunking. The output should be **observation + interpretive annotation** (faithful description as primary content, with search-friendly semantic labels). Pattern extraction is deferred to the nightly job—batch-level output should not attempt cross-day generalization.

### 2.3 Prompt Design Principles

The VLM prompt should:

1. **Prioritize personalization-relevant information.** Not "describe what you see" but "what does this reveal about the user's habits, preferences, environment, and current activity that a personal AI agent should know?"
2. **Include multimodal tags as context.** "The IMU indicates the user is stationary. Audio detects speech in a quiet environment." This grounds the VLM's interpretation.
3. **Request explicit uncertainty.** "If you cannot determine the activity, say so rather than guessing."
4. **Constrain output length.** Per-batch: 1 short paragraph (4-6 sentences).

🧪 **Experiment variable:** Prompt wording. Iterate during Phase 0 calibration; frozen during Phase 1 observation. Log which prompt versions produce the most useful memory entries.

---

## Layer 3: Memory Integration

**Output:** Physical-world observations written into OpenClaw's memory system

### 3.1 Integration Strategy

**👉 Direct write to OpenClaw's memory directory.**

**Key architectural finding:** OpenClaw's `memory_search` indexes `MEMORY.md` + `memory/**/*.md`—all markdown files under the memory directory. The perception pipeline does not need to enter any of OpenClaw's native write paths (no silent session, no compaction triggering, no context window competition). Writing markdown files into subdirectories of `memory/` makes them immediately searchable by the agent via `memory_search`.

**File structure:**

```
memory/
├── 2026-03-14.md                # OpenClaw native daily log (digital interactions)
├── MEMORY.md                    # OpenClaw native long-term memory (digital)
│
├── physical-logs/
│   ├── 2026-03-14.md            # All batch observations for the day (written in real-time)
│   └── 2026-03-15.md
├── physical-insights/
│   ├── 2026-03-14.md            # Nightly summary (key information extracted from the day)
│   └── 2026-03-15.md
├── physical-pattern.md          # Cross-day persistent patterns (e.g., "user cooks dinner ~6pm daily")
```

**Three-tier write logic:**

**physical-logs/** (full-volume record layer)
- Write timing: real-time, appended immediately after each VLM inference batch completes
- Content: faithful observation + interpretive annotation
- Characteristics: highest volume, finest granularity, subject to temporal decay in retrieval weighting
- Serves: RQ1 (what information becomes visible)

**physical-insights/** (daily distillation layer)
- Write timing: nightly job reads the day's physical-logs
- Content: noteworthy information—new behaviors, anomalous events, deviations from known patterns—plus details the model judges important or potentially useful for future personalization (e.g., a new object on the desk, an unfamiliar location, a shift in routine timing)
- Characteristics: one short file per day, subject to temporal decay
- Serves: RQ2 (what information is useful for personalization)

**physical-pattern.md** (persistent pattern layer)
- Write timing: maintained by the same nightly job
- Content: cross-day recurring patterns (routines, preferences, habits)
- Characteristics: single file, no date, not subject to temporal decay, participates in retrieval at normal weight
- Serves: RQ2 + RQ3 (core personalization output + design findings)

**Parallel relationship with OpenClaw's native architecture:**

|  | Digital (OpenClaw native) | Physical (perception pipeline) |
| --- | --- | --- |
| Full-volume record | `memory/YYYY-MM-DD.md` | `physical-logs/YYYY-MM-DD.md` |
| Daily distillation | (no native equivalent) | `physical-insights/YYYY-MM-DD.md` |
| Persistent knowledge | `MEMORY.md` | `physical-pattern.md` |

**Architecture advantages:**
- **Purely additive extension:** no modification to OpenClaw code, no interference with session/compaction mechanisms
- **Single convergence point** between the two pipelines is `memory_search`: the agent naturally searches both digital and physical sources during retrieval
- **The daily distillation layer is unique to the perception pipeline:** OpenClaw natively has no nightly summary mechanism; distillation from daily logs to MEMORY.md relies entirely on the model's in-session judgment. The perception pipeline's nightly job fills this intermediate layer—itself a design finding for RQ3

### 3.2 Nightly Summarization

**👉 Nightly job enabled**, producing two outputs per run:

1. **physical-insights/YYYY-MM-DD.md** — distills the day's physical-logs into noteworthy observations (new behaviors, anomalies, pattern deviations) and details the model judges important or potentially useful for future personalization, even if not yet part of a confirmed pattern.
2. **physical-pattern.md updates** — compares today's insights against existing patterns; adds new patterns, strengthens confirmed ones, flags deviations.

**Design rationale:** A per-batch summary captures "user is cooking right now." A nightly summary captures "user cooks every evening around 6pm." Only the latter is a durable personalization signal. The two-output structure separates ephemeral daily details (insights, subject to temporal decay) from persistent behavioral patterns (pattern file, always available to retrieval).

**🧪 Experiment variable:** Nightly summarization prompt wording (iterated during Phase 0). Compare agent behavior with physical-pattern.md present vs. absent.

### 3.3 Retention Policy

**🔒 Locked:** 14-day rolling retention for raw frames and perception logs. After 14 days, raw data is deleted; only physical-pattern.md and any information the nightly job promoted to persistent storage remain.

This is both a privacy measure and a practical constraint (storage). It also creates a natural experimental boundary: after 14 days, the agent must rely on its own memory abstractions, not raw data.

### 3.4 Retrieval & Context Loading

Writing files into `memory/` makes them searchable, but searchability alone does not guarantee the agent will use physical-world information. OpenClaw has three distinct visibility levels for memory content, and each perception file maps to the appropriate one.

**Background: OpenClaw's native memory visibility**

OpenClaw surfaces memory through three mechanisms, in descending order of visibility:

1. **Bootstrap injection (system prompt, every turn).** A hardcoded set of workspace files—AGENTS.md, SOUL.md, USER.md, IDENTITY.md, TOOLS.md, HEARTBEAT.md, MEMORY.md—is injected into the system prompt and present on every turn of every session. The agent always "sees" this content without needing to take any action.

2. **Session-start read (agent tool call, once per session).** AGENTS.md contains the instruction: "On session start, read today + yesterday + memory.md if present." The agent executes `read` / `memory_get` tool calls at session start, pulling the content of today's and yesterday's daily logs (`memory/YYYY-MM-DD.md`) into the conversation context. This content persists for the session but is not in the system prompt on every turn.

3. **On-demand retrieval (`memory_search`).** All files under `memory/` are indexed by BM25 + vector hybrid search. The agent calls `memory_search` when a query is relevant; results are returned as snippets. Temporal decay based on filename date ensures recent files rank higher.

**Perception file visibility mapping:**

| File | Visibility level | Mechanism | Rationale |
|------|-----------------|-----------|-----------|
| `physical-pattern.md` | Bootstrap injection (every turn) | `agent:bootstrap` hook adds it to the bootstrap file list | Persistent patterns are short and must always be visible—the agent needs to "know" the user cooks at 6pm without searching for it |
| `physical-insights/YYYY-MM-DD.md` (today + yesterday) | Session-start read | AGENTS.md instruction extended to include these files | Daily distillation is concise enough for session context; agent should be aware of recent physical-world highlights without needing a search query |
| `physical-logs/YYYY-MM-DD.md` | On-demand retrieval | Automatic `memory_search` indexing (no configuration needed) | Full-volume batch observations are too large for session context; retrieved only when the agent's query is semantically relevant |

**Implementation: pluggable, zero source code modification**

Both context loading mechanisms use OpenClaw's existing extension points:

1. **`agent:bootstrap` hook for `physical-pattern.md`.** OpenClaw's built-in `bootstrap-extra-files` hook (or a custom `agent:bootstrap` hook) can inject additional files into the bootstrap file list. The hook is a small TypeScript function placed in `~/.openclaw/hooks/`; it intercepts the `agent:bootstrap` event and appends `memory/physical-pattern.md` to `context.bootstrapFiles`. This file is then injected into the system prompt alongside MEMORY.md on every turn. OpenClaw updates do not affect hooks in the user's hooks directory.

2. **AGENTS.md instruction for `physical-insights/`.** The "Every Session" section in AGENTS.md is extended with one line:
   ```
   Also read memory/physical-insights/YYYY-MM-DD.md for today and yesterday if present.
   ```
   The agent will execute this as a `read` tool call at session start, identical to how it reads native daily logs. AGENTS.md is a user-editable workspace file, not part of OpenClaw's codebase.

3. **`physical-logs/` requires no configuration.** Any `.md` file under `memory/` is automatically indexed by `memory_search`.

**Context budget considerations:**

Bootstrap-injected files consume tokens on every turn. `physical-pattern.md` must be kept concise—this is already enforced by its design (single file, only durable cross-day patterns, maintained by the nightly job). The per-file bootstrap limit is configurable (`bootstrapMaxChars`, default 65,536 characters); truncation is automatic if exceeded.

Session-start reads of `physical-insights/` add to the conversation context once per session. Two days of daily insights (today + yesterday) should be short—each file is a brief summary of noteworthy observations, not a full log.

**Parallel with OpenClaw's native architecture (updated):**

|  | Digital (OpenClaw native) | Physical (perception pipeline) |
| --- | --- | --- |
| Bootstrap injection | `MEMORY.md` | `physical-pattern.md` (via hook) |
| Session-start read | `memory/YYYY-MM-DD.md` (today + yesterday) | `physical-insights/YYYY-MM-DD.md` (today + yesterday, via AGENTS.md) |
| On-demand retrieval | All `memory/**/*.md` | `physical-logs/YYYY-MM-DD.md` (automatic) |

This three-tier visibility mirrors OpenClaw's native architecture exactly: persistent knowledge is always visible, recent context is loaded at session start, and historical detail is retrieved on demand. The perception pipeline extends each tier without modifying the mechanisms themselves.

---

## Implementation Priorities

### Sprint 1 (Days 1-3): Minimum Viable Pipeline
1. Adaptive interval capture (start with fixed max_interval, add trigger-based adjustment)
2. Basic preprocessing: black frame + blur detection + pixel similarity deduplication
3. Per-batch VLM inference with 1:1 batch mapping, fixed max window
4. Direct write to `memory/physical-logs/`
5. Verify `memory_search` indexes new files
6. Create `agent:bootstrap` hook to inject `physical-pattern.md` into bootstrap file list
7. Extend AGENTS.md "Every Session" instructions to read `physical-insights/` (today + yesterday)

**Goal:** End-to-end data flow from camera to OpenClaw memory. Quality doesn't matter yet. Prove the path works.

### Sprint 2 (Days 4-7): Multimodal + Dynamic Batching
6. Add IMU stationary/sustained_motion detector + Audio VAD + noise level computation
7. Attach tags to each frame
8. Implement two-stage batch boundary (sensor trigger + SSIM visual verification + max window)
9. Frame importance scoring (visual + audio + imu + sparsity)
10. Include tags in VLM prompt

**Goal:** Full multimodal pipeline with dynamic batching. Start wearing the device daily.

### Sprint 3 (Days 8-10): Nightly + Prompt Iteration
11. Nightly job producing physical-insights/ + physical-pattern.md
12. Iterate VLM prompt based on observed output quality
13. Tune preprocessing parameters (SSIM threshold, max window, importance score weights, adaptive interval ramp curve)

**Goal:** Pipeline stable enough for sustained daily use. Begin formal study period.

### Sprint 4 (Days 11-14): Observation + Iteration
14. Daily autoethnographic journal
15. Review physical-logs vs. physical-insights vs. physical-pattern.md progression
16. Identify failure modes and iterate

**Goal:** Collect data for thesis analysis. Document design decisions and their outcomes.

---

## Decision Summary Table

| Decision | Options | Chosen | Status | Experiment? |
|----------|---------|--------|--------|-------------|
| Architecture | Batch inference (Path A excluded by design argument) | Batch | Locked | — |
| Capture mode | Adaptive interval (min 3s / max 🧪) | Adaptive | Locked | max_interval: 15s / 20s / 30s; ramp curve |
| Audio trigger | VAD | VAD | Locked | — |
| Audio data | VAD tag + noise level tag / +transcription | VAD + noise level (no speaker count) | Locked | Transcription on/off |
| IMU trigger | Motion state change | Motion state change | Locked | — |
| IMU data | Binary: stationary / sustained_motion | Binary | Locked | — |
| Batch boundary | Sensor trigger + SSIM visual verification + max window | Two-stage | Locked | SSIM threshold; max window 10/15 min; upgrade to embedding similarity |
| Frame filter | Black + Blur + Dedup + Importance Score | All four | Locked | Importance score weights; K = 4–8 |
| Inference batch | 1:1 / Merge / Split | 1:1 | Default | Log failures, add merge/split if needed |
| VLM provider | Claude / GPT-4V | TBD | Open | Compare if budget allows |
| Context chaining | No context / Prior batch summary | Prior batch summary | Locked | — |
| Output format | Free-form / Structured | Structured with optional fields | Locked | Iterate prompt |
| Memory integration | Direct write to memory/ subdirectories | Direct write (three-tier) | Locked | Compare physical-logs vs. insights vs. pattern progression |
| Context loading | Bootstrap hook / AGENTS.md instruction / automatic indexing | Three-tier visibility (see 3.4) | Locked | — |
| Nightly job | Insights + pattern file | Yes | Locked | Prompt wording; pattern file presence vs. absence |
| Proactive cron | Frequency: hourly / 4h / 2x daily | Included from Phase 1 start | Locked | Frequency tuning during Phase 0 |
| Retention policy | 14-day rolling | 14-day | Locked | — |
