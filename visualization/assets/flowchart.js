/* ═══════════════════════════════════════════════════════════════
   Flowchart — Shared Drawing Engine
   ═══════════════════════════════════════════════════════════════ */

class FlowChart {
  constructor(chartId, svgId) {
    this.chart = document.getElementById(chartId);
    this.svg   = document.getElementById(svgId);
    this.ns    = 'http://www.w3.org/2000/svg';
    this.color = '#555';
  }

  clear() { this.svg.innerHTML = ''; }

  /* ── Primitives ─────────────────────────────── */

  box(id) {
    const el = document.getElementById(id);
    if (!el) return null;
    const r  = el.getBoundingClientRect();
    const cr = this.chart.getBoundingClientRect();
    return {
      x: r.left - cr.left, y: r.top - cr.top,
      w: r.width, h: r.height,
      cx: r.left + r.width / 2 - cr.left,
      cy: r.top  + r.height / 2 - cr.top
    };
  }

  mkPath(d, color, opacity, dashed) {
    const p = document.createElementNS(this.ns, 'path');
    p.setAttribute('d', d);
    p.setAttribute('fill', 'none');
    p.setAttribute('stroke', color);
    p.setAttribute('stroke-width', '2');
    p.setAttribute('opacity', opacity);
    if (dashed) p.setAttribute('stroke-dasharray', '5 3');
    this.svg.appendChild(p);
    return p;
  }

  mkArrow(x, y, angle, fill, opacity) {
    const s = 9, hw = s * 0.38;
    const cos  = Math.cos(angle),  sin  = Math.sin(angle);
    const pcos = Math.cos(angle + Math.PI / 2), psin = Math.sin(angle + Math.PI / 2);
    const poly = document.createElementNS(this.ns, 'polygon');
    poly.setAttribute('points',
      (x + s/2*cos) + ',' + (y + s/2*sin) + ' ' +
      (x - s/2*cos + hw*pcos) + ',' + (y - s/2*sin + hw*psin) + ' ' +
      (x - s/2*cos - hw*pcos) + ',' + (y - s/2*sin - hw*psin));
    poly.setAttribute('fill', fill);
    poly.setAttribute('opacity', opacity);
    this.svg.appendChild(poly);
  }

  mkLabel(cx, cy, text) {
    const ns = this.ns;
    const g = document.createElementNS(ns, 'g');
    const lines = text.split('\n');
    const lineH = window.innerWidth * 0.012;
    const totalH = lineH * (lines.length - 1);
    const startY = cy - totalH / 2;

    lines.forEach((line, i) => {
      const t = document.createElementNS(ns, 'text');
      t.setAttribute('x', cx);
      t.setAttribute('y', startY + i * lineH);
      t.setAttribute('text-anchor', 'middle');
      t.setAttribute('dominant-baseline', 'central');
      t.setAttribute('font-size', '0.66vw');
      t.setAttribute('font-family', "'Helvetica Neue', Arial, sans-serif");
      t.setAttribute('font-weight', '600');
      t.setAttribute('fill', 'rgba(0,0,0,0.65)');
      t.textContent = line;
      g.appendChild(t);
    });

    this.svg.appendChild(g);
    requestAnimationFrame(() => {
      const bbox = g.getBBox();
      const vw = window.innerWidth / 100;
      const px = 0.06 * vw, py = 0.25 * vw;
      const rect = document.createElementNS(ns, 'rect');
      rect.setAttribute('x', bbox.x - py);
      rect.setAttribute('y', bbox.y - px);
      rect.setAttribute('width', bbox.width + py * 2);
      rect.setAttribute('height', bbox.height + px * 2);
      rect.setAttribute('rx', 0.2 * vw);
      rect.setAttribute('fill', 'rgba(255,255,255,0.9)');
      rect.setAttribute('stroke', 'none');
      g.insertBefore(rect, g.firstChild);
    });
  }

  /* ── Connection Types ───────────────────────── */

  /* Horizontal bezier: right-edge of A → left-edge of B */
  hConnect(aId, bId, opts = {}) {
    const a = this.box(aId), b = this.box(bId);
    if (!a || !b) return;
    const x1 = a.x + a.w, y1 = a.cy;
    const x2 = b.x,       y2 = b.cy;
    const off = Math.max(Math.abs(x2 - x1) * 0.42, 20);
    const color = opts.color || this.color;
    const op = opts.opacity || '0.55';
    this.mkPath(`M ${x1} ${y1} C ${x1+off} ${y1}, ${x2-off} ${y2}, ${x2} ${y2}`, color, op, opts.dashed);
    this.mkArrow(x2, y2, 0, color, op);
    if (opts.label) {
      const t = 0.5;
      const mx = (1-t)**3*x1 + 3*(1-t)**2*t*(x1+off) + 3*(1-t)*t**2*(x2-off) + t**3*x2;
      const my = (1-t)**3*y1 + 3*(1-t)**2*t*y1 + 3*(1-t)*t**2*y2 + t**3*y2;
      this.mkLabel(mx, my, opts.label);
    }
  }

