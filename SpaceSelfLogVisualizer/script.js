// Minimal visualizer for SpaceSelfLog sessions

const folderPicker = document.getElementById('folderPicker');
const importStatus = document.getElementById('importStatus');
const loadingSpinner = document.getElementById('loadingSpinner');

const statsSection = document.getElementById('statsSection');
const statCount = document.getElementById('statCount');
const statStart = document.getElementById('statStart');
const statEnd = document.getElementById('statEnd');
const statInterval = document.getElementById('statInterval');
const statDuration = document.getElementById('statDuration');
const statActiveDuration = document.getElementById('statActiveDuration');
const pausesEl = document.getElementById('pauses');

const viewerSection = document.getElementById('viewerSection');
const prevBtn = document.getElementById('prevBtn');
const nextBtn = document.getElementById('nextBtn');
const pagerText = document.getElementById('pagerText');
const viewerImage = document.getElementById('viewerImage');
// 移除 metaPrimary
// const metaPrimary = document.getElementById('metaPrimary');
const metaModel = document.getElementById('metaModel');
const metaGrid = document.getElementById('metaGrid');
const metaRawContainer = document.getElementById('metaRaw');
const metaInference = document.getElementById('metaInference');
const metaCapture = document.getElementById('metaCapture');
const metaId = document.getElementById('metaId');
const deleteBtn = document.getElementById('deleteBtn');
const censorBtn = document.getElementById('censorBtn');
const censorModeBtn = document.getElementById('censorModeBtn');
const brushSizeBtn = document.getElementById('brushSizeBtn');
const tabsEl = document.getElementById('tabs');
const tabLoadViewBtn = document.getElementById('tabLoadView');
const tabStatisticsBtn = document.getElementById('tabStatistics');
const statisticsSection = document.getElementById('statisticsSection');
const chartFormattedEl = document.getElementById('chartFormatted');
const chartHeatmapEl = document.getElementById('chartHeatmap');
const btnUnfoldFormatted = document.getElementById('btnUnfoldFormatted');
const btnUnfoldHeatmap = document.getElementById('btnUnfoldHeatmap');
const btnHeatmapNorm = document.getElementById('btnHeatmapNorm');
const btnHeatmapNormAnnotation = document.getElementById('btnHeatmapNormAnnotation');
const chartAnnotationEl = document.getElementById('chartAnnotation');
const chartAnnotationHeatmapEl = document.getElementById('chartAnnotationHeatmap');
const btnUnfoldAnnotation = document.getElementById('btnUnfoldAnnotation');
const btnUnfoldAnnotationHeatmap = document.getElementById('btnUnfoldAnnotationHeatmap');
const chartAnnotationAccuracyEl = document.getElementById('chartAnnotationAccuracy');
const btnUnfoldAnnotationAccuracy = document.getElementById('btnUnfoldAnnotationAccuracy');
const btnAnnotationMetric = document.getElementById('btnAnnotationMetric');
const chartModal = document.getElementById('chartModal');
const chartModalContent = document.getElementById('chartModalContent');
const chartModalTitle = document.getElementById('chartModalTitle');
const chartModalClose = document.getElementById('chartModalClose');
const chartModalBody = document.getElementById('chartModalBody');
const checkAllBtn = document.getElementById('checkAllBtn');
const jumpInput = document.getElementById('jumpInput');

// Session metadata (small font grid under Statistics)
const sessionProviderEl = document.getElementById('sessionProvider');
const sessionModelEl = document.getElementById('sessionModel');
const sessionExperimentEl = document.getElementById('sessionExperiment');
const sessionPromptEl = document.getElementById('sessionPrompt');

// Backend service address: default 5100 (consistent with server.py), adjust here if port needs to be changed
const SERVER_BASE = 'http://127.0.0.1:5100';

let entries = []; // { json, imgUrl, epochSec }
let avgIntervalSec = null;
let currentIndex = 0;
let currentSlug = null;
let sessionMeta = null; // { startEpochSec, intervalSec, provider, model, prompt, sessionId }
let drawLayer = null; // overlay canvas for censor painting
let isPainting = false;
let brushRadius = 16; // px
let currentURL = null;
let censorMode = 're'; // 're' = use Images as base; 'add' = use Images_censored as base

let lastTagStats = []; // cache stats for modal rendering

// Manual annotation state
let annotationLoaded = false;
let annotationMap = new Map(); // id -> { annotation, annotationChecked }

// Heatmap normalization mode: 'row' (per-label) or 'global'
let heatmapNormMode = 'row';
const HEATMAP_ROW_PALETTE = [
  { r: 60, g: 99, b: 130 },   // muted blue
  { r: 72, g: 120, b: 72 },   // muted green
  { r: 115, g: 95, b: 140 },  // muted purple
  { r: 140, g: 110, b: 70 },  // muted brown
];

function openChartModal(title, mode = 'auto', bodyClass = null) {
  if (!chartModal || !chartModalContent || !chartModalBody) return;
  chartModalTitle.textContent = title || '';
  chartModalBody.innerHTML = '';
  chartModalContent.classList.remove('wide', 'auto');
  chartModalContent.classList.add(mode === 'wide' ? 'wide' : 'auto');
  chartModal.hidden = false;
  chartModalBody.classList.remove('heatmap', 'chart-bars');
  if (bodyClass) chartModalBody.classList.add(bodyClass);
}

function closeChartModal() {
  if (!chartModal || !chartModalBody) return;
  chartModal.hidden = true;
  chartModalTitle.textContent = '';
  chartModalBody.classList.remove('heatmap', 'chart-bars');
  chartModalBody.innerHTML = '';
}

function setCensorMode(mode) {
  censorMode = mode === 'add' ? 'add' : 're';
  if (censorModeBtn) {
    censorModeBtn.textContent = (censorMode === 'add') ? 'Add' : 'Re-Censor';
  }
  try { localStorage.setItem('ssl_censor_mode', censorMode); } catch {}
}

// Brush size levels: 1..4 map to radii
const BRUSH_LEVELS = [8, 16, 24, 32];
let brushLevel = 2; // current default corresponds to 16px
function setBrushLevel(level) {
  const idx = Math.min(4, Math.max(1, level));
  brushLevel = idx;
  brushRadius = BRUSH_LEVELS[idx - 1];
  if (brushSizeBtn) brushSizeBtn.textContent = `Brush ${brushLevel}/4`;
  try { localStorage.setItem('ssl_brush_level', String(brushLevel)); } catch {}
}
function cycleBrushLevel() {
  const next = brushLevel % 4 + 1;
  setBrushLevel(next);
}

// Initialize from localStorage
try {
  const savedMode = localStorage.getItem('ssl_censor_mode');
  if (savedMode === 'add' || savedMode === 're') setCensorMode(savedMode);
  else setCensorMode('re');
  const savedBrush = parseInt(localStorage.getItem('ssl_brush_level') || '2', 10);
  if (savedBrush >= 1 && savedBrush <= 4) setBrushLevel(savedBrush);
  else setBrushLevel(2);
} catch {
  setCensorMode('re');
  setBrushLevel(2);
}

function formatDate(epochSec) {
  const d = new Date(epochSec * 1000);
  return d.toLocaleString();
}

function formatInterval(sec) {
  if (sec == null) return '-';
  // Normalize to integer seconds
  const totalSec = Math.max(0, Math.round(sec));
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  return `${h}h, ${m}m, ${s}s`;
}

function basename(path) {
  if (!path) return '';
  const idx = path.lastIndexOf('/');
  return idx >= 0 ? path.slice(idx + 1) : path;
}

function truncateText(s, max = 120) {
  if (!s) return '-';
  const str = String(s);
  return str.length > max ? (str.slice(0, max - 1) + '…') : str;
}

function showLoadView() {
  if (viewerSection) viewerSection.hidden = false;
  if (statsSection) statsSection.hidden = false;
  if (statisticsSection) statisticsSection.hidden = true;
  if (tabLoadViewBtn) tabLoadViewBtn.classList.add('active');
  if (tabStatisticsBtn) tabStatisticsBtn.classList.remove('active');
}

function showStatistics() {
  if (viewerSection) viewerSection.hidden = true;
  if (statsSection) statsSection.hidden = false;
  if (statisticsSection) statisticsSection.hidden = false;
  if (tabStatisticsBtn) tabStatisticsBtn.classList.add('active');
  if (tabLoadViewBtn) tabLoadViewBtn.classList.remove('active');
  updateStatisticsDashboard();
}

function extractTagsFromFormatted(formatted) {
  if (formatted == null) return [];
  // New structure: dict with activityLabel
  if (typeof formatted === 'object' && !Array.isArray(formatted)) {
    if (formatted.activityLabel != null) {
      const v = String(formatted.activityLabel).trim();
      return v ? [v] : [];
    }
    // Fallback: collect all values in object
    return Object.values(formatted)
      .map(s => String(s).trim())
      .filter(Boolean);
  }
  if (Array.isArray(formatted)) {
    return formatted.map(s => String(s).trim()).filter(Boolean);
  }
  if (typeof formatted === 'string') {
    // Try JSON array first
    try {
      const parsed = JSON.parse(formatted);
      if (Array.isArray(parsed)) {
        return parsed.map(s => String(s).trim()).filter(Boolean);
      }
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        if (parsed.activityLabel != null) {
          const v = String(parsed.activityLabel).trim();
          return v ? [v] : [];
        }
        return Object.values(parsed)
          .map(s => String(s).trim())
          .filter(Boolean);
      }
    } catch {}
    // Split by common separators and take token before ':' as label
    const raw = formatted;
    const parts = raw.split(/[,;|/\\]+/).flatMap(p => p.split(/\s+/));
    return parts
      .map(p => p.replace(/^"|"$/g, ''))
      .map(p => p.split(':')[0])
      .map(p => p.trim())
      .filter(t => t.length > 0);
  }
  return [];
}

