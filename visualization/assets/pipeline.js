/* ═══════════════════════════════════════════════════════════════
   Grasshopper Pipeline — Shared Classes
   Battery · WireEngine · Canvas
   ═══════════════════════════════════════════════════════════════ */

/* ── Battery ─────────────────────────────────────────────── */
class Battery {
  constructor(cfg, idx) { this.cfg = cfg; this.idx = idx; this.el = null; }

  render() {
    const c = this.cfg;
    const wrapper = document.createElement('div');
    wrapper.className = 'batt-wrapper ' + c.theme + (this.idx % 2 === 1 ? ' labels-below' : '');
    const batt = document.createElement('div');
    batt.className = 'gh-battery';
    batt.id = 'batt-' + c.id;
    batt.appendChild(this._header(c));
    batt.appendChild(this._portsCol(c.portsIn, 'ports-in'));
    batt.appendChild(this._logicCol(c));
    batt.appendChild(this._portsCol(c.portsOut, 'ports-out'));
    if (c.footer) batt.appendChild(this._footer(c));
    wrapper.appendChild(batt);
    this.el = wrapper;
    return wrapper;
  }

  _header(c) {
    const h = document.createElement('div');
    h.className = 'batt-header';
    h.innerHTML =
      '<span class="batt-tag">' + c.label +
      ' <span class="batt-title">' + c.title + '</span></span>';
    return h;
  }

  _portsCol(ports, cls) {
    const col = document.createElement('div');
    col.className = 'ports-col ' + cls;
    const isIn = cls === 'ports-in';
    ports.forEach(p => {
      const item = document.createElement('div');
      item.className = 'port-item';
      const dotCls = 'port-dot' + (p.cls ? ' ' + p.cls : '');
      const lblCls = 'port-label' + (p.dark ? ' dark' : '');
      if (isIn) {
        item.innerHTML =
          '<div class="' + dotCls + '" data-port-id="' + p.id + '"></div>' +
          '<span class="' + lblCls + '">' + p.label + '</span>';
      } else {
        item.innerHTML =
          '<span class="' + lblCls + '">' + p.label + '</span>' +
          '<div class="' + dotCls + '" data-port-id="' + p.id + '"></div>';
      }
      col.appendChild(item);
    });
    return col;
  }

  _logicCol(c) {
    const col = document.createElement('div');
    col.className = 'logic-col';
    c.blocks.forEach((b, i) => {
      col.appendChild(this._innerBlock(b));
      if (c.sequential && i < c.blocks.length - 1) {
        const arrow = document.createElement('div');
        arrow.className = 'inner-arrow';
        arrow.innerHTML = '&#x25BC;';
        col.appendChild(arrow);
      }
    });
    return col;
  }

  _innerBlock(b) {
    const block = document.createElement('div');
    block.className = 'inner-block';

    // Left micro-port
    const mpL = document.createElement('div');
    mpL.className = 'micro-port';
    if (b.portIn) mpL.setAttribute('data-port-id', b.portIn);
    block.appendChild(mpL);

    // Content
    const content = document.createElement('div');
    content.className = 'inner-content';
    const tCls = b.titleClass ? ' class="' + b.titleClass + '"' : '';
    const tSty = b.titleStyle ? ' style="' + b.titleStyle + '"' : '';
    let html = '<div class="i-title"' + tCls + tSty + '>' + b.title + '</div>';
    html += '<div class="i-desc">' + b.desc + '</div>';
    if (b.subs && b.subs.length) {
      html += '<div class="block-subs">';
      b.subs.forEach(s => {
        if (typeof s === 'string') {
          html += '<div class="sub-box">' + s + '</div>';
        } else {
          html += '<div class="sub-box">' + s.label;
          if (s.children) {
            html += '<div class="sub-children">';
            s.children.forEach(c => { html += '<span class="sub-child">' + c + '</span>'; });
            html += '</div>';
          }
          html += '</div>';
        }
      });
      html += '</div>';
    }
    content.innerHTML = html;
    block.appendChild(content);

    // Right micro-port
    const mpR = document.createElement('div');
    mpR.className = 'micro-port';
    if (b.portOut) mpR.setAttribute('data-port-id', b.portOut);
    block.appendChild(mpR);

    return block;
  }