  /* Vertical bezier: bottom-edge of A → top-edge of B */
  vConnect(aId, bId, opts = {}) {
    const a = this.box(aId), b = this.box(bId);
    if (!a || !b) return;
    const x1 = a.cx, y1 = a.y + a.h;
    const x2 = b.cx, y2 = b.y;
    const off = Math.max(Math.abs(y2 - y1) * 0.42, 15);
    const color = opts.color || this.color;
    const op = opts.opacity || '0.55';
    this.mkPath(`M ${x1} ${y1} C ${x1} ${y1+off}, ${x2} ${y2-off}, ${x2} ${y2}`, color, op, opts.dashed);
    this.mkArrow(x2, y2, Math.PI / 2, color, op);
    if (opts.label) {
      const t = 0.5;
      const mx = (1-t)**3*x1 + 3*(1-t)**2*t*x1 + 3*(1-t)*t**2*x2 + t**3*x2;
      const my = (1-t)**3*y1 + 3*(1-t)**2*t*(y1+off) + 3*(1-t)*t**2*(y2-off) + t**3*y2;
      this.mkLabel(mx, my, opts.label);
    }
  }

  /* Loop: bottom of A → bottom of B, arcing below */
  loopDown(aId, bId, opts = {}) {
    const a = this.box(aId), b = this.box(bId);
    if (!a || !b) return;
    const x1 = a.cx, y1 = a.y + a.h;
    const x2 = b.cx, y2 = b.y + b.h;
    const midY = Math.max(y1, y2) + 20;
    const color = opts.color || this.color;
    const op = opts.opacity || '0.35';
    this.mkPath(`M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`, color, op, true);
    this.mkArrow(x2, y2, -Math.PI / 2, color, op);
  }

  /* Loop: top of A → top of B, arcing above */
  loopUp(aId, bId, opts = {}) {
    const a = this.box(aId), b = this.box(bId);
    if (!a || !b) return;
    const x1 = a.cx, y1 = a.y;
    const x2 = b.cx, y2 = b.y;
    const peakY = Math.min(y1, y2) - 18;
    const color = opts.color || this.color;
    const op = opts.opacity || '0.35';
    this.mkPath(`M ${x1} ${y1} C ${x1} ${peakY}, ${x2} ${peakY}, ${x2} ${y2}`, color, op, true);
    this.mkArrow(x2, y2, Math.PI / 2, color, op);
    if (opts.label) {
      this.mkLabel(x2, peakY - 4, opts.label);
    }
  }

  /* Upward arc: top of A → bottom of B, arcing left */
  arcUp(aId, bId, opts = {}) {
    const a = this.box(aId), b = this.box(bId);
    if (!a || !b) return;
    const x1 = a.cx, y1 = a.y;
    const x2 = b.cx, y2 = b.y + b.h;
    const leftX = Math.min(x1, x2) - 30;
    const color = opts.color || this.color;
    const op = opts.opacity || '0.55';
    this.mkPath(`M ${x1} ${y1} C ${leftX} ${y1}, ${leftX} ${y2}, ${x2} ${y2}`, color, op, true);
    this.mkArrow(x2, y2, -Math.PI / 2, color, op);
    if (opts.label) {
      const t = 0.5;
      const mx = (1-t)**3*x1 + 3*(1-t)**2*t*leftX + 3*(1-t)*t**2*leftX + t**3*x2;
      const my = (1-t)**3*y1 + 3*(1-t)**2*t*y1 + 3*(1-t)*t**2*y2 + t**3*y2;
      this.mkLabel(mx, my, opts.label);
    }
  }

  /* Side loop: left edge of A → left edge of B, arcing far left */
  sideLoop(aId, bId, opts = {}) {
    const a = this.box(aId), b = this.box(bId);
    if (!a || !b) return;
    const x1 = a.x, y1 = a.cy;
    const x2 = b.x, y2 = b.cy;
    const leftX = Math.min(x1, x2) - (opts.leftOffset || 35);
    const color = opts.color || this.color;
    const op = opts.opacity || '0.35';
    this.mkPath(`M ${x1} ${y1} C ${leftX} ${y1}, ${leftX} ${y2}, ${x2} ${y2}`, color, op, !opts.solid);
    this.mkArrow(x2, y2, 0, color, op);
    if (opts.label) {
      const t = 0.5;
      const mx = (1-t)**3*x1 + 3*(1-t)**2*t*leftX + 3*(1-t)*t**2*leftX + t**3*x2;
      const my = (1-t)**3*y1 + 3*(1-t)**2*t*y1 + 3*(1-t)*t**2*y2 + t**3*y2;
      this.mkLabel(mx, my, opts.label);
    }
  }

