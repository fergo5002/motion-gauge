/* instrument-check.js: prove the instrument before you accuse the page.
 *
 * Paste the whole file into the DevTools console, or into an automation
 * tool's "evaluate JavaScript" call, BEFORE you diagnose a rendering, layout,
 * animation, freeze or timeout problem. It reports on the measurement path
 * (the tab, the frame clock, the style and layout reads), not on the page.
 *
 * Why: a backgrounded tab does not run requestAnimationFrame, so any probe
 * that waits for a frame hangs and every screenshot times out. Layout reads
 * such as innerText can come back empty, and getComputedStyle can disagree
 * with the pixels. All of these look like a broken page and none of them is.
 *
 * It cannot hang: requestAnimationFrame is raced against setTimeout, which
 * still fires in a hidden tab (throttled to about once a second), and the
 * whole check is capped at a few seconds.
 *
 * Read the verdict first:
 *   CLEAR                 the instrument is sound; findings are about the page
 *   USABLE WITH CAVEATS   read the warnings before concluding anything
 *   INSTRUMENT DEGRADED   stop; fix the instrument; nothing measured is evidence
 *
 * Options (all optional) go in window.__instrumentCheck before you run it:
 *   displayHz   the display's refresh rate, if you know it; otherwise the
 *               nearest standard rate to the measured one is assumed
 *   sampleMs    how long to watch the frame clock (default 1000)
 *   stamps      true to include the raw frame timestamps in the result
 *   cadence     "block" (default) or "warn". Real-time work needs a healthy
 *               frame clock; work that seeks a timeline to each moment only
 *               needs one that fires, so a slow or uneven clock can be a
 *               warning there. A clock that does not fire always blocks.
 *   intervals   frame intervals in ms to judge instead of measuring (tests)
 *
 * motion-gauge runs this same file as its instrument gate, so a paste-in
 * check and a gauge run judge the measurement path by the same rules.
 */