function computeFormattedTagStats(list) {
  const counts = new Map();
  for (const e of list) {
    const j = e.json || {};
    const formatted = (j && (j.formattedOutput ?? j.formatted)) || null;
    const tags = extractTagsFromFormatted(formatted);
    for (const t of tags) {
      const key = String(t).toLowerCase();
      counts.set(key, (counts.get(key) || 0) + 1);
    }
  }
  const arr = Array.from(counts.entries()).map(([label, count]) => ({ label, count }));
  arr.sort((a, b) => (b.count - a.count) || a.label.localeCompare(b.label));
  return arr;
}

function computeAnnotationTagStats(list) {
  const counts = new Map();
  for (const e of list) {
    const j = e.json || {};
    const id = j.id ? String(j.id) : null;
    if (!id || !annotationMap.has(id)) continue;
    const rec = annotationMap.get(id) || {};
    const ann = rec.annotation || {};
    if (ann.activityLabelChecked !== true) continue;
    const lbl = ann.activityLabel;
    if (!lbl) continue;
    const key = String(lbl).toLowerCase();
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  const arr = Array.from(counts.entries()).map(([label, count]) => ({ label, count }));
  arr.sort((a, b) => (b.count - a.count) || a.label.localeCompare(b.label));
  return arr;
}

let annotationMetricMode = 'accuracy';
function computeAnnotationLabelMetrics(list, labelsOrder) {
  const labels = Array.isArray(labelsOrder) ? labelsOrder.map(s => String(s).toLowerCase()) : [];
  const tp = new Map();
  const fp = new Map();
  const fn = new Map();
  const accDen = new Map();
  const accCorrect = new Map();
  for (const l of labels) {
    tp.set(l, 0);
    fp.set(l, 0);
    fn.set(l, 0);
    accDen.set(l, 0);
    accCorrect.set(l, 0);
  }
  for (const e of list) {
    const j = e.json || {};
    const id = j.id ? String(j.id) : null;
    if (!id || !annotationMap.has(id)) continue;
    const rec = annotationMap.get(id) || {};
    const ann = rec.annotation || {};
    if (ann.activityLabelChecked !== true) continue;
    const annLabelRaw = ann.activityLabel;
    if (!annLabelRaw) continue;
    const annLabel = String(annLabelRaw).toLowerCase();
    if (!labels.includes(annLabel)) continue;
    const predRaw = getPrimaryActivityLabel(j);
    const predLabel = predRaw ? String(predRaw).toLowerCase() : null;
    accDen.set(annLabel, (accDen.get(annLabel) || 0) + 1);
    if (predLabel && predLabel === annLabel) {
      accCorrect.set(annLabel, (accCorrect.get(annLabel) || 0) + 1);
      tp.set(annLabel, (tp.get(annLabel) || 0) + 1);
    } else {
      fn.set(annLabel, (fn.get(annLabel) || 0) + 1);
      if (predLabel && labels.includes(predLabel)) {
        fp.set(predLabel, (fp.get(predLabel) || 0) + 1);
      }
    }
  }
  const out = labels.map(l => {
    const denAcc = accDen.get(l) || 0;
    const correct = accCorrect.get(l) || 0;
    const t = tp.get(l) || 0;
    const f_p = fp.get(l) || 0;
    const f_n = fn.get(l) || 0;
    const accuracy = denAcc ? (correct / denAcc) : 0;
    const precision = (t + f_p) ? (t / (t + f_p)) : 0;
    const recall = (t + f_n) ? (t / (t + f_n)) : 0;
    const f1 = (precision + recall) ? (2 * precision * recall / (precision + recall)) : 0;
    return { label: l, accuracy, precision, recall, f1 };
  });
  return out;
}

function renderAnnotationMetricChart(annStats, annMetrics, targetEl = chartAnnotationAccuracyEl) {
  if (!targetEl) return;
  targetEl.innerHTML = '';
  const order = (annStats || []).map(s => s.label);
  if (!order.length) {
    targetEl.innerHTML = '<div class="bar-row"><span class="bar-label">No tags</span><div class="bar"><div class="bar-fill" style="width:0%"></div></div><span class="bar-count">0%</span></div>';
    return;
  }
  const metricsByLabel = new Map();
  for (const m of (annMetrics || [])) metricsByLabel.set(m.label, m);
  const isDashboardBars = (targetEl && targetEl.id === 'chartAnnotationAccuracy');
  const labelLimit = isDashboardBars ? 20 : Infinity;
  const labels = order.slice(0, labelLimit).filter(l => metricsByLabel.has(l));
  for (const l of labels) {
    const m = metricsByLabel.get(l);
    const val = annotationMetricMode === 'precision' ? m.precision : (annotationMetricMode === 'f1' ? m.f1 : m.accuracy);
    const pct = Math.max(0, Math.min(100, Math.round(val * 100)));
    const row = document.createElement('div');
    row.className = 'bar-row';
    const lab = document.createElement('span');
    lab.className = 'bar-label';
    lab.textContent = l;
    const bar = document.createElement('div');
    bar.className = 'bar';
    const fill = document.createElement('div');
    fill.className = 'bar-fill';
    fill.style.width = `${pct}%`;
    const cnt = document.createElement('span');
    cnt.className = 'bar-count';
    cnt.textContent = `${pct}%`;
    bar.appendChild(fill);
    row.appendChild(lab);
    row.appendChild(bar);
    row.appendChild(cnt);
    targetEl.appendChild(row);
  }
}

function renderFormattedChart(stats, targetEl = chartFormattedEl) {
  if (!targetEl) return;
  targetEl.innerHTML = '';
  if (!stats.length) {
    targetEl.innerHTML = '<div class="bar-row"><span class="bar-label">No tags</span><div class="bar"><div class="bar-fill" style="width:0%"></div></div><span class="bar-count">0</span></div>';
    return;
  }
  const max = Math.max(...stats.map(s => s.count));
  const isDashboardBars = (targetEl && (targetEl.id === 'chartFormatted' || targetEl.id === 'chartAnnotation'));
  const labelLimit = isDashboardBars ? 20 : Infinity;
  const top = stats.slice(0, labelLimit);
  for (const s of top) {
    const pct = max ? Math.round((s.count / max) * 100) : 0;
    const row = document.createElement('div');
    row.className = 'bar-row';
    const lab = document.createElement('span');
    lab.className = 'bar-label';
    lab.textContent = s.label;
    const bar = document.createElement('div');
    bar.className = 'bar';
    const fill = document.createElement('div');
    fill.className = 'bar-fill';
    fill.style.width = `${pct}%`;
    bar.appendChild(fill);
    const cnt = document.createElement('span');
    cnt.className = 'bar-count';
    cnt.textContent = String(s.count);
    row.appendChild(lab);
    row.appendChild(bar);
    row.appendChild(cnt);
    targetEl.appendChild(row);
  }
}

function updateStatisticsDashboard() {
  const stats = computeFormattedTagStats(entries);
  lastTagStats = stats;
  renderFormattedChart(stats);
  renderTimelineHeatmap(entries, stats);
  const annStats = computeAnnotationTagStats(entries);
  renderFormattedChart(annStats, chartAnnotationEl);
  renderAnnotationTimelineHeatmap(entries, annStats, chartAnnotationHeatmapEl);
  const annMetrics = computeAnnotationLabelMetrics(entries, annStats.map(s => s.label));
  renderAnnotationMetricChart(annStats, annMetrics, chartAnnotationAccuracyEl);
}

function getPrimaryActivityLabel(json) {
  if (!json) return null;
  const fo = json.formattedOutput ?? json.formatted;
  if (fo == null) return null;
  if (typeof fo === 'object' && !Array.isArray(fo)) {
    const v = fo.activityLabel ?? null;
    return v ? String(v).trim() : null;
  }
  const tags = extractTagsFromFormatted(fo);
  return tags.length ? tags[0] : null;
}

function renderFormattedMetas(fo, entryJson) {
  try {
    if (!metaGrid || !metaRawContainer) return;
    // Remove previous dynamic formatted metas
    const toRemove = Array.from(metaGrid.querySelectorAll('.formatted-dyn'));
    for (const el of toRemove) el.remove();
    if (fo == null) return;
    // Normalize formatted output to object if possible
    let obj = null;
    if (typeof fo === 'object' && !Array.isArray(fo)) {
      obj = fo;
    } else if (typeof fo === 'string') {
      try {
        const parsed = JSON.parse(fo);
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) obj = parsed;
      } catch (_) {
        obj = null;
      }
    }
    const entryId = entryJson && entryJson.id ? String(entryJson.id) : null;
    const ann = (entryId && annotationMap.has(entryId)) ? (annotationMap.get(entryId).annotation || {}) : {};
    function stringifyVal(v) {
      return (v == null) ? '—' : (typeof v === 'object' ? JSON.stringify(v) : String(v));
    }
    function shallowEqual(a, b) {
      try {
        if (a === b) return true;
        const ta = typeof a, tb = typeof b;
        if (ta !== tb) return false;
        if (Array.isArray(a) && Array.isArray(b)) {
          if (a.length !== b.length) return false;
          for (let i = 0; i < a.length; i++) {
            if (!shallowEqual(a[i], b[i])) return false;
          }
          return true;
        }
        if (ta === 'object' && a && b) {
          const ka = Object.keys(a), kb = Object.keys(b);
          if (ka.length !== kb.length) return false;
          for (const k of ka) {
            if (!shallowEqual(a[k], b[k])) return false;
          }
          return true;
        }
        return false;
      } catch { return false; }
    }
    if (obj) {
      // Sort keys alphabetically and insert sequentially right after Raw Output
      const keys = Object.keys(obj).sort((a, b) => a.localeCompare(b));
      let insertAfterEl = metaRawContainer;
      for (let i = 0; i < keys.length; i++) {
        const k = keys[i];
        const v = obj[k];
        const valueStr = stringifyVal(v);
        const item = document.createElement('div');
        item.className = 'meta formatted-dyn';
        const lab = document.createElement('span');
        lab.textContent = k;
        const strong = document.createElement('strong');
        strong.textContent = valueStr;
        item.appendChild(lab);
        item.appendChild(strong);
        // Annotation controls
        const ctrl = document.createElement('div');
        ctrl.className = 'controls';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = !!ann[`${k}Checked`];
        const inp = document.createElement('input');
        inp.type = 'text';
        inp.style.marginLeft = '8px';
        inp.value = '';
        ctrl.appendChild(cb);
        ctrl.appendChild(inp);
        item.appendChild(ctrl);
        // Annotated diff marker
        const diffRow = document.createElement('div');
        diffRow.className = 'annotated-row';
        const diffLabel = document.createElement('span');
        diffLabel.textContent = 'annotated';
        const diffStrong = document.createElement('strong');
        const annVal = ann.hasOwnProperty(k) ? ann[k] : undefined;
        const isDiff = ann.hasOwnProperty(k) && !shallowEqual(annVal, v);
        diffStrong.textContent = isDiff ? stringifyVal(annVal) : '';
        if (isDiff) {
          diffRow.appendChild(diffLabel);
          diffRow.appendChild(diffStrong);
          item.appendChild(diffRow);
        }
        cb.addEventListener('change', async () => {
          await ensureAnnotationFileCreated();
          await saveAnnotation(entryId, { checks: { [k]: cb.checked }, annotationChecked: true });
          const rec = annotationMap.get(entryId) || { annotation: {}, annotationChecked: false };
          rec.annotation[`${k}Checked`] = cb.checked;
          rec.annotationChecked = true;
          annotationMap.set(entryId, rec);
        });
        function commitInput() {
          const raw = String(inp.value || '').trim();
          if (!raw) return;
          const newVal = raw;
          (async () => {
            await ensureAnnotationFileCreated();
            await saveAnnotation(entryId, { annotation: { [k]: newVal }, checks: { [k]: true }, annotationChecked: true });
            const rec = annotationMap.get(entryId) || { annotation: {}, annotationChecked: false };
            rec.annotation[k] = newVal;
            rec.annotation[`${k}Checked`] = true;
            rec.annotationChecked = true;
            annotationMap.set(entryId, rec);
            cb.checked = true;
            const currentIsDiff = !shallowEqual(newVal, v);
            if (currentIsDiff) {
              diffLabel.textContent = 'annotated';
              diffStrong.textContent = stringifyVal(newVal);
              if (!diffRow.parentElement) {
                diffRow.appendChild(diffLabel);
                diffRow.appendChild(diffStrong);
                item.appendChild(diffRow);
              }
            } else {
              if (diffRow.parentElement) diffRow.remove();
            }
            inp.value = '';
          })();
        }
        inp.addEventListener('keydown', (ev) => {
          if (ev.key === 'Enter') {
            ev.preventDefault();
            commitInput();
            inp.blur();
          }
        });
        inp.addEventListener('blur', () => { commitInput(); });
        insertAfterEl.insertAdjacentElement('afterend', item);
        insertAfterEl = item;
      }
    } else if (typeof fo === 'string') {
      const item = document.createElement('div');
      item.className = 'meta formatted-dyn';
      const lab = document.createElement('span');
      lab.textContent = 'Formatted Output';
      const strong = document.createElement('strong');
      strong.textContent = String(fo || '—');
      item.appendChild(lab);
      item.appendChild(strong);
      metaRawContainer.insertAdjacentElement('afterend', item);
    }
  } catch (_) {
    // ignore errors in rendering
  }
}

