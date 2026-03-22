## 5.1 Methodological Framework

**Research through Design.** The central methodological question is what design requirements emerge when a new input modality—egocentric perception—meets an existing agent memory architecture. No prior system has attempted this integration, so there is no established design to validate or benchmark against. **The appropriate method must support exploratory iteration rather than confirmatory evaluation**. Methods that presuppose a stable design (controlled experiments, benchmarking) or simulate the system without building it (Wizard-of-Oz) cannot resolve the open design decisions identified in Chapter 4—over a dozen experiment variables spanning capture timing, preprocessing thresholds, prompt design, and memory update frequency. (see Table 2) Research through Design (RtD) treats iterative building and deployment as the knowledge-generating activity itself *(Research through Design as a Method for Interaction Design Research in HCI (Zimmerman et al., 2007))*, making it the appropriate framework for a study where the design variables outnumber the settled decisions.

**Autoethnography.**RtD requires sustained deployment. The question is who deploys. Autoethnography—extended self-study by the designer-researcher—is selected for two reasons. Methodologically, the designer's intimate knowledge of the system enables diagnostic depth that external participants cannot provide: tracing a personalization failure to a specific pipeline stage rather than merely reporting that the agent's response was unhelpful (Autobiographical Design (Neustaedter & Sengers, 2012)). For a study whose primary contribution is design requirements (RQ3), this depth is essential. Practically, the system is a research prototype requiring daily pipeline monitoring, and always-on egocentric capture raises ethical and logistical barriers that exceed the scope of a master's thesis.

**Triple role and bias mitigation**.The researcher serves simultaneously as designer, participant, and analyst. **This triple role carries real bias risks**—most notably, the temptation to design structured probes that favor successful outcomes, or to unconsciously adjust daily routines to suit the pipeline's strengths. **Three mechanisms constrain this bias**: the perception log is produced automatically by the pipeline, independent of researcher judgment; interaction transcripts are recorded in full, not selectively recalled; and Phase 0 calibration is separated from Phase 1 observation, so that pipeline tuning does not contaminate the data collection period (see Section 5.2). These mechanisms reduce but do not eliminate subjectivity; the remaining limitations—single-subject generalizability, routine bias, interpretive self-reliance—are discussed in Section 7.3.

## 5.2 Study Design

The study has two phases: a calibration period preceding the formal study, followed by a two-week observation period.

\[**Table 1: Study phases**\]

|  | Phase 0: Calibration | Phase 1: Observation |
| --- | --- | --- |
| Duration | Pre-study (approx. 1 week) | 2 weeks |
| System state | Active iteration | All parameters frozen |
| Purpose | Stabilize pipeline; resolve open design variables | Collect data for RQ1, RQ2, RQ3 |
| Output | Iteration log (→ RQ3) | All data sources (→ RQ1, RQ2, RQ3) |

**Phase 0: Calibration.** The perception pipeline runs with active iteration permitted. Every modification is logged with its rationale and before/after output comparison. This phase produces no data for RQ1 or RQ2, but the iteration log is a primary data source for RQ3: design requirements are extracted directly from the record of what failed and what was revised. The following design variables are resolved during calibration:

\[**Table 2: Phase 0 design variables**\]

| Variable | Range | Resolution criterion |
| --- | --- | --- |
| maxInterval | Continuous | Stable scenes receive ≥1 frame per interval without exceeding daily token budget |
| rampRatio | Continuous | Post-trigger ramp-back produces dense event coverage without redundant frames in the following quiet period |
| ssimBoundaryThreshold | Continuous | Batch boundaries align with researcher-observed scene transitions in sampled cases; fallback: upgrade to embedding similarity if SSIM proves insufficient |
| firstBatchWindowSeconds | Continuous | First batch produces a coherent scene summary despite lacking a prior-batch tail for comparison |
| maxWindowSeconds | Continuous | Batches remain short enough for coherent single-scene summaries without splitting mid-activity |
| Importance score weights (wVisual / wAudio / wIMU / wSparsity) | Continuous per weight | Selected key frames cover each batch's main activity and transitions as judged by manual review |
| ssimDedupThreshold | Continuous | Duplicate removal eliminates near-identical frames without collapsing visually distinct moments within the same scene |
| kMin / kMax / kDensityPerMin | Continuous | Short batches retain enough frames for VLM context; long batches do not exceed the VLM's useful input range |
| scoreThreshold | Continuous | Guaranteed-inclusion threshold retains event-bearing frames without inflating output during uneventful periods |
| prompt wording | Iterative | VLM outputs describe user habits and context, not generic scene captions, across diverse real-world scenes |
| insight_prompt wording | Iterative | Rolling summary captures evolving intra-day context that individual batch outputs miss |
| pattern_prompt wording | Iterative | Cross-day profile extracts stable behavioral patterns rather than echoing today's episodic content |
| insight_min_batches / insight_min_minutes | Continuous | Summary stays current without triggering redundant updates during low-activity periods |
| nightly_hour | Discrete (local hour) | Late enough that the day's activity is complete; early enough that the pattern file is ready for the next morning's first session |
| Proactive cron frequency | Iterative | Generates sufficient decision points for analysis without overwhelming the researcher with notifications |

