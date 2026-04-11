/**
 * ACTIVITY_THEME
 * Unified color configuration for all slides.
 */
const ACTIVITY_THEME = {
  "Focused Work": "#474747",
  "Learning & Review": "#3b82f6",
  "Life Maintenance": "#ec4899",
  "Movement & Transit": "#fbbf24",
  "Rest & Leisure": "#10b981",
  "Sleep / Untracked": "#dddddd",
  "Fitness & Well-being": "#be123c",
  "Other": "#94a3b8"
};

/**
 * Unified emoji mapping for activities.
 */
const ACTIVITY_EMOJI = {
  "Focused Work": "💻",
  "Learning & Review": "📖",
  "Life Maintenance": "🏠",
  "Movement & Transit": "🚶",
  "Rest & Leisure": "🌿",
  "Sleep / Untracked": "💤",
  "Fitness & Well-being": "🏃",
  "Other": "？"
};

/**
 * Get formatted label with emoji.
 */
function getActivityLabel(act, withEmoji = true) {
  if (!withEmoji) return act;
  const emoji = ACTIVITY_EMOJI[act] || ACTIVITY_EMOJI["Other"];
  return `${emoji} ${act}`;
}

/**
 * Automatically inject CSS variables into :root for styling.
 */
(function injectTheme() {
  const root = document.documentElement;
  const mapping = {
    "Focused Work": "--c-focus",
    "Learning & Review": "--c-learn",
    "Life Maintenance": "--c-maint",
    "Movement & Transit": "--c-move",
    "Rest & Leisure": "--c-rest",
    "Sleep / Untracked": "--c-sleep",
    "Fitness & Well-being": "--c-fitness"
  };

  Object.entries(mapping).forEach(([act, varName]) => {
    if (ACTIVITY_THEME[act]) {
      root.style.setProperty(varName, ACTIVITY_THEME[act]);
    }
  });
})();
