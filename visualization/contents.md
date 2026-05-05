# Script Arc

Cover 结尾抛出两个问题：
- **Q1：这个未来还有多远？** → 对应系统设计的探索（14-34）
- **Q2：如何让这个未来是我们想要的？** → 对应反思与讨论（43-46）

**02-09 Intro**：快速建立背景，不卖力。04-07 对建筑背景听众意义有限，script 极度压缩，点到为止。

**10-13 The Blind Spot**：全场最关键的转折。把情绪顿住，说清楚 agent 现在只活在数字世界里，physical world 是盲区。13 的三个 RQ 是 Q1 的具体形式。

**14-27 Design Rationale + System Design**：回答 Q1 前半段"我是怎么做的"。听众是建筑系，不要陷入工程细节。重点是逻辑，不是技术。Pipeline 逐层讲要保持呼吸感，让图说话。

**28-34 Study Design**：回答 Q1 后半段"我是怎么验证的"。自传式民族志对建筑系易理解。32 头戴 iPhone 可以轻松自嘲。33-34 过程透明度是亮点，建筑人重视过程。

**35-42 Results**：Q1 与 Q2 的交界。36 Photo Wall 让它安静展示，script 短。**40-41 Floor Plan + Fusion Map 对这个房间里的人最有共鸣，给充分时间。** 42 是从数据到语言的转折，Q2 的开场。

**43-46 Discussion**：正式回答 Q2。45 Limitations 不是道歉，是说清楚这个未来的边界在哪里。46 Conclusion 呼应 Cover 的"imagining a future"，轻落。

---

# Slides

- **Cover（01）**：Physical-World Observation — cyber lobster cover
- Intro
    - **The Claw（02）**：section cover — "INTRO"
    - **Personal AI Agents are Here（03）**：AI assistant vs. AI agent 的区别
    - **The OpenClaw Fever（04）**：9图展示 OpenClaw 的火热
    - **What is OpenClaw?（05）**：介绍 OpenClaw
    - **OpenClaw's Spreading（06）**：地图展示 OpenClaw 全球分布
    - **OpenClaw's GitHub Stars Growth（07）**：GitHub stars 增长曲线
    - **Defining Personalization（08）**：三列对比 — System / AI / Human 视角
    - **Why Personalization Matters（09）**：Agents that know you >> Agents that don't
- The Blind Spot
    - **The Blind Spot（10）**：section cover — 黄底黑圆盲点视觉
    - **The Two Worlds（11）**：左右分屏 SVG，digital traces vs. physical world 缺失
    - **Research Landscape（12）**：XY 散点图，横轴 human augmentation ↔ agent personalization，纵轴 digital ↔ physical，本研究高亮空白区
    - **Research Questions（13）**：RQ1（可见性）/ RQ2（任务情境）/ RQ3（设计需求）
- Design Rationale
    - **Design Rationale（14）**：section cover — "DESIGN RATIONALE"
    - **Why Egocentric Vision?（15）**：Mobility / Information Density / Implicit Attention / Technical Maturity
    - **Why OpenClaw Integration?（16）**：Deployed baseline / Open source / Markdown workspace
    - **How OpenClaw Works（17）**：Memory-centric architecture — Markdown Workspace + SQLite-vec retrieval，Closed-Loop Personalization
- System Design
    - **System Design（18）**：section cover — "SYSTEM DESIGN"
    - **Abstract Pipeline（19）**：The Core Focus: Strategic Compression — annotated pipeline overview
    - **Multi-layer Pipeline（20）**：完整多层 pipeline 数据流图
    - **Layer 1 & 1.5（21）**：iOS capture (VAD + IMU) + on-device keyframe selection
    - **Capture Monitor（22）**：双面板 UI — Settings/Parameters + Real-time Monitor
    - **Layer 2 — Inference（23）**：VLM API call，Prompt Assembly（Log Prompt + Batch frames + Prior Context）
    - **Layer 3 — Memory（24）**：3-tier 写入 — physical-logs / physical-insights / physical-pattern.md
    - **Server Monitor（25）**：双面板 UI — Settings/Parameters + Real-time Monitor（服务端）
    - **Layer 3.5 — Retrieval（26）**：SQLite-vec 检索循环
    - **Full Pipeline Overview（27）**：全链路总览
- Study Design
    - **Study Design（28）**：section cover — lobster + "STUDY DESIGN"
    - **Study Design Overview（29）**：Phase 0（校准）→ Phase 1（观察，2周），三种观察方法
    - **Data Collection（30）**：数据采集指标与分组
    - **Study Design Protocol（31）**：6格 storyboard SVG — 穿戴捕获 / 被动观察 / 结构化探针 / 主动 cron / 午间评估 / 深夜复盘
    - **Study Device（32）**：设备对比展示
    - **Design Iteration Log（33）**：双面板 UI — Iteration Form + Context & History
    - **Autoethnographic Journal（34）**：双面板 UI — Journal Form + Context & History
- Results
    - **Results（35）**：section cover — "RESULTS"
    - **Photo Wall（36）**：egocentric 截图照片墙
    - **Activity Rhythm（37）**：活动节律热图（按天/时段）
    - **Object Network（38）**：物体共现力导向图
    - **Sankey Diagram（39）**：Location → Social Context → Activity 能量流向图
    - **Floor Plan（40）**：带房间访问频次注释的平面图
    - **Fusion Map（41）**：多维数据融合可视化
    - **What the Agent Learned About Me（42）**：physical-pattern.md 中的 agent insights 卡片（饮品规律 / 厨房循环 / 等）
- Discussion
    - **Discussion — RQs（43）**：每条 RQ 的 FINDING + LIMIT / PEAK + NOISE / REQ
    - **Moments of Connection & Disconnection（44）**：成功案例（推断攀岩）+ 失败案例（VLM 幻觉"清洁冰箱线圈"）
    - **System Limitations（45）**：两周部署中发现的系统瓶颈
    - **Conclusion（46）**："The Biographer Has Opened Its Eyes." — manga 三格
- **Thank You（47）**：致谢
- Appendix
    - **Appendix（48）**：section cover — "APPENDIX"
    - **Behavioral Profile（49）**：physical-pattern.md 行为档案示例
    - **System Prompts 1/2（50）**：系统提示词第一页
    - **System Prompts 2/2（51）**：系统提示词第二页
    - **Raw Data Log Example（52）**：实时原始日志示例（live data）
    - **System Parameters（53）**：系统参数表