function computeAvgInterval(epochs) {
  if (!epochs || epochs.length === 0) return null;
  const sorted = [...epochs].sort((a, b) => a - b);
  if (sorted.length >= 3) {
    const d1 = sorted[1] - sorted[0];
    const d2 = sorted[2] - sorted[1];
    return (d1 + d2) / 2;
  } else if (sorted.length >= 2) {
    return (sorted[1] - sorted[0]);
  }
  return null;
}

function buildBins(start, end, avgIntervalSec) {
  const minWidth = 30; // seconds
  const maxWidth = 300; // seconds
  let bw = avgIntervalSec || 60;
  if (!Number.isFinite(bw) || bw <= 0) bw = 60;
  bw = Math.max(minWidth, Math.min(maxWidth, bw));
  const count = Math.max(1, Math.ceil((end - start) / bw));
  const bins = new Array(count);
  for (let i = 0; i < count; i++) bins[i] = start + i * bw;
  return { binWidthSec: bw, bins };
}

function buildPauseMask(bins, binWidthSec, pauses) {
  const mask = new Array(bins.length).fill(false);
  if (!pauses || !pauses.length) return mask;
  for (let i = 0; i < bins.length; i++) {
    const center = bins[i] + binWidthSec / 2;
    for (const p of pauses) {
      if (center >= p.start && center <= p.end) {
        mask[i] = true;
        break;
      }
    }
  }
  return mask;
}