**Phase 1: Observation (2 weeks).** All pipeline parameters are frozen. The system runs continuously during waking hours, writing physical-world observations into OpenClaw's memory through the three-tier direct write strategy (physical-logs, physical-insights (rolling intra-day), [physical-pattern.md](http://physical-pattern.md) (nightly)) described in Section 4.5. Three observation methods operate in parallel.

- **Passive observation.** The researcher uses OpenClaw for daily tasks—scheduling, writing, planning, information lookup—without steering conversations toward physical-world topics.
  - *Protocol:* After each interaction, tag in the journal whether the agent's response referenced physical-world memory, and if so, whether the reference improved the response. No intervention is made to increase or decrease the likelihood of physical context surfacing.
  - *Example:* Asking the agent to draft a weekly plan; observing whether it accounts for the morning runs the pipeline logged.
- **Structured probes.** Once or twice daily, the researcher reviews the perception log, selects an entry where the pipeline captured information that could plausibly aid a task, and poses a request where that information is relevant but not explicitly mentioned.
  - *Protocol:* (1) Select a perception log entry. (2) Design a request that an agent with only digital traces would answer generically, but an agent with physical-world memory could answer specifically. (3) Pose the request to the agent. (4) Log the chain: perception entry → probe wording → agent response → whether physical-world memory surfaced. This is not a blind evaluation; the audit trail ensures traceability.
  - *Example:* Perception log shows the researcher worked from a café three afternoons this week. Probe: "suggest a workspace for this afternoon." An agent without physical-world memory defaults to generic suggestions; an agent with it references the café pattern.
- **Proactive cron.** A scheduled job triggers OpenClaw at a fixed interval (set during Phase 0) to review recent physical-world memory entries and decide whether to proactively contact the researcher.
  - *Protocol:* The agent either sends a message or decides not to act; both outcomes are logged with the agent's stated reasoning. The researcher does not influence the trigger or the decision.
  - *Example:* Cron fires after the pipeline logs four hours of stationary desk work. The agent decides whether to suggest a break based on prior movement patterns.

\[**Table 3: Observation methods compared**\]

|  | Passive observation | Structured probes | Proactive cron |
| --- | --- | --- | --- |
| Tests | Does physical-world memory surface organically? | Can the agent use physical context when the opportunity arises? | Can the agent judge when to act on physical context unprompted? |
| Isolates | Baseline utilization under natural conditions | "No opportunity to use" vs. "had information but failed to use" | Agent's autonomous judgment about when physical context warrants action |
| Frequency | All interactions during study period | 1–2 probes per day | Fixed interval (set in Phase 0) |
| Researcher intervention | None | Non-blind; audit trail logged | None |

These three methods are complementary lenses on the same deployment, not independent conditions; their combined output feeds the analysis described in Section 5.4.

## 5.3 Data Collection

The study produces two categories of data: automated records generated by the pipeline and agent independent of researcher judgment, and researcher-produced records that capture structured observations and reflections.

Three data sources are automated. The **perception log** stores every VLM output produced by the pipeline, unfiltered by OpenClaw's memory heuristics—the complete record of what egocentric capture made visible. The **three-tier memory output** (Section 4.5)—physical-logs, physical-insights, and physical-pattern.md, alongside OpenClaw's native daily logs and MEMORY.md—records what the memory architecture retained, distilled, or discarded at each tier. Together with the perception log, it forms a paired record: what the pipeline produced versus what the memory architecture preserved. **Interaction transcripts** record every conversation with OpenClaw during the observation period in full, including natural interactions, structured probes, and proactive messages initiated by the cron job. Proactive messages are logged as a distinct interaction type, annotated with the agent's stated reasoning for acting or declining to act.

