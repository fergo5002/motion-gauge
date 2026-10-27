// motion-gauge's in-page measurements. Installed by an init script on every page the gauge opens,
// so it is in place before the page's own scripts run. Keep this file ASCII.
//
// Visible means: nothing on the way up has display none, the element's own visibility is visible,
// opacity times filter opacity() (multiplied up to the root) is at least 0.05, and ancestors that clip
// leave some of it showing. Ghosted means inside a .ghost element or fainter than 0.2.
(function () {
  "use strict";
  if (window.__gauge) return;
  var G = {};
  var ids = new WeakMap(), seq = 0;
  function idOf(e) { var v = ids.get(e); if (!v) { v = ++seq; ids.set(e, v); } return v; }
  function name(e) {
    var cls = (e.getAttribute && e.getAttribute("class") || "").trim();
    return e.tagName.toLowerCase() + (e.id ? "#" + e.id : "") + (cls ? "." + cls.split(/\s+/).join(".") : "");
  }
  function alphaOf(v) {
    if (!v || v === "none" || v === "transparent") return 0;
    if (/^url\(/.test(v)) return 1;
    var m = /rgba?\(([^)]*)\)/.exec(v);
    if (!m) return 1;
    var p = m[1].split(/[\s,\/]+/).filter(Boolean);
    if (p.length < 4) return 1;
    var a = p[3];
    return /%$/.test(a) ? parseFloat(a) / 100 : parseFloat(a);
  }
  function filterOpacity(f) {
    if (!f || f === "none") return 1;
    var out = 1, re = /opacity\(\s*([\d.]+)(%?)\s*\)/g, m;
    while ((m = re.exec(f))) out *= m[2] ? parseFloat(m[1]) / 100 : parseFloat(m[1]);
    return out;
  }
  function rectOf(r) { return {l: r.left, t: r.top, r: r.right, b: r.bottom}; }
  function inter(a, b) { return {l: Math.max(a.l, b.l), t: Math.max(a.t, b.t), r: Math.min(a.r, b.r), b: Math.min(a.b, b.b)}; }
  function area(a) { return Math.max(0, a.r - a.l) * Math.max(0, a.b - a.t); }

  // One reading of the page. Computed styles and boxes are cached for the reading only.
  // The view is the part of the frame a viewer can see: the frame's box cut by the window and by every
  // ancestor that clips. k is CSS pixels per frame pixel: the frame's rendered width over its layout
  // width (1 unless the frame is scaled). Positions are reported in frame pixels from the view's top
  // left.
  function Reading(frameSel, opts) {
    opts = opts || {};
    var styles = new Map(), boxes = new Map();
    this.css = function (n) { var c = styles.get(n); if (!c) { c = getComputedStyle(n); styles.set(n, c); } return c; };
    this.box = function (n) { var b = boxes.get(n); if (!b) { b = rectOf(n.getBoundingClientRect()); boxes.set(n, b); } return b; };
    this.frame = typeof frameSel === "string" ? document.querySelector(frameSel) : frameSel;
    if (!this.frame) throw new Error("gauge: no frame matches " + frameSel);
    var raw = this.box(this.frame), fr = inter(raw, {l: 0, t: 0, r: innerWidth, b: innerHeight});
    for (var n = this.frame.parentElement; n && n !== document.documentElement && n !== document.body; n = n.parentElement) {
      var c = this.css(n);
      if (c.overflowX !== "visible" || c.overflowY !== "visible") fr = inter(fr, this.box(n));
    }
    this.fr = fr;
    this.k = this.frame.offsetWidth ? (raw.r - raw.l) / this.frame.offsetWidth : 1;
    this.W = (fr.r - fr.l) / this.k;
    this.H = (fr.b - fr.t) / this.k;
  }
  var NOT_RENDERED = "defs, mask, clipPath, symbol, marker, pattern, linearGradient, radialGradient, filter, title, desc, script, style, template, noscript";
  // shown: nothing hides it; a: opacity times filter opacity, multiplied up to the root; ghost: in a
  // .ghost or fainter than 0.2; dim: in a .dim.
  Reading.prototype.look = function (e) {
    var shown = !(e.closest && e.closest(NOT_RENDERED)), a = 1, ghost = false, dim = false;
    for (var n = e; shown && n && n.nodeType === 1; n = n.parentElement) {
      var c = this.css(n);
      if (c.display === "none" || (n === e && c.visibility !== "visible")) { shown = false; break; }
      a *= (+c.opacity) * filterOpacity(c.filter);
      if (n.classList) { if (n.classList.contains("ghost")) ghost = true; if (n.classList.contains("dim")) dim = true; }
    }
    return {shown: shown && a >= 0.05, a: a, ghost: ghost || a < 0.2, dim: dim};
  };
  // A rect clipped by every ancestor below the frame whose overflow is not visible (a collapsed
  // max-height box, a screen-reader-only span), and optionally by the frame itself.
  Reading.prototype.clip = function (e, r, withFrame) {
    var out = r;
    for (var n = e.parentElement; n && n !== this.frame; n = n.parentElement) {
      var c = this.css(n);
      if (c.overflowX !== "visible" || c.overflowY !== "visible" || (c.clipPath && c.clipPath !== "none" && /inset\(\s*50%/.test(c.clipPath))) out = inter(out, this.box(n));
    }
    return withFrame ? inter(out, this.fr) : out;
  };
  // An SVG shape's box with its stroke: a straight stroked line has a geometry box with no height or
  // no width.
  Reading.prototype.shapeBox = function (e) {
    var b = this.box(e);
    if (!(e instanceof SVGElement) || e.tagName.toLowerCase() === "svg") return b;
    var c = this.css(e);
    if (c.stroke === "none" || !(parseFloat(c.strokeWidth) > 0)) return b;
    var sw = parseFloat(c.strokeWidth) * (this.k || 1) / 2;
    return {l: b.l - sw, t: b.t - sw, r: b.r + sw, b: b.b + sw};
  };
  // In frame pixels, relative to the view's top left.
  Reading.prototype.local = function (r) {
    var k = this.k || 1;
    return {l: (r.l - this.fr.l) / k, t: (r.t - this.fr.t) / k, r: (r.r - this.fr.l) / k, b: (r.b - this.fr.t) / k};
  };

  var SHAPES = {path: 1, circle: 1, rect: 1, ellipse: 1, line: 1, polyline: 1, polygon: 1, text: 1, image: 1, use: 1};
  function ownText(e) { for (var c = e.firstChild; c; c = c.nextSibling) if (c.nodeType === 3 && c.textContent.trim()) return true; return false; }
  function borderShows(c) {
    return ["Top", "Right", "Bottom", "Left"].some(function (s) {
      return parseFloat(c["border" + s + "Width"]) > 0 && c["border" + s + "Style"] !== "none" && c["border" + s + "Style"] !== "hidden" && alphaOf(c["border" + s + "Color"]) > 0.05;
    });
  }
  // A stroked path whose dash hides all of it (an undrawn wire), directly or through its mask.
  function undrawn(e, c, R) {
    var m = (e.getAttribute("mask") || "").match(/url\(#([^)]+)\)/);
    if (m) {
      var mk = document.getElementById(m[1]), ps = mk ? mk.querySelectorAll("path") : [];
      if (ps.length) return Array.prototype.every.call(ps, function (p) { return dashHides(p, R.css(p)); });
    }
    return dashHides(e, c);
  }
  function dashHides(e, c) {
    if (!c.strokeDasharray || c.strokeDasharray === "none") return false;
    var L = e.hasAttribute("pathLength") ? parseFloat(e.getAttribute("pathLength")) : (e.getTotalLength ? e.getTotalLength() : 0);
    if (!(L > 0)) return false;
    var dash = parseFloat(c.strokeDasharray.split(/[\s,]+/)[0]), off = Math.abs(parseFloat(c.strokeDashoffset) || 0);
    return dash >= L * 0.999 && off >= L * 0.999;
  }
  // What an element paints itself, or null. An inline SVG no larger than 64 by 64 frame pixels is one
  // mark (an icon), and its insides are skipped.
  Reading.prototype.paints = function (e) {
    var c = this.css(e), tag = e.tagName.toLowerCase();
    if (e instanceof SVGElement) {
      if (tag === "svg") {
        var b = this.box(e), k = this.k || 1;
        return (b.r - b.l) / k <= 64 && (b.b - b.t) / k <= 64 ? {icon: true} : null;
      }
      if (!SHAPES[tag]) return null;
      if (tag === "text") return {text: true};
      var fill = c.fill !== "none" && alphaOf(c.fill) * (+c.fillOpacity) > 0.05;
      var stroke = c.stroke !== "none" && alphaOf(c.stroke) * (+c.strokeOpacity) > 0.05 && parseFloat(c.strokeWidth) > 0;
      if (stroke && !fill && undrawn(e, c, this)) stroke = false;
      if (!fill && !stroke) return null;
      return fill ? {fill: true} : {stroke: true};
    }
    var p = {};
    if (tag === "img" || tag === "video" || tag === "canvas" || tag === "iframe") p.media = true;
    if (ownText(e)) p.text = true;
    if (alphaOf(c.backgroundColor) > 0.05 || (c.backgroundImage && c.backgroundImage !== "none")) p.box = true;
    if (borderShows(c)) p.box = true;
    return p.media || p.text || p.box ? p : null;
  };

  function words(s) { var t = s.trim(); return t ? t.split(/\s+/).length : 0; }
  function textInk(el, c) {
    if (el instanceof SVGElement) return c.fill === "none" ? 0 : alphaOf(c.fill) * (+c.fillOpacity);
    return Math.min(alphaOf(c.color), alphaOf(c.webkitTextFillColor || c.color));
  }

  // The settled frame: text runs, words, lit, dim, ghosts, coverage, loops.
  G.settled = function (frameSel, opts) {
    opts = opts || {};
    var R = new Reading(frameSel, opts), frame = R.frame, k = R.k || 1, W = R.W, H = R.H;
    var out = {text_runs: 0, words: 0, lit: 0, dim: 0, ghosts: 0, texts: [], lit_names: [],
      frame: {w: Math.round(W * 10) / 10, h: Math.round(H * 10) / 10, k: k, view: [R.fr.l, R.fr.t, R.fr.r, R.fr.b]}};
    var cover = [];   // rects in frame pixels
    // text runs
    var tw = document.createTreeWalker(frame, NodeFilter.SHOW_TEXT), range = document.createRange();
    for (var t = tw.nextNode(); t; t = tw.nextNode()) {
      var s = t.textContent;
      if (!s.trim()) continue;
      var el = t.parentElement;
      if (!el) continue;
      var v = R.look(el);
      if (!v.shown || v.ghost) continue;
      if (textInk(el, R.css(el)) <= 0.05) continue;
      var rects = [];
      if (el instanceof SVGElement) rects = [R.box(el)];
      else { range.selectNodeContents(t); rects = Array.prototype.map.call(range.getClientRects(), rectOf); }
      var seen = 0;
      rects.forEach(function (r0) {
        var r = R.clip(el, r0, true);
        if ((r.r - r.l) >= 2 && (r.b - r.t) >= 2) { seen += area(r); cover.push(R.local(r)); }
      });
      if (seen < 4) continue;
      out.text_runs++;
      out.words += words(s);
      if (out.texts.length < 400) out.texts.push(s.trim().replace(/\s+/g, " ").slice(0, 60));
    }
    // painted elements
    var all = frame.querySelectorAll("*"), skip = null, frameArea = W * H;
    for (var i = 0; i < all.length; i++) {
      var e = all[i];
      if (skip && skip.contains(e)) continue;
      skip = null;
      var p = R.paints(e);
      if (!p) continue;
      if (p.icon) skip = e;
      var lv = R.look(e);
      if (!lv.shown) continue;
      var r1 = R.clip(e, R.shapeBox(e), true);
      if (area(r1) < 4) continue;
      if (lv.ghost) { out.ghosts++; continue; }
      out.lit++;
      if (lv.dim) out.dim++;
      if (out.lit_names.length < 600) out.lit_names.push(name(e));
      var loc = R.local(r1);
      if ((p.box || p.media || p.fill || p.icon) && area(loc) < frameArea * 0.5) cover.push(loc);
    }
    out.coverage = grid(cover, W, H, opts.rows || 6, opts.cols || 8);
    // Endless animations in the frame. A seek pauses every animation, so a paused one counts too.
    out.loops = document.getAnimations().filter(function (a) {
      try { return (a.playState === "running" || a.playState === "paused") && a.effect && a.effect.getComputedTiming().iterations === Infinity && frame.contains(a.effect.target); } catch (err) { return false; }
    }).length;
    return out;
  };

  // The share of each cell covered by the union of rects, on a 4 px raster in frame pixels.
  function grid(rects, W, H, rows, cols) {
    var S = 4, gw = Math.ceil(W / S), gh = Math.ceil(H / S), bits = new Uint8Array(gw * gh);
    rects.forEach(function (r) {
      var x0 = Math.max(0, Math.floor(r.l / S)), x1 = Math.min(gw, Math.ceil(r.r / S)), y0 = Math.max(0, Math.floor(r.t / S)), y1 = Math.min(gh, Math.ceil(r.b / S));
      for (var y = y0; y < y1; y++) for (var x = x0; x < x1; x++) {
        // a raster cell counts when the rect covers at least half of it
        var cx = (x + 0.5) * S, cy = (y + 0.5) * S;
        if (cx >= r.l && cx <= r.r && cy >= r.t && cy <= r.b) bits[y * gw + x] = 1;
      }
    });
    var cells = [];
    for (var rI = 0; rI < rows; rI++) {
      var row = [];
      for (var cI = 0; cI < cols; cI++) {
        var gx0 = Math.round(cI * gw / cols), gx1 = Math.round((cI + 1) * gw / cols), gy0 = Math.round(rI * gh / rows), gy1 = Math.round((rI + 1) * gh / rows), n = 0, tot = 0;
        for (var yy = gy0; yy < gy1; yy++) for (var xx = gx0; xx < gx1; xx++) { tot++; n += bits[yy * gw + xx]; }
        row.push(tot ? Math.round(n / tot * 1000) / 1000 : 0);
      }
      cells.push(row);
    }
    return cells;
  }

  // ------------------------------------------------------------------ movers
  // A mover is an element whose own animated properties change between two samples. Own values only:
  // a property children inherit (visibility, colour, fill, stroke, text fill) is recorded only where
  // it differs from the parent's, and an element that starts or stops rendering, or enters or leaves
  // the DOM, together with its parent is the parent's change. So a card that fades in, a box whose
  // colour changes or a panel switched on is one mover, however many children carry the change.
  var PROPS = ["display", "opacity", "transform", "translate", "scale", "rotate", "strokeDashoffset", "clipPath",
    "offsetDistance", "width", "height", "left", "top", "backgroundColor", "borderTopColor", "boxShadow", "filter"];
  var INHERITED = ["visibility", "color", "fill", "stroke", "webkitTextFillColor"];
  // Colours that follow currentColor (a border, an icon's fill) are recorded as "cc" when they equal
  // the element's own colour, so they change only when the colour itself is the element's own.
  var FOLLOWS = {borderTopColor: 1, fill: 1, stroke: 1, webkitTextFillColor: 1};
  function sig(e, c, pc) {
    var own = function (p) { return FOLLOWS[p] && c[p] === c.color ? "cc" : c[p]; };
    var s = PROPS.map(own).join("|");
    s += "|" + INHERITED.map(function (p) { return pc && pc[p] === c[p] ? "~" : own(p); }).join("|");
    if (e.children.length === 0) s += "|" + e.textContent;
    return s;
  }
  // A path inside a mask renders nothing itself but draws the wire it masks, so it always counts as
  // rendered; anything else renders when it has a box.
  function rendered(e) { return e.getClientRects().length > 0 || !!(e.closest && e.closest("mask")); }
  var W0 = null;
  G.windowStart = function (rootSel, track, opts) {
    W0 = {root: rootSel, prev: null, changed: new Map(), intervals: [], track: track || [], samples: [], opts: opts || {}};
  };
  // One sample: every element under the root (the root included), and the tracked selectors' boxes.
  G.sample = function (at) {
    var w = W0, root = document.querySelector(w.root);
    if (!root) throw new Error("gauge: no root " + w.root);
    var now = new Map(), css = new Map(), els = [root].concat(Array.prototype.slice.call(root.querySelectorAll("*")));
    function cs(n) { var c = css.get(n); if (!c) { c = getComputedStyle(n); css.set(n, c); } return c; }
    els.forEach(function (e) {
      if (e.closest(NOT_RENDERED) && e.tagName.toLowerCase() !== "path") return;
      var r = rendered(e), par = e.parentElement;
      now.set(idOf(e), {e: e, r: r, p: par ? idOf(par) : 0,
        s: r ? sig(e, cs(e), par ? cs(par) : null) : "unrendered|" + cs(e).display});
    });
    if (w.prev) {
      var prev = w.prev, n = 0;
      var flipped = function (id) { var a = prev.get(id), b = now.get(id); return !a || !b || a.r !== b.r; };
      now.forEach(function (v, id) {
        var p = prev.get(id);
        if (p && p.s === v.s) return;
        if (flipped(id) && v.p && flipped(v.p) && (prev.has(v.p) || now.has(v.p))) return;   // the parent's change
        n++;
        if (!w.changed.has(id)) w.changed.set(id, v.e);
      });
      prev.forEach(function (v, id) {
        if (now.has(id)) return;
        if (v.p && !now.has(v.p) && prev.has(v.p)) return;   // removed with its parent
        n++;
        if (!w.changed.has(id)) w.changed.set(id, v.e);
      });
      w.intervals.push(n);
    }
    w.prev = now;
    if (w.track.length) w.samples.push({at: at, els: G.boxes(w.root, w.track, w.opts)});
    return true;
  };
  G.windowEnd = function () {
    var w = W0, names = [];
    w.changed.forEach(function (e) { if (names.length < 40) names.push(name(e)); });
    var out = {window: w.changed.size, peak: w.intervals.length ? Math.max.apply(null, w.intervals) : 0, intervals: w.intervals, names: names,
      samples: w.samples};
    W0 = null;
    return out;
  };
  // Real time: take a sample, run enter, then sample every `every` ms for `ms` ms. Resolves with windowEnd().
  G.recordWindow = function (rootSel, enter, ms, every, track, opts) {
    G.windowStart(rootSel, track, opts);
    G.sample(0);
    var t0 = performance.now();
    if (typeof enter === "string") { if (enter) (0, eval)("(" + enter + ")")(); }
    else if (enter && enter.key) document.dispatchEvent(new KeyboardEvent("keydown", {key: enter.key, bubbles: true, cancelable: true}));
    return new Promise(function (res) {
      (function tick() {
        var dt = performance.now() - t0;
        G.sample(Math.min(1, dt / ms));
        if (dt >= ms) res(G.windowEnd()); else setTimeout(tick, every);
      })();
    });
  };

  // The boxes of each tracked selector's elements, in frame pixels, with their visibility.
  G.boxes = function (rootSel, sels, opts) {
    var R = new Reading(rootSel, opts), scope = R.frame;
    return {W: R.W, H: R.H, sets: sels.map(function (sel) {
      var els = Array.prototype.slice.call(scope.querySelectorAll(sel));
      return els.map(function (e) {
        var v = R.look(e), raw = R.shapeBox(e), vis = R.clip(e, raw, false);
        var shown = v.shown && !v.ghost && area(vis) >= 1;
        var b = R.local(raw);
        return {n: name(e), id: idOf(e), shown: shown, inview: area(inter(vis, R.fr)) >= 1, a: Math.round(v.a * 50) / 50,
          box: [Math.round(b.l * 10) / 10, Math.round(b.t * 10) / 10, Math.round(b.r * 10) / 10, Math.round(b.b * 10) / 10]};
      });
    })};
  };

  G.finishTransitions = function () {
    document.getAnimations().forEach(function (a) { if (a instanceof CSSTransition) a.finish(); });
  };
  G.finishFinite = function () {
    document.getAnimations().forEach(function (a) {
      try { if (isFinite(a.effect.getComputedTiming().endTime)) a.finish(); } catch (e) { /* infinite or detached */ }
    });
  };

  // Seek every Web Animation in the document (CSS animations and transitions included) to `t`
  // seconds, paused. All of a page's CSS animations start together at load, so one time fits all.
  G.seekAnimations = function (t) {
    document.getAnimations().forEach(function (a) { a.pause(); a.currentTime = t * 1000; });
  };

  window.__gauge = G;
})();
