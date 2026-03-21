# 3. Design Rationale
This chapter justifies two foundational design decisions: selecting egocentric vision as the primary physical-world input modality, and choosing OpenClaw as the agent integration platform.

## 3.1 Egocentric Vision as Primary Modality
We select egocentric vision—first-person visual capture from a body-worn device—as the primary physical-world input, supplemented where useful by audio and inertial data. Four properties make it the strongest candidate for the personalization question this thesis investigates.

**Mobility.** Unlike fixed sensors that are bound to a single space and lose coverage the absence moment. An egocentric device moves with the wearer, enabling continuous capture across locations throughout the day—a prerequisite for the longitudinal patterns personalization depends on. This capability is reinforced by a new hardware trend: consumer smart glasses with cameras are going viral (Meta Ray-Ban, Brilliant Labs).

**Information density.** A first-person visual perspective captures environment, activity, and object interaction simultaneously within a single sensing channel (First-Person Vision (Kanade & Hebert, 2012)). Alternative modalities—audio, IMU, IoT sensors—each provide complementary but narrower signals.

**Implicit attention signal.** Egocentric capture is anchored to body orientation, so what recurrently appears in the field of view reflects what the user engages with; what is consistently absent suggests disinterest. This coarse attention pattern—not gaze tracking—is a personalization signal that screen-mediated interaction cannot yield.

**Technical maturity.** Vision-language models (VLMs) can now convert egocentric imagery into structured text descriptions of activities, objects, and context (Embodied VideoAgent (Fan et al., 2025); Vinci (Pei et al., 2025); EgoLife (Yang et al., 2025)).

Prior egocentric vision work operates on short benchmark recordings—minutes to hours of scripted activity (Ego4D (Grauman et al., 2022); EPIC-KITCHENS (Damen et al., 2021)). Personalization for a persistent agent depends on longitudinal patterns that only emerge over weeks of sustained capture. This study therefore adopts continuous daily recording over a multi-week period, using a smartphone worn on the body as a hardware proxy for dedicated wearable devices.

## 3.2 OpenClaw as Integration Platform
We build on OpenClaw (Steinberger, 2025), rather than creating a new agent or using closed platform for three reasons.

**Deployed baseline.** OpenClaw is one of the few open-source personal AI agents in sustained real-world use, with integrated tools, persistent memory, and continuous learning (Steinberger, 2025). Discovering where physical context helps requires a baseline that reflects actual use patterns, not toy scenarios.

**Integration opportunity.** OpenClaw personalizes through a workspace of plain markdown files—behavioral identity, user preferences, operating rules—loaded into the system prompt at session start. Persistent memory is organized as a curated long-term file and append-only daily logs, surfaced through BM25 and vector hybrid retrieval. Crucially, the memory ingestion interface is text-based by design: any new input channel that produces structured text can extend the user model without modifying the existing pipeline.

**Inspectability and format compatibility.** Every memory entry is stored as human-readable markdown, which is essential for answering RQ1 and RQ2: we must observe exactly how physical-world observations enter memory, persist alongside digital traces, and surface during interactions. Markdown also matches VLM output format directly—the pipeline from sensor capture to text summary to markdown memory requires no representation conversion.

These properties distinguish OpenClaw from alternatives that lack the inspectability or text-native storage this study requires.



---

These decisions define the system described in Chapter 4: an egocentric vision pipeline that captures physical-world context, processes it through VLMs into text, and writes those summaries into OpenCLAW's existing markdown memory.