function renderTimelineHeatmap(list, tagStats, targetEl = chartHeatmapEl) {
  if (!targetEl) return;
  targetEl.innerHTML = '';
  const epochs = list.map(e => e.epochSec).filter(Number.isFinite).sort((a, b) => a - b);
  if (!epochs.length) {
    targetEl.innerHTML = '<div class="heat-legend">No data</div>';
    return;
  }
  const start = epochs[0];
  const end = epochs[epochs.length - 1];
  const avg = computeAvgInterval(epochs);
  const pauses = analyzePauses(epochs, avg);
  const { binWidthSec, bins } = buildBins(start, end, avg);
  const pauseMask = buildPauseMask(bins, binWidthSec, pauses);

  // Build per-label counts per bin
  const countsByLabel = new Map();
  for (const e of list) {
    const t = getPrimaryActivityLabel(e.json || {});
    if (!t) continue;
    const idx = Math.max(0, Math.min(bins.length - 1, Math.floor((e.epochSec - start) / binWidthSec)));
    const label = String(t).toLowerCase();
    if (!countsByLabel.has(label)) countsByLabel.set(label, new Array(bins.length).fill(0));
    countsByLabel.get(label)[idx] += 1;
  }

  // 标签按频次排序来源于 tagStats；折叠视图取前 20，展开视图显示全部
  const labelsAll = (tagStats || [])
    .map(s => s.label)
    .filter(l => countsByLabel.has(l));
  const labelsOrdered = (targetEl && targetEl.id === 'chartHeatmap') ? labelsAll.slice(0, 20) : labelsAll;
  if (!labelsOrdered.length) {
    targetEl.innerHTML = '<div class="heat-legend">No activity labels</div>';
    return;
  }

  // Compress to fit: aggregate bins to the maximum columns that fit in the card
  const isDashboardHeatmap = (targetEl && targetEl.id === 'chartHeatmap');
  let containerWidth;
  if (isDashboardHeatmap) {
    const vw = Math.max(document.documentElement.clientWidth, window.innerWidth || 0);
    const statsStyles = statisticsSection ? getComputedStyle(statisticsSection) : null;
    const gridEl = document.getElementById('chartsGrid');
    const gridStyles = gridEl ? getComputedStyle(gridEl) : null;
    const paddingLeft = statsStyles ? parseFloat(statsStyles.paddingLeft || '20') : 20;
    const paddingRight = statsStyles ? parseFloat(statsStyles.paddingRight || '20') : 20;
    const gridWidth = vw - (paddingLeft + paddingRight);
    const baseWidth = gridWidth * (2 / 3);
    const columnGap = gridStyles ? parseFloat(gridStyles.columnGap || gridStyles.gap || '12') : 12;
    const containerPadding = 20; // chart-card horizontal padding total (approx 10 + 10)
    const extraShrink = vw * 0.37;      // extra shrink to be conservative in collapsed dashboard
    containerWidth = Math.max(0, baseWidth - columnGap - containerPadding - extraShrink);
  } else {
    const cardEl = targetEl.closest('.chart-card') || targetEl;
    containerWidth = cardEl.clientWidth || cardEl.getBoundingClientRect().width || 600;
  }
  const labelColWidthPx = 140; // matches CSS left column in .heat-row/.heat-axis
  const gapPx = 8; // grid gap
  const availableForCells = Math.max(100, containerWidth - labelColWidthPx - gapPx * 2);
  const minCellPx = 4; // minimum cell width to keep visibility
  const maxCols = Math.max(20, Math.floor(availableForCells / minCellPx));

  let binsAgg = bins;
  let pauseMaskAgg = pauseMask;
  let countsByLabelAgg = countsByLabel;
  let groupSize = 1;
  if (bins.length > maxCols) {
    groupSize = Math.ceil(bins.length / maxCols);
    const groups = Math.ceil(bins.length / groupSize);
    binsAgg = new Array(groups);
    pauseMaskAgg = new Array(groups).fill(false);
    for (let g = 0; g < groups; g++) {
      const startIdx = g * groupSize;
      const endIdx = Math.min(bins.length, startIdx + groupSize);
      binsAgg[g] = bins[startIdx];
      let allPause = true;
      for (let i = startIdx; i < endIdx; i++) {
        if (!pauseMask[i]) { allPause = false; break; }
      }
      pauseMaskAgg[g] = allPause;
    }
    const aggMap = new Map();
    for (const [label, series] of countsByLabel.entries()) {
      const agg = new Array(groups).fill(0);
      for (let g = 0; g < groups; g++) {
        const sIdx = g * groupSize;
        const eIdx = Math.min(series.length, sIdx + groupSize);
        let sum = 0;
        for (let i = sIdx; i < eIdx; i++) sum += series[i];
        agg[g] = sum;
      }
      aggMap.set(label, agg);
    }
    countsByLabelAgg = aggMap;
  }
  // Global max across all labels/bins for global normalization
  let globalMax = 1;
  for (const series of countsByLabelAgg.values()) {
    for (const vv of series) {
      if (vv > globalMax) globalMax = vv;
    }
  }
  const binWidthAggSec = binWidthSec * groupSize;

  // Axis row
  const axis = document.createElement('div');
  axis.className = 'heat-axis';
  const axisLabel = document.createElement('div');
  axisLabel.className = 'heat-axis-label';
  axisLabel.textContent = 'Time';
  const axisRow = document.createElement('div');
  axisRow.className = 'heat-axis-row';
  axisRow.style.gridTemplateColumns = `repeat(${binsAgg.length}, 1fr)`;
  // Compute tick positions: always include start/end, add evenly spaced ticks based on available width
  const labelMinSpacingPx = 50;
  let desiredTicks = Math.max(2, Math.min(binsAgg.length, Math.floor(availableForCells / labelMinSpacingPx)));
  const tickSet = new Set();
  for (let k = 0; k < desiredTicks; k++) {
    const idx = Math.round(k * (binsAgg.length - 1) / (desiredTicks - 1));
    tickSet.add(idx);
  }
  // Ensure mid tick is present even in tight widths
  if (desiredTicks === 2 && binsAgg.length >= 3) {
    tickSet.add(Math.round((binsAgg.length - 1) / 2));
  }
  for (let i = 0; i < binsAgg.length; i++) {
    const cell = document.createElement('div');
    cell.className = 'heat-axis-cell';
    if (tickSet.has(i)) {
      const d = (i === binsAgg.length - 1) ? new Date(end * 1000) : new Date((binsAgg[i]) * 1000);
      const hh = String(d.getHours()).padStart(2, '0');
      const mm = String(d.getMinutes()).padStart(2, '0');
      cell.textContent = `${hh}:${mm}`;
    }
    axisRow.appendChild(cell);
  }
  axis.appendChild(axisLabel);
  axis.appendChild(axisRow);
  targetEl.appendChild(axis);

  // Rows per activity label
  for (let idxRow = 0; idxRow < labelsOrdered.length; idxRow++) {
    const label = labelsOrdered[idxRow];
    const rowWrap = document.createElement('div');
    rowWrap.className = 'heat-row';
    const lab = document.createElement('div');
    lab.className = 'heat-label';
    lab.textContent = label;
    const cells = document.createElement('div');
    cells.className = 'heat-cells';
    cells.style.gridTemplateColumns = `repeat(${binsAgg.length}, 1fr)`;
    const series = countsByLabelAgg.get(label);
    const rowMax = Math.max(1, ...series);
    const baseColor = (heatmapNormMode === 'row')
      ? HEATMAP_ROW_PALETTE[idxRow % HEATMAP_ROW_PALETTE.length]
      : { r: 17, g: 17, b: 17 };
    for (let i = 0; i < binsAgg.length; i++) {
      const cell = document.createElement('div');
      cell.className = pauseMaskAgg[i] ? 'heat-cell pause' : 'heat-cell';
      const v = series[i];
      if (!pauseMaskAgg[i] && v > 0) {
        const baseline = 0.05;
        const alpha = (heatmapNormMode === 'global')
          ? Math.min(1, Math.max(baseline, Math.log1p(v) / Math.log1p(globalMax)))
          : Math.min(1, Math.max(baseline, v / rowMax));
        cell.style.backgroundColor = `rgba(${baseColor.r},${baseColor.g},${baseColor.b},${alpha})`;
      } else {
        cell.style.backgroundColor = 'transparent';
      }
      // Tooltip
      const startMs = binsAgg[i] * 1000;
      const endMs = (i === binsAgg.length - 1) ? end * 1000 : startMs + binWidthAggSec * 1000;
      const ds = new Date(startMs);
      const de = new Date(endMs);
      cell.title = `${ds.toLocaleTimeString()} - ${de.toLocaleTimeString()}\n${label}: ${v}`;
      cells.appendChild(cell);
    }
    rowWrap.appendChild(lab);
    rowWrap.appendChild(cells);
    targetEl.appendChild(rowWrap);
  }
  const legend = document.createElement('div');
  legend.className = 'heat-legend';
  legend.textContent = (heatmapNormMode === 'global')
    ? 'Black = higher frequency (global log normalization). Blank = paused or no data.'
    : 'Colored rows; darker = higher frequency within that label (row normalization). Blank = paused or no data.';
  legend.style.marginTop = '1em';
  targetEl.appendChild(legend);

  // Dynamic per-cell time scale description (English)
  const scale = document.createElement('div');
  scale.className = 'heat-legend';
  const humanScale = formatInterval(binWidthAggSec);
  const extra = (groupSize > 1)
    ? ` (aggregated from ${groupSize}×${formatInterval(binWidthSec)})`
    : '';
  scale.textContent = `Each cell represents ${humanScale}${extra}.`;
  scale.style.marginTop = '0.25em';
  targetEl.appendChild(scale);
}