  _footer(c) {
    const f = document.createElement('div');
    f.className = 'batt-footer';
    f.innerHTML = c.footer;
    return f;
  }
}


/* ── WireEngine ──────────────────────────────────────────── */
class WireEngine {
  constructor(svgEl) {
    this.svg = svgEl;
    this.NS = 'http://www.w3.org/2000/svg';
  }

  draw(wires) {
    this.svg.innerHTML = '';
    wires.forEach(w => {
      const a = this._portCenter(w.from);
      const b = this._portCenter(w.to);
      if (!a || !b) return;

      switch (w.type) {
        case 'loop':      this._loop(a, b, w); break;
        case 'intLoop':   this._intLoop(a, b, w); break;
        case 'internal':  this._internal(a, b, w); break;
        case 'trigger':   this._trigger(a, b, w); break;
        default:          this._normal(a, b, w);
      }
    });
  }

  _portCenter(id) {
    const el = document.querySelector('[data-port-id="' + id + '"]');
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  }

  _path(d, color, extra) {
    const vwScale = window.innerWidth / 1600;
    const p = document.createElementNS(this.NS, 'path');
    p.setAttribute('d', d);
    p.setAttribute('stroke', color);
    p.setAttribute('stroke-width', 2 * vwScale);
    p.setAttribute('fill', 'none');
    p.setAttribute('opacity', '0.55');
    if (extra) {
      Object.entries(extra).forEach(([k, v]) => {
        if (k === 'stroke-width') v = parseFloat(v) * vwScale;
        if (k === 'stroke-dasharray') v = v.split(' ').map(n => parseFloat(n) * vwScale).join(' ');
        p.setAttribute(k, v);
      });
    }
    this.svg.appendChild(p);
  }

  _arrow(x, y, angle, color, opacity) {
    const vwScale = window.innerWidth / 1600;
    const s = 11 * vwScale;
    const hw = s * 0.4;
    const tipX = x + (s / 2) * Math.cos(angle);
    const tipY = y + (s / 2) * Math.sin(angle);
    const baseX = x - (s / 2) * Math.cos(angle);
    const baseY = y - (s / 2) * Math.sin(angle);
    const perpX = Math.cos(angle + Math.PI / 2) * hw;
    const perpY = Math.sin(angle + Math.PI / 2) * hw;
    const poly = document.createElementNS(this.NS, 'polygon');
    poly.setAttribute('points',
      tipX + ',' + tipY + ' ' +
      (baseX + perpX) + ',' + (baseY + perpY) + ' ' +
      (baseX - perpX) + ',' + (baseY - perpY));
    poly.setAttribute('fill', color);
    poly.setAttribute('opacity', opacity);
    this.svg.appendChild(poly);
  }

  _midArrow(P0, P1, P2, P3, color, opacity) {
    const t = 0.5, u = 0.5;
    const mx = u*u*u*P0.x + 3*u*u*t*P1.x + 3*u*t*t*P2.x + t*t*t*P3.x;
    const my = u*u*u*P0.y + 3*u*u*t*P1.y + 3*u*t*t*P2.y + t*t*t*P3.y;
    const dx = 3*(u*u*(P1.x-P0.x) + 2*u*t*(P2.x-P1.x) + t*t*(P3.x-P2.x));
    const dy = 3*(u*u*(P1.y-P0.y) + 2*u*t*(P2.y-P1.y) + t*t*(P3.y-P2.y));
    const odx = P3.x - P0.x, ody = P3.y - P0.y;
    const angle = (odx * dx + ody * dy) >= 0
      ? Math.atan2(dy, dx)
      : Math.atan2(ody, odx);
    this._arrow(mx, my, angle, color, opacity);
  }

