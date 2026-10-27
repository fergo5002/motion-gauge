# motion-gauge

motion-gauge measures motion on rendered web pages. It opens a page in Chromium through Playwright, walks it beat by beat, and counts what a viewer has to take in: how many things move at once, how much text is on screen, how crowded each part of the frame is. It also checks a storyboard's rules against the page, such as "the token arrives before its label appears" or "nothing leaves the frame".

Before it measures anything it checks the browser itself. A background tab, a throttled frame clock or a layout read that comes back empty all look like a broken animation, and none of them is. If the measurement path is unhealthy, the run says it measured nothing rather than reporting numbers. That check is also a standalone file you can paste into DevTools.

The numbers are counts. They don't judge whether an animation is good, and a count only means something once you've compared it against pages people have already judged (see [Turning counts into thresholds](#turning-counts-into-thresholds)).

## The tools

| Command | What it does | Exit code |
|---|---|---|
| `motion-gauge instrument [PAGE]` | Checks the measurement path: page visible, `requestAnimationFrame` firing within 10% of the display rate with no more than 10% long frames, style and layout reads passing a control. Records headed or headless, browser version and renderer. `busy` and `predicates` run the same gate before and after every run | 0 healthy, 1 degraded |
| `motion-gauge busy PAGE --spec SPEC` | Per settled beat: visible text runs and words, painted elements, a 6 by 8 coverage grid from element boxes and the same grid from pixels, elements that move in the beat's motion window, endless animations | 0 measured, 2 measured nothing or a bad spec, 3 the run itself failed |
| `motion-gauge predicates PAGE --spec SPEC` | Checks the spec's predicates: `appearsBy`, `before`, `staysInFrame`, `noOverlap`, `maxMovers`, `density` | 0 all hold, 1 any fails, 2 measured nothing or a bad spec, 3 the run itself failed |
| `motion-gauge compare CALM.json BUSY.json` | Two `busy` reports side by side, the one that should be calmer first: medians, how often its beats are lower, and a provisional band where a metric separates them | 0, or 2 if a report measured nothing |
| `motion-gauge snippet` | Prints the paste-in browser instrument check (`--path` prints where the file is) | 0 |
| `motion-gauge examples DIR` | Copies the example pages and specs into `DIR` | 0 |

Every tool also runs as `python -m motion_gauge.<tool>`, and `motion-gauge TOOL --help` lists its options. Exit 3 means the run crashed before it could check anything (a page that won't load, a frame selector that matches nothing, a script in the spec that throws), so a CI job can tell that apart from a rule that failed.

## Install

Python 3.11 or later. motion-gauge isn't on PyPI; install the wheel from the [latest release](https://github.com/fergo5002/motion-gauge/releases/latest), then fetch Playwright's Chromium:

```sh
pip install https://github.com/fergo5002/motion-gauge/releases/download/v0.1.0/motion_gauge-0.1.0-py3-none-any.whl
python -m playwright install chromium
```

On Linux, `python -m playwright install --with-deps chromium` also installs the system libraries Chromium needs.

From a checkout:

```sh
git clone https://github.com/fergo5002/motion-gauge
cd motion-gauge
pip install -e ".[test]"
python -m playwright install chromium
```

## Try it on the examples

The package ships two pages that tell the same small story with the same element ids: an order card arrives, a token rides across, a second card and its label appear. `calm.html` moves one thing at a time. `busy.html` does everything at once: the title marches off the edge, five sparks drift throughout, a square spins for ever, a solid slab fills a corner, and the second card lands on top of the first while its label shows up early. `storyboard.json` holds the rules both pages are checked against.

```sh
motion-gauge examples ex
motion-gauge busy ex/calm.html --spec ex/storyboard.json --out calm.json
motion-gauge busy ex/busy.html --spec ex/storyboard.json --out busy.json
motion-gauge compare calm.json busy.json
motion-gauge predicates ex/busy.html --spec ex/storyboard.json
```

`busy` on the busy page, headless on a Mac:

```text
busy: ex/busy.html (seek, headless)
  gate: USABLE WITH CAVEATS; chromium 156.0.8078.4, rAF 59.88 Hz against 60.0 Hz, ANGLE (... SwiftShader driver)
  beat             runs  words   lit  dim   cov  >.6   ink  mov  peak  loops
  order arrives       2      4    10    0  1.00    4  1.00    8     8      1
  token rides         2      4    10    0  1.00    4  1.00    7     7      1
  shipped             4      9    12    0  1.00    4  1.00    8     8      1
```

The calm page reads 1, 1 and 1 for its movers peak and has no cell over 0.6. The caveat on the gate is the software renderer, explained [below](#headless-and-headed).

`predicates` on the busy page fails six of its ten rules and exits 1:

```text
  order arrives: an order has come in
    ok   appearsBy(#card-a, 0.5): #card-a appears at 0.21, by 0.5
    FAIL staysInFrame(#title): h1#title goes 180 px past the right edge of the frame at 1.00
    FAIL maxMovers(2): 8 elements move at once at most (limit 2): [...]
    FAIL density(max_cell=0.6): the densest cell (row 1, column 7) is 1.00 covered (limit 0.6, by coverage)
  ...
  shipped: the order has shipped and been checked
    FAIL before(#card-b, #lbl): #card-b arrives at 0.83; #lbl appears at 0.04
    FAIL noOverlap(#card-a, #card-b): div#card-a.card and div#card-b.card overlap at IoU 0.333 (limit 0.2)
    ok   appearsBy(#lbl, 1): #lbl appears at 0.04, by 1
  6 of 10 predicates failed
```

The calm page passes all ten and exits 0. `steps.html` and `steps.json` show the other kind of page, one that steps like a slide deck.

## The paste-in instrument check

`src/motion_gauge/instrument_check.js` is one self-contained expression. Paste it into the DevTools console, or pass it to an automation tool's "evaluate JavaScript" call (Playwright's `page.evaluate`, a browser agent's JS tool), before you diagnose a rendering, layout, animation, freeze or timeout problem. `motion-gauge snippet` prints it.

It returns one of three verdicts:

- `CLEAR`: the instrument is sound, so findings are about the page.
- `USABLE WITH CAVEATS`: read the warnings first (software renderer, quirks mode, fonts still loading, a tiny window).
- `INSTRUMENT DEGRADED`: fix the instrument before you conclude anything. Blockers are a hidden tab, `requestAnimationFrame` not firing, a frame rate more than 10% off the display, more than 10% long frames, `getComputedStyle` failing a control reading, or layout reads (`innerText`, `getBoundingClientRect`) returning nothing for a visible control element.

Set `window.__instrumentCheck = {cadence: "warn"}` when your measurement seeks a timeline to each moment rather than waiting for frames: a slow or uneven frame clock then becomes a warning, while a clock that doesn't fire at all still blocks. `busy` and `predicates` do this for `seek` specs and keep cadence blocking for `steps` specs.

It can't hang. `requestAnimationFrame` is raced against `setTimeout`, which still fires in a hidden tab, and the whole check finishes in a few seconds. It doesn't know your display's refresh rate unless you tell it (`window.__instrumentCheck = {displayHz: 120}` before pasting), so by default it assumes the nearest standard rate to the one it measures and says so.

The Python gate runs this same file, so a paste-in check and a gauge run judge the measurement path by the same rules.

## The spec

One JSON object. `busy` and `predicates` read the same format; `busy` ignores the predicates.

```json
{
  "spec": "motion-gauge/predicates/1",
  "kind": "seek",
  "frame": "#frame",
  "timeline": "animations",
  "viewport": [1920, 1080],
  "beats": [
    {"label": "token rides", "at": 1.6, "window": [1.0, 1.6],
     "learns": "the order travels on",
     "predicates": ["appearsBy(#token, 0.1)", "staysInFrame(#token)", "maxMovers(1)"]}
  ]
}
```

- `kind`: `seek` or `steps`.
- `frame`: a CSS selector for the element that is the frame. Selectors in predicates are looked up inside it, and the coverage grid is laid over it.
- `viewport`: the browser window, `[width, height]`. Defaults to 1920 by 1080.
- `ready`: optional JavaScript predicate to wait for after load. The default waits for `readyState` and fonts.
- `learns` and `motion`: optional notes that travel into the report.

**seek** pages have a timeline the gauge can set to any time, so sampling doesn't depend on the frame rate. `timeline` is either `"animations"`, which pauses every Web Animation in the document (CSS animations and transitions included) and sets them all to the same time, or a JavaScript expression for an object with a `seek(seconds)` method, such as a GSAP timeline (`"window.tl"`). Each beat settles at `at` seconds and its motion window is `window`, `[start, end]` in seconds.

**steps** pages move in real time when something happens. Each beat may have `go` (JavaScript run first, to reach the step before) and `enter` (a JavaScript expression such as `go(2)`, a function such as `() => go(2)`, or `{"key": "ArrowRight"}` dispatched on the document) to start its window, which lasts `window_ms` (default 1500) and is sampled every `every_ms` (default 50). A beat with no `enter` has no motion window. Optional `setup` (JavaScript) and `setup_wait_ms` run once after load, to stop an autoplay, say. Run these headed (see below).

## The predicates

Times are fractions of the beat's motion window: 0 is where it starts, 1 the settle. A selector that matches nothing fails its predicate, because a check that can't see its subject hasn't passed. For the same reason `appearsBy`, `before` and `maxMovers` are refused on a beat with no motion window.

| Predicate | Holds when |
|---|---|
| `appearsBy(sel, t)` | some element of `sel` is visible (shown, not ghosted, inside the frame) at or before `t` |
| `before(a, b)` | every element of `a` visible at the settle has stopped changing (box within 0.75 px, opacity within 0.02) by the time the first element of `b` appears |
| `staysInFrame(sel[, tol=1])` | no visible element of `sel` is more than `tol` px outside the frame at any sample or at the settle |
| `noOverlap(a, b[, iou=0.2])` | at the settle, no visible pair from `a` and `b` overlaps past that intersection over union |
| `maxMovers(n[, of=peak])` | at most `n` elements change in any one sampling interval (`of=window`: in the whole window) |
| `density([max_cell=0.6][, using=coverage])` | no cell of the 6 by 8 grid is over `max_cell` at the settle (`using=ink` reads pixels instead of boxes) |

## What the numbers mean

- **Visible**: nothing on the way up has `display: none`, the element's own `visibility` is `visible`, opacity times `filter: opacity()` multiplied up to the root is at least 0.05, and clipping ancestors leave some of it showing.
- **Ghosted**: inside an element with the class `ghost`, or fainter than 0.2. Ghosts are counted apart and their words aren't counted. **Dim** is inside an element with the class `dim`.
- **Lit**: a visible, unghosted element that paints something itself: its own text, an SVG shape, a small inline SVG (an icon, counted once), an image, video or canvas, or a visible background or border.
- **Coverage**: a 6 by 8 grid over the frame, each cell's share covered by text line boxes and painted boxes. **Ink** is the same grid read from a screenshot: the share of pixels at least 40 levels away from the frame's commonest colour in some channel.
- **Movers**: elements whose own animated properties (display, opacity, transforms, size, position, colours, clip path, filter, stroke dash offset and a few more) change between samples. A property children inherit counts only where it differs from the parent's, and an element that starts rendering or enters the DOM with its parent is the parent's change, so a card that fades in is one mover however many children it has. `window` counts every element that moved; `peak` is the most in one sampling interval.
- **Loops**: endless animations on elements in the frame.

## Headless and headed

Headless Chromium draws through a software rasteriser (SwiftShader), so the gate on a headless run reports `USABLE WITH CAVEATS`. Seeked pages are sampled by setting the timeline, not by waiting for frames, so their counts don't depend on cadence, and the gate only warns about a slow frame clock on a `seek` run. With the frame clock throttled to about 2 Hz, the tests get the same mover counts on `calm.html` as with a healthy one. On `calm.html`, a headless and a headed run on a Mac gave the same counts on every beat.

Anything that runs in real time, a `steps` page above all, depends on the frame clock, so on a `steps` run the gate fails when the cadence is off. Run these with `--headed`, in a visible window. On GitHub's macOS runners, headless Chromium's frame clock ran at 30 Hz against 60, and the gate refused real-time runs there. Headless frame drops describe the software rasteriser, not your page. On macOS and Linux the gate can't read the display's refresh rate, so headed runs assume the nearest standard rate to the measured one and say so; pass `--display-hz` to set it. On Windows it asks the system for the rate first.

## Turning counts into thresholds

A count becomes a threshold only after it separates pages people have already judged. Measure a set of pages that were judged calm and a set judged busy with the same spec, run `compare` with the calmer report first, and look for metrics that hit (the calmer page's beat is lower in at least 60% of beat pairs) with a band below the busier median. Then check the band against pages that weren't used to set it. Two example pages are a smoke test, not a calibration, and the bands `compare` prints for them mean nothing beyond those two pages.

## What it does not see

- Pseudo-elements (`::before`, `::after`), canvas and WebGL content, and CSS `content` animations: their motion is invisible to the mover count and their area to coverage. Ink still sees their pixels.
- Motion that only the compositor knows about is seen through computed styles, so a mover is a style change, not a measured pixel displacement.
- Mover peaks on `steps` pages depend on the real-time sampling interval and aren't comparable with seeked pages.
- Box coverage saturates on layouts built from filled cards. Ink is the finer reading there.
- Firefox, WebKit, phones and reduced-motion mode aren't measured.
- Nothing here judges feel, clarity or appeal.

## Tests

```sh
python -m pytest -q
```

The tests run headless Chromium against the example pages. Every expected count is worked out by hand from the pages' CSS. Faults are planted in the measurement path (a hidden page with `requestAnimationFrame` stubbed out, a frame clock throttled to about 2 Hz, empty layout reads, a stale `getComputedStyle`) and each must turn the verdict to `INSTRUMENT DEGRADED`. Tests that need a healthy real-time frame clock first take a control reading on this machine and skip, saying why, when it fails. CI runs the suite on Linux and macOS with Python 3.11 and 3.13, and on Windows with Python 3.11.

## Licence

MIT. See [LICENSE](LICENSE).