function renderAnnotationTimelineHeatmap(list, tagStats, targetEl = chartAnnotationHeatmapEl) {
  if (!targetEl) return;
  targetEl.innerHTML = '';
  const epochs = list.map(e => e.epochSec).filter(Number.isFinite).sort((a, b) => a - b);
  if (!epochs.length) {
    targetEl.innerHTML = '<div class="heat-legend">No data</div>';
    return;
  }
  const start = epochs[0];
  const end = epochs[epochs.length - 1];
  const avg = computeAvgInterval(epochs);
  const pauses = analyzePauses(epochs, avg);
  const { binWidthSec, bins } = buildBins(start, end, avg);
  const pauseMask = buildPauseMask(bins, binWidthSec, pauses);

  const countsByLabel = new Map();
  for (const e of list) {
    const j = e.json || {};
    const id = j.id ? String(j.id) : null;
    if (!id || !annotationMap.has(id)) continue;
    const rec = annotationMap.get(id) || {};
    const ann = rec.annotation || {};
    if (ann.activityLabelChecked !== true) continue;
    const labelRaw = ann.activityLabel;
    if (!labelRaw) continue;
    const idx = Math.max(0, Math.min(bins.length - 1, Math.floor((e.epochSec - start) / binWidthSec)));
    const label = String(labelRaw).toLowerCase();
    if (!countsByLabel.has(label)) countsByLabel.set(label, new Array(bins.length).fill(0));
    countsByLabel.get(label)[idx] += 1;
  }
  const labelsAll = (tagStats || []).map(s => s.label).filter(l => countsByLabel.has(l));
  const labelsOrdered = (targetEl && targetEl.id === 'chartAnnotationHeatmap') ? labelsAll.slice(0, 20) : labelsAll;
  if (!labelsOrdered.length) {
    targetEl.innerHTML = '<div class="heat-legend">No activity labels</div>';
    return;
  }
  let containerWidth;
  const isDashboardHeatmap = (targetEl && targetEl.id === 'chartAnnotationHeatmap');
  if (isDashboardHeatmap) {
    const vw = Math.max(document.documentElement.clientWidth, window.innerWidth || 0);
    const statsStyles = statisticsSection ? getComputedStyle(statisticsSection) : null;
    const gridEl = document.getElementById('chartsGrid');
    const gridStyles = gridEl ? getComputedStyle(gridEl) : null;
    const paddingLeft = statsStyles ? parseFloat(statsStyles.paddingLeft || '20') : 20;
    const paddingRight = statsStyles ? parseFloat(statsStyles.paddingRight || '20') : 20;
    const gridWidth = vw - (paddingLeft + paddingRight);
    const baseWidth = gridWidth * (2 / 3);
    const columnGap = gridStyles ? parseFloat(gridStyles.columnGap || gridStyles.gap || '12') : 12;
    const containerPadding = 20;
    const extraShrink = vw * 0.37;
    containerWidth = Math.max(0, baseWidth - columnGap - containerPadding - extraShrink);
  } else {
    const cardEl = targetEl.closest('.chart-card') || targetEl;
    containerWidth = cardEl.clientWidth || cardEl.getBoundingClientRect().width || 600;
  }
  const labelColWidthPx = 140;
  const gapPx = 8;
  const availableForCells = Math.max(100, containerWidth - labelColWidthPx - gapPx * 2);
  const minCellPx = 4;
  const maxCols = Math.max(20, Math.floor(availableForCells / minCellPx));

  let binsAgg = bins;
  let pauseMaskAgg = pauseMask;
  let countsByLabelAgg = countsByLabel;
  let groupSize = 1;
  if (bins.length > maxCols) {
    groupSize = Math.ceil(bins.length / maxCols);
    const groups = Math.ceil(bins.length / groupSize);
    binsAgg = new Array(groups);
    pauseMaskAgg = new Array(groups).fill(false);
    for (let g = 0; g < groups; g++) {
      const startIdx = g * groupSize;
      const endIdx = Math.min(bins.length, startIdx + groupSize);
      binsAgg[g] = bins[startIdx];
      let allPause = true;
      for (let i = startIdx; i < endIdx; i++) {
        if (!pauseMask[i]) { allPause = false; break; }
      }
      pauseMaskAgg[g] = allPause;
    }
    const aggMap = new Map();
    for (const [label, series] of countsByLabel.entries()) {
      const agg = new Array(groups).fill(0);
      for (let g = 0; g < groups; g++) {
        const sIdx = g * groupSize;
        const eIdx = Math.min(series.length, sIdx + groupSize);
        let sum = 0;
        for (let i = sIdx; i < eIdx; i++) sum += series[i];
        agg[g] = sum;
      }
      aggMap.set(label, agg);
    }
    countsByLabelAgg = aggMap;
  }
  let globalMax = 1;
  for (const series of countsByLabelAgg.values()) {
    for (const vv of series) {
      if (vv > globalMax) globalMax = vv;
    }
  }
  const binWidthAggSec = binWidthSec * groupSize;

  const axis = document.createElement('div');
  axis.className = 'heat-axis';
  const axisLabel = document.createElement('div');
  axisLabel.className = 'heat-axis-label';
  axisLabel.textContent = 'Time';
  const axisRow = document.createElement('div');
  axisRow.className = 'heat-axis-row';
  axisRow.style.gridTemplateColumns = `repeat(${binsAgg.length}, 1fr)`;
  const labelMinSpacingPx = 50;
  let desiredTicks = Math.max(2, Math.min(binsAgg.length, Math.floor(availableForCells / labelMinSpacingPx)));
  const tickSet = new Set();
  for (let k = 0; k < desiredTicks; k++) {
    const idx = Math.round(k * (binsAgg.length - 1) / (desiredTicks - 1));
    tickSet.add(idx);
  }
  if (desiredTicks === 2 && binsAgg.length >= 3) {
    tickSet.add(Math.round((binsAgg.length - 1) / 2));
  }
  for (let i = 0; i < binsAgg.length; i++) {
    const cell = document.createElement('div');
    cell.className = 'heat-axis-cell';
    if (tickSet.has(i)) {
      const d = (i === binsAgg.length - 1) ? new Date(end * 1000) : new Date((binsAgg[i]) * 1000);
      const hh = String(d.getHours()).padStart(2, '0');
      const mm = String(d.getMinutes()).padStart(2, '0');
      cell.textContent = `${hh}:${mm}`;
    }
    axisRow.appendChild(cell);
  }
  axis.appendChild(axisLabel);
  axis.appendChild(axisRow);
  targetEl.appendChild(axis);

  for (let idxRow = 0; idxRow < labelsOrdered.length; idxRow++) {
    const label = labelsOrdered[idxRow];
    const rowWrap = document.createElement('div');
    rowWrap.className = 'heat-row';
    const lab = document.createElement('div');
    lab.className = 'heat-label';
    lab.textContent = label;
    const cells = document.createElement('div');
    cells.className = 'heat-cells';
    cells.style.gridTemplateColumns = `repeat(${binsAgg.length}, 1fr)`;
    const series = countsByLabelAgg.get(label);
    const rowMax = Math.max(1, ...series);
    const baseColor = (heatmapNormMode === 'row')
      ? HEATMAP_ROW_PALETTE[idxRow % HEATMAP_ROW_PALETTE.length]
      : { r: 17, g: 17, b: 17 };
    for (let i = 0; i < binsAgg.length; i++) {
      const cell = document.createElement('div');
      cell.className = pauseMaskAgg[i] ? 'heat-cell pause' : 'heat-cell';
      const v = series[i];
      if (!pauseMaskAgg[i] && v > 0) {
        const baseline = 0.05;
        const alpha = (heatmapNormMode === 'global')
          ? Math.min(1, Math.max(baseline, Math.log1p(v) / Math.log1p(globalMax)))
          : Math.min(1, Math.max(baseline, v / rowMax));
        cell.style.backgroundColor = `rgba(${baseColor.r},${baseColor.g},${baseColor.b},${alpha})`;
      } else {
        cell.style.backgroundColor = 'transparent';
      }
      const startMs = binsAgg[i] * 1000;
      const endMs = (i === binsAgg.length - 1) ? end * 1000 : startMs + binWidthAggSec * 1000;
      const ds = new Date(startMs);
      const de = new Date(endMs);
      cell.title = `${ds.toLocaleTimeString()} - ${de.toLocaleTimeString()}\n${label}: ${v}`;
      cells.appendChild(cell);
    }
    rowWrap.appendChild(lab);
    rowWrap.appendChild(cells);
    targetEl.appendChild(rowWrap);
  }
  const legend = document.createElement('div');
  legend.className = 'heat-legend';
  legend.textContent = (heatmapNormMode === 'global')
    ? 'Black = higher frequency (global log normalization). Blank = paused or no data.'
    : 'Colored rows; darker = higher frequency within that label (row normalization). Blank = paused or no data.';
  legend.style.marginTop = '1em';
  targetEl.appendChild(legend);

  const scale = document.createElement('div');
  scale.className = 'heat-legend';
  const humanScale = formatInterval(binWidthAggSec);
  const extra = (groupSize > 1)
    ? ` (aggregated from ${groupSize}×${formatInterval(binWidthSec)})`
    : '';
  scale.textContent = `Each cell represents ${humanScale}${extra}.`;
  scale.style.marginTop = '0.25em';
  targetEl.appendChild(scale);
}

// Parse session slug: compatible with different selection scenarios (select session root / select parent Data / select higher level)
function extractSlugFromJsonFile(jsonFile, jsonArray, allFiles) {
  const rel = jsonFile.webkitRelativePath || '';
  // Case 1: Select higher level directory, path contains Data/<slug>/Data/analysis_results.json
  let m = rel.match(/(?:^|\/)Data\/([^/]+)\/Data\/analysis_results\.json$/);
  if (m) return m[1];
  // Case 2: Select parent Data directory, relative path like <slug>/Data/analysis_results.json
  m = rel.match(/^([^/]+)\/Data\/analysis_results\.json$/);
  if (m) return m[1];
  // Case 3: Extract /Data/<slug>/Images/ from JSON's imagePath absolute path
  if (Array.isArray(jsonArray)) {
    for (const j of jsonArray) {
      const p = (j && j.imagePath) || '';
      const m2 = (typeof p === 'string') ? p.match(/\/?Data\/([^/]+)\/Images\//) : null;
      if (m2) return m2[1];
    }
  }
  // Case 4: Try to extract /Data/<slug>/Images/ or /Data/<slug>/Data/analysis_results.json from selected file relative paths
  if (Array.isArray(allFiles)) {
    for (const f of allFiles) {
      const rp = f.webkitRelativePath || '';
      const m3 = rp.match(/\/?Data\/([^/]+)\/Images\//) || rp.match(/\/?Data\/([^/]+)\/Data\/analysis_results\.json$/);
      if (m3) return m3[1];
    }
  }
  return null;
}

// Call backend to ensure Images_censored is generated (one-click processing if not exists)
async function ensureCensoredOnServer(slug) {
  try {
    const res = await fetch(`${SERVER_BASE}/ensure_censored`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slug }),
    });
    if (!res.ok) {
      const t = await res.text();
      throw new Error(`HTTP ${res.status}: ${t}`);
    }
    const j = await res.json();
    return j; // { status, processed_count, session_dir }
  } catch (e) {
    throw new Error('Backend processing failed: ' + e.message);
  }
}

function deriveFilenameFromCapture(json) {
  // Try analysis_<epoch>.jpg where epoch = captureTime + 978307200
  if (typeof json.captureTime === 'number') {
    const epoch = Math.round(json.captureTime + 978307200);
    return `analysis_${epoch}.jpg`;
  }
  return null;
}

function computeEpochFrom(json, fileName) {
  // 1) Prefer digits in fileName (Unix epoch seconds embedded)
  const mNum = /(\d{10})/.exec(fileName || '');
  if (mNum) {
    const v = Number(mNum[1]);
    if (Number.isFinite(v)) return v;
  }
  // 2) Parse date-like patterns in fileName or imagePath: YYYY-MM-DD_HH-MM-SS
  const srcPath = (json && typeof json.imagePath === 'string') ? json.imagePath : fileName || '';
  const mDate = /(\d{4})-(\d{2})-(\d{2})[ T_](\d{2})[-:](\d{2})[-:](\d{2})/.exec(srcPath);
  if (mDate) {
    const y = Number(mDate[1]);
    const M = Number(mDate[2]);
    const d = Number(mDate[3]);
    const h = Number(mDate[4]);
    const mi = Number(mDate[5]);
    const s = Number(mDate[6]);
    const dt = new Date(y, M - 1, d, h, mi, s);
    return Math.floor(dt.getTime() / 1000);
  }
  // 3) If captureTime/responseTime provided
  if (typeof json?.captureTime === 'number') return json.captureTime + 978307200; // CFAbsoluteTime
  if (typeof json?.responseTime === 'number') return json.responseTime + 978307200; // CFAbsoluteTime
  if (typeof json?.captureTime === 'string') {
    const ms = Date.parse(json.captureTime);
    if (!Number.isNaN(ms)) return Math.floor(ms / 1000);
  }
  if (typeof json?.responseTime === 'string') {
    const ms = Date.parse(json.responseTime);
    if (!Number.isNaN(ms)) return Math.floor(ms / 1000);
  }
  // 4) Try generic timestamp fields
  const cand = json?.timestamp || json?.createdAt || json?.date || null;
  if (typeof cand === 'string') {
    const ms = Date.parse(cand);
    if (!Number.isNaN(ms)) return Math.floor(ms / 1000);
  }
  return NaN;
}