Two data sources are researcher-produced. The **design iteration log** from Phase 0 records every pipeline modification with its rationale and before/after output comparison, documenting the design decisions that shaped the final system configuration.

The **autoethnographic journal**, maintained throughout Phase 0 and Phase 1, is the sole data source that captures researcher interpretation—judgments that require knowing both the pipeline's internals and the lived context that automated records cannot represent. Interaction transcripts record what the agent said; the perception log records what the pipeline captured; only the journal records why a response felt helpful, what information should have surfaced but didn't, or what the researcher was actually doing when the pipeline misclassified a scene. The journal therefore focuses exclusively on interpretive assessment and does not duplicate transcription or pipeline output.

Each day includes two structured entries. A **mid-day check-in** (\~5 minutes), recorded after the first few OpenClaw interactions, captures interaction assessments while the context is fresh: per-interaction judgments of whether physical context surfaced and whether it was useful, plus the design intent behind any structured probes conducted that morning. An **end-of-day reflection** (\~15 minutes) synthesizes the full day: a utilization summary counting physical-context surfacing across observation methods, missed opportunities identified by comparing the day's perception log against actually experienced events, noise or irrelevance cases, pipeline behavior observations, and free-form reflection. During Phase 0, the end-of-day entry includes an additional field documenting any pipeline modifications made that day—this overlaps with the design iteration log but adds narrative context that structured modification records lack. During Phase 1, this field is replaced by a standing notation for issues observed but not acted on, preserving the frozen-parameter constraint.

The two-entry rhythm serves a methodological purpose: mid-day entries guard against the memory decay that would distort end-of-day recall of morning interactions, while end-of-day entries enable cross-referencing between the perception log and lived experience that mid-day entries cannot yet perform (the perception log accumulates throughout the day). The total journaling commitment—approximately 20 minutes per day over 14 days—is designed to sustain consistent data quality without inducing fatigue-driven attrition.

\[**Table 4: Data sources**\]

| Data source | Production | Content | Collection period | Feeds analysis stage |
| --- | --- | --- | --- | --- |
| Perception log | Automated (pipeline) | All VLM outputs, unfiltered | Phase 1 | Content classification; three-tier memory flow |
| Three-tier memory output | Automated (pipeline + OpenClaw) | physical-logs, physical-insights, physical-pattern.md changes, plus OpenClaw native memory changes | Phase 1 | Three-tier memory flow |
| Interaction transcripts | Automated (OpenClaw) | All conversations: passive, probe, and proactive; annotated by type | Phase 1 | Interaction-level coding |
| Design iteration log | Researcher-produced | Pipeline modifications with rationale and before/after comparison | Phase 0 | Thematic analysis |
| Autoethnographic journal | Researcher-produced | Twice-daily structured entries: interaction assessments, probe design intent, utilization counts, missed opportunities, noise cases, pipeline observations, reflections | Phase 0 + Phase 1 | All stages (interpretive supplement) |

\[**Table 5: Journal entry structure**\]

| Field | Entry | What it records | Why automated sources cannot substitute |
| --- | --- | --- | --- |
| Interaction assessment | Mid-day | Per-interaction judgment: did physical context surface, and was it useful? | Transcripts record content; the journal records evaluative judgment and reasoning |
| Structured probe intent | Mid-day | Why a perception log entry was selected and what the probe was designed to test | Probe design rationale exists only in the researcher's reasoning until recorded |
| Utilization summary | End-of-day | Counts of physical-context surfacing by observation method | Aggregation requires researcher judgment about what counts as "surfacing" |
| Missed opportunities | End-of-day | Information the pipeline captured (or should have) that the agent failed to use, with diagnosis of where the chain broke | Only the researcher knows what they experienced and can identify the gap |
| Noise / irrelevance | End-of-day | Cases where physical context surfaced but was unhelpful or distracting | Requires subjective assessment of response quality in context |
| Pipeline behavior | End-of-day | Technical observations about capture density, batch quality, memory tier behavior | Requires system-level interpretation beyond raw log inspection |
| Reflection | End-of-day | Free-form observations, emerging patterns, design intuitions | Unstructured interpretive space for themes that resist structured fields |

## 5.4 Analysis

Analysis proceeds in four stages, each building on the prior stage's output.

