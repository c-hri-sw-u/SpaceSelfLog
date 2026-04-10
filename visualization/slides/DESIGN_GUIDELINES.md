# Personal AI Agent Slide Deck - Design System & Guidelines

This document records the visual guidelines, typography scales, and CSS component structures established for the "Personal AI Agent" slide deck. This ensures absolute aesthetic consistency across all future slide additions.

## 1. Core Aesthetic Philosophy
* **Exhibition Minimalism ("高级展厅艺术美学")**: Zero unnecessary boxes, no heavy drop-shadows, and no card-style grey backgrounds. We rely on pure whitespace to separate information.
* **Diagram-Centric (图例为主)**: Visual communication relies primarily on Diagrams, Data Maps, Distribution Dots, and Geometries. 
* **Zero Meta-Headers**: Slides MUST NOT have traditional titles, slide numbers, context headers, meta-tags (like `03 // Topic`), or index labels. Let the layout and statement stand entirely on their own.
* **Typographic Hierarchy**: Heavy contrast between deep bold titles and subtle grey descriptive text. Text is reserved ONLY for critical, high-impact statements. Less is more.
* **Strict Proportional Scaling**: **All** spacing, font-sizes, and metrics must use `vw` (Viewport Width) units. This guarantees the layout preserves 100% of its aspect ratio geometry regardless of the projector or screen resolution. *Total vertical spacing must safely remain under `56vw` to avoid overflowing standard 16:9 displays (`100vh`).*

## 2. Color Palette
* **Background**: Pure white (`#ffffff`).
* **Primary Text**: Deep stark black (`#111111`) for maximum contrast.
* **Secondary Text (Descriptions/Dimmed)**: `color: #666666`, `#888888`, or `#999999` for progressive visual hierarchy and fading out "old paradigms".
* **Brand Accent**: **`#ffe94d`** (Pure bright yellow).
  * **Usage**: Extensively used as a marker tag `class="highlight"` framing key words. 
  * *CSS Snippet*: `background: #ffe94d; padding: 0 0.2vw; color: #111;`

## 3. Typography Scale & Layout
**Font Family**: `'Helvetica Neue', Helvetica, Arial, sans-serif`

* **Master Slide Wrapper**:
  ```css
  body {
    width: 100vw; height: 100vh;
    display: flex; flex-direction: column; justify-content: center;
    padding: 0 8vw; /* Horizontal padding, let flex handle vertical */
    color: #111; background: #fff; overflow: hidden;
  }
  ```
* **H1 (Main Headline)**: `font-size: 3.8vw; font-weight: 700; letter-spacing: -0.02em; margin-bottom: 1vw;`
* **Intro / Subtitle**: `font-size: 1.4vw; font-weight: 400; color: #666; max-width: 65vw; line-height: 1.4;`
  * *Emphasized Keywords in Intro*: Wrap in `<strong>` and apply `color: #111; font-weight: 600;`
* **H2 (Column / Section Headers)**: `font-size: 1.8vw; margin-bottom: 2.5vw;` 
  * `font-weight: 400; color: #999;` (For inactive/comparative sections)
  * `font-weight: 700; color: #111;` (For primary/current topic focus)
* **Body Text (p)**: `font-size: 1.1vw; line-height: 1.4; color: #888` (or `#444` for primary emphasis).

## 4. Common Components

### A. The "Highlight" Span
Whenever a concept needs tying to the core brand identity, wrap it in `<span class="highlight">Word</span>`.

### B. Clean Multi-Column Layout (The Center Divider)
Instead of boxing columns, let them float in whitespace separated by a single pristine hairline.
```css
.comparison-container {
  display: flex; gap: 8vw; position: relative;
}
.comparison-container::after {
  content: ''; position: absolute; left: 50%; top: 0; bottom: 0;
  width: 0.1vw; background: #eee; transform: translateX(-50%);
}
```

### C. Traits / Information Blocks
Standardized layout for bullet points/features using Emojis/Icons.
```html
<div class="trait">
  <div class="trait-icon">🚀</div>
  <div class="trait-text">
    <h3>Title</h3>
    <p>Description text here.</p>
  </div>
</div>
```
* **Icon Aesthetic Control (Very Important)**:
  By default, Emojis can look too "startup-like". To make them fit the "Premium Exhibition" aesthetic, we suppress them using CSS filters for passive text:
  * *Inactive/Past state*: `filter: grayscale(100%); opacity: 0.5;`
  * *Active/Future state*: `filter: grayscale(0%); opacity: 1;`

## 5. Cover Image & Generative Prompt Guidelines
When generating images for full-screen cover slides (e.g., the System Design Lobster), adhere to this prompt structure and style constraints to maintain visual consistency:
* **Background requirement**: Explicitly ask for the object to be isolated on a **solid vibrant yellow background (`#ffe94d`)**. This matches the presentation's brand color. 
* **Contrast and details**: Ask for highly detailed, ultra-realistic **black and white photography**. The stark black and white object against the pure yellow background is core to the exhibition quality.
* **Lighting and Quality**: Emphasize "high-end macro studio photograph," "cinematic studio photography style," and "sharp professional exhibition quality."
* **Art Style**: Ensure the result is photorealistic, not drawn or comic-like. Use phrases like "**NOT an illustration, NOT a drawing, 100% photorealistic studio shot**."
* **Example Prompt**: *"A high-end macro studio photograph of a highly detailed, biological lobster with high-tech mechanical cybernetic modifications... rendered in ultra-realistic black and white photography style, while isolated perfectly on a solid vibrant yellow background (#ffe94d)... Minimalist, aggressive, cinematic studio photography style, sharp professional exhibition quality. NOT an illustration, NOT a drawing, 100% photorealistic studio shot."*