(async (opts) => {
  'use strict';
  opts = opts || {};
  const RAF_RACE_MS = 1200;
  const MIN_FRAMES = 20;
  const RATE_TOLERANCE = 0.10;
  const LONG_FACTOR = 1.5;
  const LONG_SHARE = 0.10;
  const STANDARD_HZ = [60, 75, 90, 100, 120, 144, 165, 240];
  const sampleMs = opts.sampleMs || 1000;
  const out = { blockers: [], warnings: [] };
  const cadenceIssues = opts.cadence === 'warn' ? out.warnings : out.blockers;

  // --- the tab. A hidden tab does not run requestAnimationFrame. ----------
  out.visibilityState = document.visibilityState;
  out.hasFocus = document.hasFocus();
  if (document.visibilityState !== 'visible') {
    out.blockers.push('The tab is ' + document.visibilityState + '. requestAnimationFrame ' +
      'does not run here, so frame-based probes hang and screenshots time out. That looks ' +
      'exactly like a frozen page and is not one. Bring the tab to the front and measure again.');
  }

  // --- the frame clock. Race rAF against setTimeout; never await it bare. --
  const stamps = [];
  if (Array.isArray(opts.intervals)) {
    out.rafFires = true;
    let t = 0;
    stamps.push(t);
    opts.intervals.forEach(dt => { t += dt; stamps.push(t); });
  } else {
    out.rafFires = await new Promise(res => {
      let done = false;
      setTimeout(() => { if (!done) { done = true; res(false); } }, RAF_RACE_MS);
      requestAnimationFrame(ts => { if (!done) { done = true; stamps.push(ts); res(true); } });
    });
    if (out.rafFires) {
      await new Promise(res => {
        let cut = false;
        const end = performance.now() + sampleMs;
        setTimeout(() => { cut = true; res(); }, sampleMs + 1000);
        (function loop() {
          requestAnimationFrame(ts => {
            if (cut) return;
            stamps.push(ts);
            if (performance.now() < end) loop(); else { cut = true; res(); }
          });
        })();
      });
    }
  }
  if (!out.rafFires) {
    out.blockers.push('requestAnimationFrame did not fire within ' + RAF_RACE_MS + ' ms (setTimeout did). ' +
      'Every frame-based reading would hang or lie. This is a fact about the environment, not the page.');
  }

  // Cadence: the median frame rate against the display, and the share of long frames.
  const intervals = [];
  for (let i = 1; i < stamps.length; i++) intervals.push(stamps[i] - stamps[i - 1]);
  const cad = { frames: intervals.length, rafHz: null, displayHz: null, displaySource: null, longFrameShare: null };
  if (out.rafFires) {
    if (intervals.length < MIN_FRAMES) {
      cadenceIssues.push('Only ' + intervals.length + ' frame intervals in the sample (at least ' + MIN_FRAMES +
        ' needed): requestAnimationFrame is stalling or throttled.');
    } else {
      const sorted = intervals.slice().sort((a, b) => a - b);
      const mid = sorted.length >> 1;
      const med = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
      const hz = med > 0 ? 1000 / med : 0;
      let disp = opts.displayHz > 0 ? opts.displayHz : null;
      if (disp) {
        cad.displaySource = 'given';
      } else {
        disp = STANDARD_HZ.reduce((best, h) => Math.abs(h - hz) < Math.abs(best - hz) ? h : best, STANDARD_HZ[0]);
        cad.displaySource = 'assumed: the nearest standard rate to the measured one';
      }
      const budget = 1000 / disp;
      const long = intervals.filter(x => x > LONG_FACTOR * budget).length / intervals.length;
      cad.rafHz = Math.round(hz * 100) / 100;
      cad.displayHz = disp;
      cad.longFrameShare = Math.round(long * 1000) / 1000;
      if (Math.abs(hz - disp) / disp > RATE_TOLERANCE) {
        cadenceIssues.push('requestAnimationFrame runs at ' + hz.toFixed(1) + ' Hz against a ' + disp +
          ' Hz display (more than ' + Math.round(RATE_TOLERANCE * 100) + '% off): the frame clock is throttled or overloaded.');
      }
      if (long > LONG_SHARE) {
        cadenceIssues.push(Math.round(long * 100) + '% of frames are longer than ' + LONG_FACTOR +
          ' display frames (more than ' + Math.round(LONG_SHARE * 100) + '%): timings read now describe the hitches.');
      }
    }
  }
  out.cadence = cad;
  if (opts.stamps) out.stamps = stamps;

  // --- style and layout reads: take a control reading on a known element. -
  try {
    const probe = document.createElement('div');
    probe.textContent = 'instrument control';
    // Every property set !important, so the page's own !important rules cannot win the cascade.
    [['position', 'fixed'], ['left', '0'], ['top', '0'], ['color', 'rgb(1, 2, 3)'], ['width', '37px'],
     ['display', 'block'], ['visibility', 'visible'], ['opacity', '0.01'], ['pointer-events', 'none']]
      .forEach(([k, v]) => probe.style.setProperty(k, v, 'important'));
    (document.body || document.documentElement).appendChild(probe);
    const cs = getComputedStyle(probe);
    const rect = probe.getBoundingClientRect();
    // Copy the reads out before the probe goes: a computed style is live and empties on removal.
    out.styleControl = { color: cs.color, width: cs.width };
    out.layoutControl = { innerText: probe.innerText, height: Math.round(rect.height * 10) / 10 };
    probe.remove();
    if (!(out.styleControl.color === 'rgb(1, 2, 3)' && out.styleControl.width === '37px')) {
      out.blockers.push('getComputedStyle failed its control: set rgb(1, 2, 3) and 37px, read back ' +
        out.styleControl.color + ' and ' + out.styleControl.width + '. Do not trust style reads here; check the pixels instead.');
    }
    if (out.layoutControl.innerText !== 'instrument control' || !(rect.height > 0)) {
      out.blockers.push('Layout reads failed their control: a visible element read back innerText "' +
        out.layoutControl.innerText + '" and height ' + out.layoutControl.height + '. innerText, ' +
        'getBoundingClientRect and offsetHeight will return confident wrong answers here. ' +
        'Read textContent instead, or bring the tab to the front.');
    }
  } catch (e) {
    out.blockers.push('The style and layout control could not run: ' + e.message);
  }

  // --- which document, which renderer --------------------------------------
  out.url = location.href;
  out.ua = navigator.userAgent;
  out.readyState = document.readyState;
  out.compatMode = document.compatMode;
  out.charset = document.characterSet;
  out.viewport = innerWidth + 'x' + innerHeight;
  out.dpr = devicePixelRatio;
  try {
    const gl = document.createElement('canvas').getContext('webgl');
    const ext = gl && gl.getExtension('WEBGL_debug_renderer_info');
    out.renderer = gl ? (ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER)) : 'no WebGL';
  } catch (e) { out.renderer = 'unknown: ' + e.message; }
  if (/swiftshader|llvmpipe|software/i.test(out.renderer || '')) {
    out.warnings.push('The renderer is software (' + out.renderer + '). Real-time cadence and ' +
      'frame drops read here describe the software rasteriser, not a GPU.');
  }
  if (document.compatMode === 'BackCompat') {
    out.warnings.push('Quirks mode (no doctype). The box model and line height differ from a ' +
      'standards-mode page, so you may be measuring a different document from the one that ships.');
  }
  if (document.characterSet.toLowerCase() !== 'utf-8') {
    out.warnings.push('The charset is ' + document.characterSet + ', not UTF-8.');
  }
  if (document.readyState !== 'complete') {
    out.warnings.push('readyState is "' + document.readyState + '": layout is not final.');
  }
  try {
    out.fontsStatus = document.fonts.status;
    if (document.fonts.status !== 'loaded') {
      out.warnings.push('document.fonts.status is "' + document.fonts.status + '": text measurements ' +
        'are provisional until document.fonts.ready resolves.');
    }
    const failed = [...document.fonts].filter(f => f.status === 'error');
    if (failed.length) {
      out.warnings.push(failed.length + ' font face(s) failed to load (' + failed.map(f => f.family).join(', ') +
        '); text is in a fallback face.');
    }
  } catch (e) { out.fontsStatus = 'unavailable: ' + e.message; }
  if (innerWidth < 300 || innerHeight < 300) {
    out.warnings.push('The window is ' + innerWidth + 'x' + innerHeight + ': too small for layout ' +
      'conclusions about the design.');
  }

  out.verdict = out.blockers.length ? 'INSTRUMENT DEGRADED'
    : out.warnings.length ? 'USABLE WITH CAVEATS' : 'CLEAR';
  out.meaning = {
    'CLEAR': 'the instrument is sound; findings from here are about the page',
    'USABLE WITH CAVEATS': 'read the warnings before concluding anything',
    'INSTRUMENT DEGRADED': 'fix the instrument first; nothing measured through it is evidence',
  }[out.verdict];
  return out;
})(window.__instrumentCheck);