function analyzePauses(sortedEpochs, intervalSec) {
  const pauses = [];
  if (!sortedEpochs || sortedEpochs.length < 2 || !intervalSec || !isFinite(intervalSec)) return pauses;
  // Pause detection sensitivity factor (persisted via localStorage if set)
  let factor = 2;
  try {
    const saved = parseFloat(localStorage.getItem('ssl_pause_factor') || '2');
    if (isFinite(saved) && saved >= 1.1 && saved <= 4.0) factor = saved;
  } catch {}
  const threshold = intervalSec * factor; // e.g., 2x average interval by default
  for (let i = 1; i < sortedEpochs.length; i++) {
    const gap = sortedEpochs[i] - sortedEpochs[i - 1];
    if (gap > threshold) {
      pauses.push({ start: sortedEpochs[i - 1], end: sortedEpochs[i], gap });
    }
  }
  return pauses;
}

function updateStats() {
  const count = entries.length;
  statCount.textContent = String(count);
  if (count === 0) {
    statStart.textContent = '-';
    statEnd.textContent = '-';
    statInterval.textContent = '-';
    statDuration.textContent = '-';
    statActiveDuration.textContent = '-';
    pausesEl.innerHTML = '';
    return;
  }

  const epochs = entries.map(e => e.epochSec).filter(Number.isFinite).sort((a, b) => a - b);
  const start = (sessionMeta && Number.isFinite(sessionMeta.startEpochSec)) ? sessionMeta.startEpochSec : epochs[0];
  const end = epochs[epochs.length - 1];
  statStart.textContent = formatDate(start);
  statEnd.textContent = formatDate(end);

  // 平均间隔：看前 3 个 timestamp，取间隔的平均数
  if (sessionMeta && Number.isFinite(sessionMeta.intervalSec) && sessionMeta.intervalSec > 0) {
    avgIntervalSec = sessionMeta.intervalSec;
  } else if (epochs.length >= 3) {
    const d1 = epochs[1] - epochs[0];
    const d2 = epochs[2] - epochs[1];
    avgIntervalSec = (d1 + d2) / 2;
  } else if (epochs.length >= 2) {
    avgIntervalSec = (epochs[1] - epochs[0]);
  } else {
    avgIntervalSec = null;
  }
  statInterval.textContent = formatInterval(avgIntervalSec);

  const pauses = analyzePauses(epochs, avgIntervalSec);
  const totalDurationSec = end - start;
  const totalPausedSec = pauses.reduce((acc, p) => acc + (p.gap || 0), 0);
  const activeDurationSec = Math.max(0, totalDurationSec - totalPausedSec);
  statDuration.textContent = formatInterval(totalDurationSec);
  statActiveDuration.textContent = formatInterval(activeDurationSec);
  if (pauses.length === 0) {
    pausesEl.innerHTML = '<div class="pause-item">No significant pauses detected</div>';
  } else {
    pausesEl.innerHTML = pauses.map(p => {
      return `<div class="pause-item">Pause: ${formatDate(p.start)} → ${formatDate(p.end)} (${formatInterval(p.gap)})</div>`;
    }).join('');
  }

  // Session metadata display (use smaller font in meta-grid)
  try {
    const provider = sessionMeta?.provider || '-';
    const model = sessionMeta?.model || '-';
    const exp = sessionMeta?.experimentNumber || '-';
    const promptShort = truncateText(sessionMeta?.prompt || '-', 140);
    if (sessionProviderEl) sessionProviderEl.textContent = provider;
    if (sessionModelEl) sessionModelEl.textContent = model;
    if (sessionExperimentEl) sessionExperimentEl.textContent = exp;
    if (sessionPromptEl) sessionPromptEl.textContent = promptShort;
  } catch (_) {}
}

function updateViewer() {
  const total = entries.length;
  if (total === 0) {
    viewerSection.hidden = true;
    return;
  }
  viewerSection.hidden = false;
  pagerText.textContent = `${currentIndex + 1} / ${total}`;

  const e = entries[currentIndex];
  const j = e.json || {};
  const imgUrl = e.imgUrl || null;

  // Image: directly use image URL provided by server (Images_censored)
  if (imgUrl) {
    viewerImage.src = imgUrl;
    viewerImage.alt = basename(j.imagePath || '');
  } else {
    viewerImage.src = '';
    viewerImage.alt = 'Image missing';
  }

  // Meta: remove top-right display, show both raw/formatted output below instead
  metaModel.textContent = (j.modelOutput || '—');
  const fo = (j.formattedOutput ?? j.formatted);
  renderFormattedMetas(fo, j);

  if (typeof j.captureTime === 'number' && typeof j.responseTime === 'number') {
    const ms = Math.max(0, (j.responseTime - j.captureTime) * 1000);
    metaInference.textContent = `${ms.toFixed(0)} ms`;
  } else {
    metaInference.textContent = '—';
  }
  const epoch = e.epochSec;
  metaCapture.textContent = Number.isFinite(epoch) ? formatDate(epoch) : '—';
  metaId.textContent = j.id || '—';
}

function normalizeFormattedObject(fo) {
  if (fo && typeof fo === 'object' && !Array.isArray(fo)) return fo;
  if (typeof fo === 'string') {
    try {
      const parsed = JSON.parse(fo);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return parsed;
    } catch {}
  }
  return null;
}

async function checkAllCurrent() {
  if (entries.length === 0) return;
  const e = entries[currentIndex];
  const j = e.json || {};
  const fo = (j.formattedOutput ?? j.formatted);
  const obj = normalizeFormattedObject(fo);
  if (!obj) return;
  const checks = {};
  for (const k of Object.keys(obj)) checks[k] = true;
  await ensureAnnotationFileCreated();
  await saveAnnotation(j.id, { checks, annotationChecked: true });
  const rec = annotationMap.get(j.id) || { annotation: {}, annotationChecked: false };
  for (const k of Object.keys(obj)) rec.annotation[`${k}Checked`] = true;
  rec.annotationChecked = true;
  annotationMap.set(j.id, rec);
  const boxes = metaGrid ? metaGrid.querySelectorAll('.formatted-dyn .controls input[type="checkbox"]') : [];
  boxes.forEach(cb => { cb.checked = true; });
}

if (checkAllBtn) {
  checkAllBtn.addEventListener('click', (e) => { e.preventDefault(); checkAllCurrent(); });
}

if (jumpInput) {
  jumpInput.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') {
      ev.preventDefault();
      const v = parseInt(jumpInput.value || '');
      if (Number.isFinite(v) && v >= 1 && v <= entries.length) {
        currentIndex = v - 1;
        updateViewer();
      }
    }
  });
}

async function tryLoadAnnotation(slug) {
  try {
    const res = await fetch(`${SERVER_BASE}/get_annotation?slug=${encodeURIComponent(slug)}`);
    if (!res.ok) return;
    const j = await res.json();
    const arr = Array.isArray(j.data) ? j.data : [];
    annotationMap.clear();
    for (const e of arr) {
      if (e && e.id) {
        annotationMap.set(String(e.id), {
          annotation: (e.annotation || {}),
          annotationChecked: !!e.annotationChecked,
        });
      }
    }
    annotationLoaded = true;
  } catch {}
}

async function ensureAnnotationFileCreated() {
  if (annotationLoaded) return;
  if (!currentSlug) return;
  try {
    const res = await fetch(`${SERVER_BASE}/ensure_annotation`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slug: currentSlug })
    });
    if (!res.ok) return;
    await tryLoadAnnotation(currentSlug);
  } catch {}
}

async function saveAnnotation(entryId, updates) {
  if (!currentSlug || !entryId) return;
  try {
    const res = await fetch(`${SERVER_BASE}/update_annotation`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slug: currentSlug, id: entryId, updates })
    });
    if (!res.ok) {
      const t = await res.text();
      importStatus.textContent = `Annotation save failed: ${t}`;
      return;
    }
  } catch (e) {
    importStatus.textContent = 'Annotation save failed: ' + e.message;
  }
}

function toMapByName(files) {
  const map = new Map();
  for (const f of files) {
    map.set(basename(f.webkitRelativePath || f.name), f);
  }
  return map;
}

function parseISOToEpochSec(s) {
  try {
    const ms = Date.parse(String(s));
    if (!Number.isFinite(ms)) return null;
    return Math.floor(ms / 1000);
  } catch (_) {
    return null;
  }
}

function normalizeMeta(raw) {
  try {
    if (!raw || typeof raw !== 'object') return null;
    let startEpochSec = null;
    const expStart = raw.experimentStartTime;
    if (typeof expStart === 'string') {
      startEpochSec = parseISOToEpochSec(expStart);
    } else if (typeof expStart === 'number') {
      startEpochSec = expStart > 1e12 ? Math.floor(expStart / 1000) : Math.floor(expStart);
    }
    const intervalSec = (typeof raw.intervalSeconds === 'number' && raw.intervalSeconds > 0) ? raw.intervalSeconds : null;
    const provider = (raw.apiProvider != null) ? String(raw.apiProvider) : null;
    const model = (raw.model != null) ? String(raw.model) : null;
    const prompt = (raw.prompt != null) ? String(raw.prompt) : null;
    const experimentNumber = (raw.experimentNumber != null) ? String(raw.experimentNumber) : null;
    const sessionId = (raw.sessionId != null) ? String(raw.sessionId) : null;
    return { startEpochSec, intervalSec, provider, model, prompt, experimentNumber, sessionId };
  } catch (_) {
    return null;
  }
}