  _normal(a, b, w) {
    const vwScale = window.innerWidth / 1600;
    const off = Math.max(Math.abs(b.x - a.x) * 0.42, 45 * vwScale);
    this._path(
      'M ' + a.x + ' ' + a.y +
      ' C ' + (a.x + off) + ' ' + a.y +
            ', ' + (b.x - off) + ' ' + b.y +
            ', ' + b.x + ' ' + b.y,
      w.color);
    this._midArrow(a, {x:a.x+off,y:a.y}, {x:b.x-off,y:b.y}, b, w.color, '0.55');
  }

  _loop(a, b, w) {
    const vwScale = window.innerWidth / 1600;
    const off = Math.max(Math.abs(b.x - a.x) * 0.42, 45 * vwScale);
    this._path(
      'M ' + a.x + ' ' + a.y +
      ' C ' + (a.x - off) + ' ' + a.y +
            ', ' + (b.x + off) + ' ' + b.y +
            ', ' + b.x + ' ' + b.y,
      w.color,
      { 'stroke-dasharray': '5 3', 'stroke-width': '1.5', opacity: '0.4' });
    this._midArrow(a, {x:a.x-off,y:a.y}, {x:b.x+off,y:b.y}, b, w.color, '0.4');
    if (w.label) {
      const t = 0.5, u = 0.5;
      const mx = u*u*u*a.x + 3*u*u*t*(a.x-off) + 3*u*t*t*(b.x+off) + t*t*t*b.x;
      const my = u*u*u*a.y + 3*u*u*t*a.y + 3*u*t*t*b.y + t*t*t*b.y;
      this._label(mx, my, w.label);
    }
  }

  _internal(a, b, w) {
    const vwScale = window.innerWidth / 1600;
    const off = Math.max(Math.abs(b.x - a.x) * 0.35, 15 * vwScale);
    this._path(
      'M ' + a.x + ' ' + a.y +
      ' C ' + (a.x + off) + ' ' + a.y +
            ', ' + (b.x - off) + ' ' + b.y +
            ', ' + b.x + ' ' + b.y,
      w.color,
      { opacity: '0.35' });
    this._midArrow(a, {x:a.x+off,y:a.y}, {x:b.x-off,y:b.y}, b, w.color, '0.35');
    if (w.label) {
      const t = 1/3;
      const mx = Math.pow(1-t,3)*a.x + 3*Math.pow(1-t,2)*t*(a.x+off) + 3*(1-t)*t*t*(b.x-off) + Math.pow(t,3)*b.x;
      const my = Math.pow(1-t,3)*a.y + 3*Math.pow(1-t,2)*t*a.y + 3*(1-t)*t*t*b.y + Math.pow(t,3)*b.y;
      this._label(mx, my, w.label);
    }
  }

  _trigger(a, b, w) {
    const vwScale = window.innerWidth / 1600;
    const off = Math.max(Math.abs(b.x - a.x) * 0.35, 15 * vwScale);
    this._path(
      'M ' + a.x + ' ' + a.y +
      ' C ' + (a.x + off) + ' ' + a.y +
            ', ' + (b.x - off) + ' ' + b.y +
            ', ' + b.x + ' ' + b.y,
      w.color,
      { 'stroke-dasharray': '2 4', 'stroke-width': '1.5', opacity: '0.45' });
    this._midArrow(a, {x:a.x+off,y:a.y}, {x:b.x-off,y:b.y}, b, w.color, '0.45');
    const t = 1/3;
    const mx = Math.pow(1-t,3)*a.x + 3*Math.pow(1-t,2)*t*(a.x+off) + 3*(1-t)*t*t*(b.x-off) + Math.pow(t,3)*b.x;
    const my = Math.pow(1-t,3)*a.y + 3*Math.pow(1-t,2)*t*a.y + 3*(1-t)*t*t*b.y + Math.pow(t,3)*b.y;
    this._label(mx, my, w.label, true);
  }

