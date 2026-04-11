# 29_study_design_protocol.html | Storyboard SVG Design Plan

This document outlines the SVG graphic definitions and composition layout for the 6-panel storyboard that visualizes the Autoethnographic Study Design. 

The aesthetic is strictly "Exhibition Minimalism", adhering to:
- Muted lines (`stroke-width="0.5"`, `stroke="#ccc"`)
- Subtle fills (`fill="#d8d8d8"`, `fill="#f9f9f9"`)
- Thematic yellow highlighting (`#ffe94d`) to map directly to core methodology components.
- Completely based on simple geometric SVG primitives and Bezier paths that are inherently lightweight and perfectly crisp.

## Panel 1: 物理穿戴与日常捕捉 (Continuous Wear & Capture)
**Objective:** Visualize the "always-on" base condition of the deployment.
- **SVG Composition:**
  - **Character Outline:** A continuous minimalist Bezier `<path>` tracing the profile (forehead, nose, chin, neck, chest, back) representing the researcher.
  - **The Device:** A solid `#333` `<rect>` positioned at the chest, held by a thin strap `<line>`.
  - **The Capture:** A yellow-to-transparent `<polygon>` or `<path>` radiating forward from the device forming the FOV cone, overlaying the environment.
- **Complexity rating:** Simple. Achievable with ~10 clear coordinate points for the body profile.

## Panel 2: 无意识的自然使用 (Passive Observation)
**Objective:** Visualize using the agent organically without steering the conversation toward physical topics.
- **SVG Composition:**
  - **Context:** A simple paper coffee cup resting on a minimalist surface (composed of simple `<rect>` and `<polygon>`). 
  - **Action:** A hand outline `<path>` holding a smartphone. 
  - **The AI Interaction:** Above the phone screen, 3 distinct chat bubble outlines `<rect rx="2">`. The top two are standard `#ccc`, but one element inside the bot's reply bubble is a solid yellow `#ffe94d` bar, demonstrating physical context naturally emerging.
- **Complexity rating:** Low. Uses standard UI motifs and geometric objects.

## Panel 3: 处心积虑的探针测试 (Structured Probes)
**Objective:** Visualize the calculated crafting of a test prompt based on raw log reviews.
- **SVG Composition:**
  - **Posture:** The character's silhouette seated at a desk, leaning forward slightly (two bent elbows/arms drawn with `<path>`).
  - **The Workstation:** A wide monitor screen.
  - **The Interface:** Split-screen layout inside the monitor. Left side contains dense, tiny gray rectangles representing the unedited Daily Log. Right side contains a text-input box with a thick `#ffe94d` stroke, out of which an arrow `<polygon>` points toward the AI core.
- **Complexity rating:** Moderate. Relies heavily on geometric arrangement rather than complex organic paths.

## Panel 4: 被动干预与系统决断 (Proactive Cron)
**Objective:** Visualize the AI interrupting a physical, non-digital task.
- **SVG Composition:**
  - **Physical Task:** A clear overhead/angle view of a frying pan `<circle>` and a spatula `<path>` indicating the user is busy in the physical world.
  - **The Device:** Resting on the edge of the frame.
  - **The Interruption:** Concentric vibrating waves (arcs or `<circle>` with varying `opacity`) radiating from the device in bright `#ffe94d`, indicating an unprompted chime/notification. 
- **Complexity rating:** Low. Pure geometric shapes symbolizing action and notification.

## Panel 5: 午间评估 (Mid-Day Assessment)
**Objective:** Depict the active "evaluation" task the user does mid-day to score system flags.
- **SVG Composition:**
  - **Environment Anchor:** A minimalist wall clock showing 12:00 surrounded by a subtle dotted `<circle>` aura for the high-noon sun.
  - **Action:** A perspective laptop computer placed on a flat desk line, with two overlaid typing hands interacting directly with the keyboard.
  - **Synthesis:** The laptop screen displays a "Mid-day Check-in" list. It shows a series of checkmark boxes (`<rect>` and `<path>`), with one active row currently highlighted in yellow being scored/evaluated.
- **Complexity rating:** Moderate. Standardizes equipment format with Panel 6 while distinguishing the task interface.

## Panel 6: 深夜的复盘对抗 (End-of-day Reflection)
**Objective:** Illustrate the deep 15-minute comparison between "lived context" and "system output", focusing sharply on the human element of active reflection.
- **SVG Composition:**
  - **Environment Anchor:** A simple crescent moon `<path>` to firmly establish "End of the Day".
  - **Action:** A perspective laptop computer placed on a flat desk line.
  - **Synthesis (Concrete Visual):** 
    - The laptop screen displays a centralized "Reflection Diary" UI block.
    - Prominent focus is given to active text input: featuring typing layout lines, an active blinking cursor `|`, and a strongly highlighted yellow active block to visually isolate and elevate the act of the user writing their reflections against the system.
- **Complexity rating:** Low. Clear, geometric UI framing within a stylized desktop setting.

---

### Feasibility Statement
All 6 illustrations use core scalable vector paths (`M`, `L`, `C`, `A` coordinates) and native SVG tags (`line`, `rect`, `circle`). Keeping the entire drawing in monochrome vector limits rendering logic and matches the precise exhibition styling perfectly. I am capable of encoding these exact representations directly into the `29_study_design_protocol.html` DOM.