  /* Side loop right: right edge of A → right edge of B, arcing far right */
  sideLoopRight(aId, bId, opts = {}) {
    const a = this.box(aId), b = this.box(bId);
    if (!a || !b) return;
    const x1 = a.x + a.w, y1 = a.cy;
    const x2 = b.x + b.w, y2 = b.cy;
    const rightX = Math.max(x1, x2) + (opts.rightOffset || 35);
    const color = opts.color || this.color;
    const op = opts.opacity || '0.35';
    this.mkPath(`M ${x1} ${y1} C ${rightX} ${y1}, ${rightX} ${y2}, ${x2} ${y2}`, color, op, !opts.solid);
    this.mkArrow(x2, y2, Math.PI, color, op);
    if (opts.label) {
      const t = 0.5;
      const mx = (1-t)**3*x1 + 3*(1-t)**2*t*rightX + 3*(1-t)*t**2*rightX + t**3*x2;
      const my = (1-t)**3*y1 + 3*(1-t)**2*t*y1 + 3*(1-t)*t**2*y2 + t**3*y2;
      this.mkLabel(mx, my, opts.label);
    }
  }

  /* Vertical bezier reverse: top-edge of A → bottom-edge of B (B is above A) */
  vConnectReverse(aId, bId, opts = {}) {
    const a = this.box(aId), b = this.box(bId);
    if (!a || !b) return;
    const x1 = a.cx, y1 = a.y;
    const x2 = b.cx, y2 = b.y + b.h;
    const off = Math.max(Math.abs(y1 - y2) * 0.42, 15);
    const color = opts.color || this.color;
    const op = opts.opacity || '0.55';
    this.mkPath(`M ${x1} ${y1} C ${x1} ${y1-off}, ${x2} ${y2+off}, ${x2} ${y2}`, color, op, opts.dashed);
    this.mkArrow(x2, y2, -Math.PI / 2, color, op);
    if (opts.label) {
      const t = 0.5;
      const mx = (1-t)**3*x1 + 3*(1-t)**2*t*x1 + 3*(1-t)*t**2*x2 + t**3*x2;
      const my = (1-t)**3*y1 + 3*(1-t)**2*t*(y1-off) + 3*(1-t)*t**2*(y2+off) + t**3*y2;
      this.mkLabel(mx, my, opts.label);
    }
  }

  /* Horizontal bezier reverse: left-edge of A → right-edge of B (B is to the left of A) */
  hConnectReverse(aId, bId, opts = {}) {
    const a = this.box(aId), b = this.box(bId);
    if (!a || !b) return;
    const x1 = a.x,       y1 = a.cy;
    const x2 = b.x + b.w, y2 = b.cy;
    const off = Math.max(Math.abs(x1 - x2) * 0.42, 20);
    const color = opts.color || this.color;
    const op = opts.opacity || '0.55';
    this.mkPath(`M ${x1} ${y1} C ${x1-off} ${y1}, ${x2+off} ${y2}, ${x2} ${y2}`, color, op, opts.dashed);
    this.mkArrow(x2, y2, Math.PI, color, op);
    if (opts.label) {
      const t = 0.5;
      const mx = (1-t)**3*x1 + 3*(1-t)**2*t*(x1-off) + 3*(1-t)*t**2*(x2+off) + t**3*x2;
      const my = (1-t)**3*y1 + 3*(1-t)**2*t*y1 + 3*(1-t)*t**2*y2 + t**3*y2;
      this.mkLabel(mx, my, opts.label);
    }
  }

  /* Long diagonal: bottom of A → top of B, skipping intermediate rows */
  diagConnect(aId, bId, opts = {}) {
    const a = this.box(aId), b = this.box(bId);
    if (!a || !b) return;
    const x1 = a.cx, y1 = a.y + a.h;
    const x2 = b.cx, y2 = b.y;
    const off = Math.max(Math.abs(y2 - y1) * 0.35, 20);
    const color = opts.color || this.color;
    const op = opts.opacity || '0.35';
    this.mkPath(`M ${x1} ${y1} C ${x1} ${y1+off}, ${x2} ${y2-off}, ${x2} ${y2}`, color, op, opts.dashed);
    this.mkArrow(x2, y2, Math.PI / 2, color, op);
    if (opts.label) {
      const t = 0.5;
      const mx = (1-t)**3*x1 + 3*(1-t)**2*t*x1 + 3*(1-t)*t**2*x2 + t**3*x2;
      const my = (1-t)**3*y1 + 3*(1-t)**2*t*(y1+off) + 3*(1-t)*t**2*(y2-off) + t**3*y2;
      this.mkLabel(mx, my, opts.label);
    }
  }
}