async function parseSession(fileList) {
  importStatus.textContent = 'Reading…';
  if (loadingSpinner) loadingSpinner.hidden = false;
  // Hide stats and viewer during processing, disable navigation buttons
  statsSection.hidden = true;
  viewerSection.hidden = true;
  prevBtn.disabled = true;
  nextBtn.disabled = true;
  entries = [];
  avgIntervalSec = null;
  currentIndex = 0;
  sessionMeta = null;

  const files = Array.from(fileList);
  // Find JSON
  const jsonFile = files.find(f => /(^|\/)Data\/analysis_results\.json$/.test(f.webkitRelativePath || ''));
  if (!jsonFile) {
    importStatus.textContent = 'Data/analysis_results.json not found, please select session root directory.';
    statsSection.hidden = true;
    viewerSection.hidden = true;
    return;
  }

  // Read JSON
  const text = await jsonFile.text();
  let arr = [];
  try {
    arr = JSON.parse(text);
    if (!Array.isArray(arr)) throw new Error('JSON is not an array');
  } catch (e) {
    importStatus.textContent = 'analysis_results.json parsing failed: ' + e.message;
    statsSection.hidden = true;
    viewerSection.hidden = true;
    return;
  }

  // Extract slug and request backend to ensure Images_censored is generated
  const slug = extractSlugFromJsonFile(jsonFile, arr, files);
  if (!slug) {
    importStatus.textContent = 'Unable to identify session slug: please select session root directory or its parent Data directory; or ensure JSON imagePath is absolute path.';
    if (loadingSpinner) loadingSpinner.hidden = true;
    statsSection.hidden = true;
    viewerSection.hidden = true;
    return;
  }
  currentSlug = slug;
  await tryLoadAnnotation(slug);
  // Estimate processing count (based on jpg count in Images vs Images_censored in selected directory)
  const estimate = (() => {
    try {
      const rels = files.map(f => f.webkitRelativePath || '');
      const total = rels.filter(p => /\/Images\/.+\.(jpe?g)$/i.test(p)).length;
      const done = rels.filter(p => /\/Images_censored\/.+\.(jpe?g)$/i.test(p)).length;
      const toProcess = Math.max(0, total - done);
      return { total, done, toProcess };
    } catch (_) {
      return { total: 0, done: 0, toProcess: 0 };
    }
  })();
  importStatus.textContent = `Checking Images_censored… (session: ${slug}, estimated to process ${estimate.toProcess} images)`;
  let sessionDir = null;
  try {
    const ensure = await ensureCensoredOnServer(slug);
    sessionDir = ensure && ensure.session_dir ? ensure.session_dir : null;
    importStatus.textContent = `Processing complete: Images_censored ready (newly processed ${ensure.processed_count} images)`;
  } catch (e) {
    importStatus.textContent = e.message;
    if (loadingSpinner) loadingSpinner.hidden = true;
    statsSection.hidden = true;
    viewerSection.hidden = true;
    return;
  }

  // Optional: read metadata.json from selected files
  try {
    const metaFile = files.find(f => /(^|\/)Data\/metadata\.json$/.test(f.webkitRelativePath || ''));
    if (metaFile) {
      const metaText = await metaFile.text();
      const rawMeta = JSON.parse(metaText);
      sessionMeta = normalizeMeta(rawMeta);
    }
  } catch (_) {
    sessionMeta = null;
  }

  // Build entries (only use Images_censored)
  for (const j of arr) {
    const nameFromPath = basename(j.imagePath || '');
    if (!nameFromPath || !/\.jpe?g$/i.test(nameFromPath)) {
      const epochSec = computeEpochFrom(j, nameFromPath);
      entries.push({ json: j, imgUrl: null, epochSec });
      continue;
    }
    const absOriginal = j.imagePath || '';
    let absCensored = null;
    if (sessionDir) {
      absCensored = `${sessionDir}/Images_censored/${nameFromPath}`;
    } else {
      // Fallback compatibility: replace directory name from original path (may be iOS absolute path, backend will reject)
      absCensored = absOriginal.replace('/Images/', '/Images_censored/');
    }
    const imgUrl = absCensored ? `${SERVER_BASE}/file?path=${encodeURIComponent(absCensored)}` : null;
    const epochSec = computeEpochFrom(j, nameFromPath);
    entries.push({ json: j, imgUrl, epochSec });
  }

  // Sort by epoch
  entries.sort((a, b) => (a.epochSec - b.epochSec));

  importStatus.textContent = `Loaded: JSON ${arr.length} entries, image source: Images_censored`;
  statsSection.hidden = false;
  updateStats();
  currentIndex = 0;
  updateViewer();
  // Loading complete, hide spinner, enable navigation
  if (loadingSpinner) loadingSpinner.hidden = true;
  prevBtn.disabled = false;
  nextBtn.disabled = false;
  // Show tabs and default to Load & View
  if (tabsEl) tabsEl.hidden = false;
  showLoadView();
}

async function deleteCurrentEntry() {
  if (entries.length === 0) return;
  const e = entries[currentIndex];
  const j = e.json || {};
  let filename = basename(j.imagePath || '');
  if (!filename) {
    const derived = deriveFilenameFromCapture(j);
    if (derived) filename = derived;
  }
  if (!filename || !currentSlug) {
    importStatus.textContent = 'Cannot delete: missing filename or session slug';
    return;
  }
  deleteBtn.disabled = true;
  try {
    const res = await fetch(`${SERVER_BASE}/delete_entry`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slug: currentSlug, filename, id: j.id || null }),
    });
    if (!res.ok) throw new Error(await res.text());
    const info = await res.json();
    const removed = info?.deleted?.json_removed_count || (info?.deleted?.json_removed ? 1 : 0);
    importStatus.textContent = `Deleted: ${filename} (JSON removed ${removed})`;
    // Remove locally and update UI
    entries.splice(currentIndex, 1);
    if (entries.length === 0) {
      updateStats();
      updateViewer();
      return;
    }
    currentIndex = Math.min(currentIndex, entries.length - 1);
    updateStats();
    updateViewer();
  } catch (e) {
    importStatus.textContent = 'Delete failed: ' + e.message;
  } finally {
    deleteBtn.disabled = false;
  }
}

function ensureDrawLayer() {
  const container = document.querySelector('.canvas');
  if (!container) return null;
  if (!drawLayer) {
    drawLayer = document.createElement('canvas');
    drawLayer.id = 'drawLayer';
    drawLayer.style.position = 'absolute';
    drawLayer.style.left = '0';
    drawLayer.style.top = '0';
    drawLayer.style.width = '100%';
    drawLayer.style.height = '100%';
    drawLayer.style.cursor = 'crosshair';
    drawLayer.style.pointerEvents = 'auto';
    container.style.position = 'relative';
    container.appendChild(drawLayer);
  }
  // Size to match displayed image box
  const rect = container.getBoundingClientRect();
  drawLayer.width = Math.max(1, Math.floor(rect.width));
  drawLayer.height = Math.max(1, Math.floor(rect.height));
  const ctx = drawLayer.getContext('2d');
  ctx.clearRect(0, 0, drawLayer.width, drawLayer.height);
  return drawLayer;
}

function imageClientRect() {
  const img = viewerImage;
  const r = img.getBoundingClientRect();
  const container = document.querySelector('.canvas').getBoundingClientRect();
  return {
    x: r.left - container.left,
    y: r.top - container.top,
    w: r.width,
    h: r.height,
  };
}

function startCensorMode() {
  const layer = ensureDrawLayer();
  if (!layer) return;
  // 进入模式但不立即绘制，仅在按下左键拖动时绘制
  isPainting = false;
  censorBtn.textContent = 'Confirm';
  prevBtn.disabled = true;
  nextBtn.disabled = true;
  // Paint events
  const ctx = layer.getContext('2d');
  ctx.fillStyle = 'rgba(128, 0, 128, 0.7)'; // purple
  const imgRect = imageClientRect();
  function localPoint(e) {
    const rect = layer.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    return { x, y };
  }
  function drawDot(x, y) {
    ctx.beginPath();
    ctx.arc(x, y, brushRadius, 0, Math.PI * 2);
    ctx.closePath();
    ctx.fill();
  }
  function onDown(e) {
    // 仅响应左键
    if (e.button !== 0) return;
    e.preventDefault();
    isPainting = true;
    const p = localPoint(e);
    drawDot(p.x, p.y);
  }
  function onMove(e) {
    // 在鼠标移动时，如果未按住左键则不绘制
    if (!isPainting) return;
    if (e.buttons !== undefined && (e.buttons & 1) === 0) return;
    const p = localPoint(e);
    drawDot(p.x, p.y);
  }
  function onUp() { isPainting = false; }
  layer.addEventListener('mousedown', onDown);
  layer.addEventListener('mousemove', onMove);
  layer.addEventListener('mouseleave', onUp);
  window.addEventListener('mouseup', onUp, { once: false });
  // Store listeners for cleanup
  layer._listeners = { onDown, onMove, onUp };
}

function stopCensorMode(resetCanvas = true) {
  if (!drawLayer) return;
  const { onDown, onMove, onUp } = drawLayer._listeners || {};
  if (onDown) drawLayer.removeEventListener('mousedown', onDown);
  if (onMove) drawLayer.removeEventListener('mousemove', onMove);
  if (onUp) window.removeEventListener('mouseup', onUp);
  if (resetCanvas) {
    const ctx = drawLayer.getContext('2d');
    ctx.clearRect(0, 0, drawLayer.width, drawLayer.height);
  }
  isPainting = false;
  censorBtn.textContent = 'Censor';
  prevBtn.disabled = false;
  nextBtn.disabled = false;
  if (censorModeBtn) {
    censorModeBtn.hidden = true;
  }
  if (brushSizeBtn) {
    brushSizeBtn.hidden = true;
  }
}