**Content classification (→ RQ1).** All perception log entries are categorized by information type through open coding—categories emerge from the data rather than a predefined taxonomy, though initial passes are guided by the broad domains summarized in Table 5. The resulting classification is compared against the digital traces available during the same period—OpenClaw's pre-existing memory entries, calendar events, and chat logs—to identify information categories that are exclusively or primarily accessible through physical-world observation. Cross-entry temporal patterns—recurring routines, schedule regularities—are identified during aggregation rather than coded at the individual entry level.

\[**Table 6: Initial content classification domains**\]

| Domain | What it captures |
| --- | --- |
| Activity | What the user is doing (cooking, working, exercising) |
| Environment | Where the user is and what the space looks like (home office, café, kitchen) |
| Objects | What objects the user interacts with (groceries, books, equipment) |
| Social context | Who is present, whether conversation is occurring |

**Interaction-level coding (→ RQ2).** Each interaction transcript is coded for the role physical-world information played. \[The journal's per-interaction assessments (Section 5.3, Table 5) serve as an initial interpretive pass—recording whether physical context surfaced and whether it helped while the interaction is fresh. The systematic coding described here is a second pass applied to the full transcript corpus after Phase 1, using the journal assessments as an interpretive anchor but coding independently from the transcript text itself.\] The initial coding scheme is summarized in Table 7; codes are iteratively refined as sub-patterns emerge during analysis. Coding is performed across all three observation methods (passive, structured probe, proactive cron), enabling comparison along two dimensions: whether the agent uses physical context spontaneously versus only when prompted, and whether proactive surfacing changes utilization patterns.

\[**Table 7: Initial interaction-level codes**\]

| Code | Definition |
| --- | --- |
| Useful | Physical context improved response relevance |
| Unused | Relevant physical information existed in memory but was not surfaced |
| Irrelevant | Physical context surfaced but did not help or distracted |
| Absent | Interaction type where physical context has no bearing |

**Three-tier memory flow analysis (→ RQ3).** The three-tier memory output described in Section 5.3 is analyzed through entry-level tracing across tiers: each perception log entry is followed through physical-logs (was it written?), physical-insights (was it retained in the intra-day distillation?), and physical-pattern.md (did it contribute to a persistent pattern?). This is supplemented by category-level aggregation to identify systematic patterns—whether certain information types are consistently lost during intra-day distillation, whether the pattern update produces false patterns, and which tier the agent's retrieval mechanism actually surfaces during interactions. The analysis also examines the three-tier visibility design: whether bootstrap injection of physical-pattern.md causes the agent to use persistent patterns naturally, whether session-start loading of physical-insights changes agent behavior compared to on-demand retrieval from physical-logs, and where information is lost or distorted across the pipeline.

**Thematic analysis of journal and iteration log (→ RQ3).** Recurring themes across daily reflections and Phase 0 design iterations are extracted following reflexive thematic analysis *(Thematic Analysis (Braun & Clarke, 2006))*. Codes are generated inductively from the data, grouped into candidate themes, and reviewed against the full dataset. These themes feed the design implications presented in Chapter 7.

A final cross-cutting analysis links the first two stages: the content classification from RQ1 is mapped against the interaction-level codes from RQ2 to determine whether certain information types are inherently more useful for personalization, or whether utility depends primarily on task context. 

**Credibility.** Single-researcher autoethnography requires explicit credibility mechanisms to constrain interpretive bias. Four are employed. First, **audit trail**: the perception log, interaction transcripts, and iteration log are recorded automatically, ensuring that every analytic inference is traceable to source data rather than reconstructed from memory. Second, **negative case analysis**: the analysis deliberately seeks interactions where physical context should have helped but did not, or where it introduced noise, guarding against confirmatory selection of supportive examples. Third, **thick description**: findings (Chapter 6) present extended interaction excerpts with full context—the perception log entry, the agent's response, and the researcher's assessment—so that readers can evaluate interpretive claims against the primary data. Fourth, **peer debriefing**: coding samples and emerging themes are reviewed with the thesis advisor at two checkpoints (mid-study and post-analysis) to surface blind spots that single-coder analysis risks missing. The journal's reflection field (Table 5) additionally functions as a **reflexivity audit**—a daily record of the researcher's evolving assumptions and interpretive tendencies, available for review during thematic analysis to detect patterns of self-serving interpretation.
