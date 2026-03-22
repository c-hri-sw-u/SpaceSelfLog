# Chapter 4 (System Design) — Writing & Experiment Instructions

## Position in Thesis

The design space is NOT a standalone chapter. It is the argumentative backbone of Chapter 4 (System Design). The design-space.md file is a working document for decision-making; the thesis chapter transforms those decisions into narrative prose with design reasoning.

## Chapter 4 Structure

- **4.1 Pipeline Overview** — Architecture diagram + one-page data flow (capture → preprocess → inference → memory)
- **4.2 Capture Layer** — Vision + Audio + IMU roles, dual role distinction (trigger vs. data source), adaptive interval capture reasoning
- **4.3 Preprocessing** — Why preprocess (token cost, info density), two-stage batch boundary design (sensor trigger + SSIM visual verification), frame filtering with importance scoring
- **4.4 Inference** — Why batch over per-frame (design argument to exclude Path A), VLM prompt design, output format
- **4.5 Memory Integration** — Direct write strategy (three-tier: physical-logs / physical-insights / physical-pattern.md), three-tier visibility mapping (bootstrap injection / session-start read / on-demand retrieval), nightly summarization, retention policy
- **4.6 Implementation** — Tech stack, hardware, timeline

## Writing Pattern Per Decision Point

For each design decision within each section:
1. **Present the design space** — briefly show what options exist (2-3 sentences)
2. **State your choice + reasoning** — why this option best serves your RQs (the bulk of the argument)
3. **Dismiss alternatives concisely** — one or two sentences per rejected option explaining why not

Do NOT exhaustively enumerate every option with equal depth. The chosen path gets full treatment; rejected paths get brief design-argument dismissals.

## Experiment Scope

- **Path A (per-frame inference) does not need to be implemented.** Exclude via design argument (inferior information density, higher API cost, no cross-frame reasoning). This is legitimate in RtD.
- **Path B is the sole implementation path.** Within Path B, not every sub-option needs empirical testing. Most decisions are justified by design reasoning alone.
- **Experiment variables (marked 🧪 in design-space.md)** are the subset of decisions explored during the study: adaptive interval max_interval and ramp curve, SSIM threshold, batch max window size, importance score weights, prompt wording, nightly summarization prompt wording and pattern file presence vs. absence, proactive cron frequency, transcription on/off. These produce findings for RQ3.
- **This is Research through Design, not an ablation study.** You do not need to empirically prove every design choice. You need informed decisions with clear reasoning.