async function confirmCensor() {
  if (!drawLayer || entries.length === 0) return;
  const e = entries[currentIndex];
  const j = e.json || {};
  const filename = basename(j.imagePath || '');
  if (!filename || !currentSlug) {
    importStatus.textContent = 'Cannot censor: missing filename or session slug';
    return;
  }
  // Export mask as PNG data URL
  const maskDataUrl = drawLayer.toDataURL('image/png');
  censorBtn.disabled = true;
  try {
    const res = await fetch(`${SERVER_BASE}/censor_manual`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slug: currentSlug, filename, mask: maskDataUrl, mode: censorMode }),
    });
    if (!res.ok) throw new Error(await res.text());
    const info = await res.json();
    importStatus.textContent = `Censored: ${filename}`;
    // Bust cache to reload censored image
    const old = e.imgUrl;
    const bust = `${old}${old.includes('?') ? '&' : '?'}t=${Date.now()}`;
    e.imgUrl = bust;
    updateViewer();
  } catch (e) {
    importStatus.textContent = 'Censor failed: ' + e.message;
  } finally {
    censorBtn.disabled = false;
    stopCensorMode();
  }
}

// Wire up buttons
if (deleteBtn) {
  deleteBtn.addEventListener('click', (e) => { e.preventDefault(); deleteCurrentEntry(); });
}
if (censorBtn) {
  censorBtn.addEventListener('click', (e) => {
    e.preventDefault();
    if (censorBtn.textContent === 'Confirm') {
      confirmCensor();
    } else {
      startCensorMode();
      // Show mode toggle when entering drawing mode
      if (censorModeBtn) {
        censorModeBtn.hidden = false;
        // keep previously selected mode
        setCensorMode(censorMode);
      }
      if (brushSizeBtn) {
        brushSizeBtn.hidden = false;
        // keep previously selected brush size
        setBrushLevel(brushLevel);
      }
    }
  });
}

// Mode toggle handler
if (censorModeBtn) {
  censorModeBtn.addEventListener('click', (e) => {
    e.preventDefault();
    setCensorMode(censorMode === 're' ? 'add' : 're');
  });
}

// Brush size toggle
if (brushSizeBtn) {
  brushSizeBtn.addEventListener('click', (e) => {
    e.preventDefault();
    cycleBrushLevel();
  });
}

// Chart modal interactions
if (chartModalClose) {
  chartModalClose.addEventListener('click', () => closeChartModal());
}
if (chartModal) {
  chartModal.addEventListener('click', (e) => {
    if (e.target === chartModal) closeChartModal();
  });
}

if (btnUnfoldFormatted) {
  btnUnfoldFormatted.addEventListener('click', () => {
    openChartModal('Activity Label Frequency', 'auto', 'chart-bars');
    renderFormattedChart(lastTagStats, chartModalBody);
    const overflow = chartModalBody.scrollWidth > chartModalBody.clientWidth || chartModalBody.scrollHeight > chartModalBody.clientHeight;
    chartModalContent.classList.toggle('wide', overflow);
    chartModalContent.classList.toggle('auto', !overflow);
  });
}

if (btnUnfoldAnnotation) {
  btnUnfoldAnnotation.addEventListener('click', () => {
    openChartModal('Annotation Activity Frequency', 'auto', 'chart-bars');
    const annStats = computeAnnotationTagStats(entries);
    renderFormattedChart(annStats, chartModalBody);
    const overflow = chartModalBody.scrollWidth > chartModalBody.clientWidth || chartModalBody.scrollHeight > chartModalBody.clientHeight;
    chartModalContent.classList.toggle('wide', overflow);
    chartModalContent.classList.toggle('auto', !overflow);
  });
}

if (btnUnfoldAnnotationHeatmap) {
  btnUnfoldAnnotationHeatmap.addEventListener('click', () => {
    openChartModal('Annotation Timeline Heatmap', 'wide', 'heatmap');
    const annStats = computeAnnotationTagStats(entries);
    renderAnnotationTimelineHeatmap(entries, annStats, chartModalBody);
    chartModalContent.classList.toggle('wide', true);
    chartModalContent.classList.toggle('auto', false);
  });
}

if (btnUnfoldAnnotationAccuracy) {
  btnUnfoldAnnotationAccuracy.addEventListener('click', () => {
    openChartModal('Annotation Activity Accuracy', 'auto', 'chart-bars');
    const annStats = computeAnnotationTagStats(entries);
    const annMetrics = computeAnnotationLabelMetrics(entries, annStats.map(s => s.label));
    renderAnnotationMetricChart(annStats, annMetrics, chartModalBody);
    const overflow = chartModalBody.scrollWidth > chartModalBody.clientWidth || chartModalBody.scrollHeight > chartModalBody.clientHeight;
    chartModalContent.classList.toggle('wide', overflow);
    chartModalContent.classList.toggle('auto', !overflow);
  });
}

if (btnUnfoldHeatmap) {
  btnUnfoldHeatmap.addEventListener('click', () => {
    openChartModal('Timeline Heatmap', 'wide', 'heatmap');
    renderTimelineHeatmap(entries, lastTagStats, chartModalBody);
    const overflow = chartModalBody.scrollWidth > chartModalBody.clientWidth || chartModalBody.scrollHeight > chartModalBody.clientHeight;
    chartModalContent.classList.toggle('wide', true);
    chartModalContent.classList.toggle('auto', !overflow);
  });
}

// Heatmap normalization toggle
if (btnHeatmapNorm) {
  // Initialize button label
  btnHeatmapNorm.textContent = (heatmapNormMode === 'global') ? 'Normalize: Global' : 'Normalize: Row';
  btnHeatmapNorm.addEventListener('click', () => {
    heatmapNormMode = (heatmapNormMode === 'global') ? 'row' : 'global';
    btnHeatmapNorm.textContent = (heatmapNormMode === 'global') ? 'Normalize: Global' : 'Normalize: Row';
    if (btnHeatmapNormAnnotation) {
      btnHeatmapNormAnnotation.textContent = (heatmapNormMode === 'global') ? 'Normalize: Global' : 'Normalize: Row';
    }
    // Re-render both dashboard and modal if open
    renderTimelineHeatmap(entries, lastTagStats, chartHeatmapEl);
    const annStats = computeAnnotationTagStats(entries);
    renderAnnotationTimelineHeatmap(entries, annStats, chartAnnotationHeatmapEl);
    if (chartModal && !chartModal.hidden && chartModalBody) {
      renderTimelineHeatmap(entries, lastTagStats, chartModalBody);
    }
  });
}

// Annotation heatmap normalization toggle
if (btnHeatmapNormAnnotation) {
  btnHeatmapNormAnnotation.textContent = (heatmapNormMode === 'global') ? 'Normalize: Global' : 'Normalize: Row';
  btnHeatmapNormAnnotation.addEventListener('click', () => {
    heatmapNormMode = (heatmapNormMode === 'global') ? 'row' : 'global';
    btnHeatmapNormAnnotation.textContent = (heatmapNormMode === 'global') ? 'Normalize: Global' : 'Normalize: Row';
    if (btnHeatmapNorm) {
      btnHeatmapNorm.textContent = (heatmapNormMode === 'global') ? 'Normalize: Global' : 'Normalize: Row';
    }
    const annStats = computeAnnotationTagStats(entries);
    renderAnnotationTimelineHeatmap(entries, annStats, chartAnnotationHeatmapEl);
    renderTimelineHeatmap(entries, lastTagStats, chartHeatmapEl);
    if (chartModal && !chartModal.hidden && chartModalBody) {
      renderAnnotationTimelineHeatmap(entries, annStats, chartModalBody);
    }
  });
}

if (btnAnnotationMetric) {
  btnAnnotationMetric.textContent = 'Metric: Accuracy';
  btnAnnotationMetric.addEventListener('click', () => {
    annotationMetricMode = (
      annotationMetricMode === 'accuracy' ? 'precision' : (
        annotationMetricMode === 'precision' ? 'f1' : 'accuracy'
      )
    );
    btnAnnotationMetric.textContent = (
      annotationMetricMode === 'precision' ? 'Metric: Precision' : (
        annotationMetricMode === 'f1' ? 'Metric: F1' : 'Metric: Accuracy'
      )
    );
    const annStats = computeAnnotationTagStats(entries);
    const annMetrics = computeAnnotationLabelMetrics(entries, annStats.map(s => s.label));
    renderAnnotationMetricChart(annStats, annMetrics, chartAnnotationAccuracyEl);
    if (chartModal && !chartModal.hidden && chartModalBody && chartModalTitle && chartModalTitle.textContent === 'Annotation Activity Accuracy') {
      renderAnnotationMetricChart(annStats, annMetrics, chartModalBody);
      const overflow = chartModalBody.scrollWidth > chartModalBody.clientWidth || chartModalBody.scrollHeight > chartModalBody.clientHeight;
      chartModalContent.classList.toggle('wide', overflow);
      chartModalContent.classList.toggle('auto', !overflow);
    }
  });
}

if (tabLoadViewBtn) {
  tabLoadViewBtn.addEventListener('click', (e) => {
    e.preventDefault();
    showLoadView();
  });
}
if (tabStatisticsBtn) {
  tabStatisticsBtn.addEventListener('click', (e) => {
    e.preventDefault();
    showStatistics();
  });
}

folderPicker.addEventListener('change', (e) => {
  const list = e.target.files;
  if (!list || list.length === 0) return;
  parseSession(list);
});

prevBtn.addEventListener('click', () => {
  if (entries.length === 0) return;
  currentIndex = (currentIndex - 1 + entries.length) % entries.length;
  updateViewer();
});
nextBtn.addEventListener('click', () => {
  if (entries.length === 0) return;
  currentIndex = (currentIndex + 1) % entries.length;
  updateViewer();
});

window.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowLeft') prevBtn.click();
  if (e.key === 'ArrowRight') nextBtn.click();
});