  _intLoop(a, b, w) {
    const vwScale = window.innerWidth / 1600;
    const h = 30 * vwScale;
    const portEl = document.querySelector('[data-port-id="' + w.from + '"]');
    const blockEl = portEl ? portEl.closest('.inner-block') : null;
    const blockTop = blockEl ? blockEl.getBoundingClientRect().top : Math.min(a.y, b.y);
    const boxH = blockEl ? blockEl.getBoundingClientRect().height : 30 * vwScale;
    const padding = Math.max(6, boxH * 0.12);
    const peakY = blockTop - padding;
    const midX = (a.x + b.x) / 2;
    this._path(
      'M ' + a.x + ' ' + a.y +
      ' C ' + (a.x + h) + ' ' + a.y +
      ', ' + (a.x + h) + ' ' + peakY +
      ', ' + midX + ' ' + peakY +
      ' S ' + (b.x - h) + ' ' + b.y +
      ', ' + b.x + ' ' + b.y,
      w.color,
      { opacity: '0.35', 'stroke-dasharray': '5 3' });
    this._arrow(midX, peakY, Math.PI, w.color, '0.35');
    if (w.label) {
      const t = 0.85;
      const mx = Math.pow(1-t,3)*a.x + 3*Math.pow(1-t,2)*t*(a.x+h) + 3*(1-t)*t*t*(a.x+h) + Math.pow(t,3)*midX;
      const my = Math.pow(1-t,3)*a.y + 3*Math.pow(1-t,2)*t*a.y + 3*(1-t)*t*t*peakY + Math.pow(t,3)*peakY;
      this._label(mx, my, w.label);
    }
  }

  _label(cx, cy, text, isTrigger) {
    const NS = this.NS;
    const g = document.createElementNS(NS, 'g');
    const t = document.createElementNS(NS, 'text');
    t.setAttribute('x', cx);
    t.setAttribute('y', cy);
    t.setAttribute('text-anchor', 'middle');
    t.setAttribute('dominant-baseline', 'central');
    t.setAttribute('font-size', isTrigger ? '0.66vw' : '0.72vw');
    t.setAttribute('font-family', "'Roboto', sans-serif");
    t.setAttribute('font-weight', isTrigger ? '400' : '600');
    if (isTrigger) t.setAttribute('letter-spacing', '0.05em');
    t.setAttribute('fill', isTrigger ? 'rgba(0,0,0,0.45)' : 'rgba(0,0,0,0.65)');
    t.textContent = text;
    g.appendChild(t);
    this.svg.appendChild(g);
    requestAnimationFrame(() => {
      const bbox = t.getBBox();
      const vw = window.innerWidth / 100;
      const px = 0.06 * vw, py = 0.25 * vw;
      const rect = document.createElementNS(NS, 'rect');
      rect.setAttribute('x', bbox.x - py);
      rect.setAttribute('y', bbox.y - px);
      rect.setAttribute('width', bbox.width + py * 2);
      rect.setAttribute('height', bbox.height + px * 2);
      rect.setAttribute('rx', 0.2 * vw);
      rect.setAttribute('fill', 'rgba(255,255,255,0.9)');
      if (isTrigger) {
        rect.setAttribute('stroke', 'rgba(0,0,0,0.15)');
        const vwScale = window.innerWidth / 1600;
        rect.setAttribute('stroke-width', 0.5 * vwScale);
        rect.setAttribute('stroke-dasharray', `${2 * vwScale} ${2 * vwScale}`);
      } else {
        rect.setAttribute('stroke', 'none');
      }
      g.insertBefore(rect, t);
    });
  }
}


/* ── Canvas ───────────────────────────────────────────────── */
class Canvas {
  constructor(containerId, svgId) {
    this.container = document.getElementById(containerId);
    this.wireEngine = new WireEngine(document.getElementById(svgId));
  }

  build(layers, wires) {
    this.container.innerHTML = '';
    layers.forEach((l, i) => {
      this.container.appendChild(new Battery(l, i).render());
    });
    this.wireEngine.draw(wires);
    window.addEventListener('resize', () => this.wireEngine.draw(wires));
  }
}
