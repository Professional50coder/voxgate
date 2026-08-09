# Frontend Technique Research — Awwwards 2026, filtered for an ops console

**Date:** 2026-08-07
**Method:** Pulled raw HTML from 13 currently-winning sites and grepped for library
fingerprints, rather than relying on write-ups. Sources: [awwwards.com](https://www.awwwards.com/)
and the [gradient-gradients collection](https://www.awwwards.com/jessica/collections/gradient-gradients/)
that prompted this pass.

---

## 1. What the winners actually ship

| Site | Award | Detected stack |
|---|---|---|
| noartmusic.com | SOTD | GSAP + ScrollTrigger + SplitText, Lenis, three.min.js, **OGL**, Swiper, Next.js |
| alethia.earth | SOTD | **OGL**, Lottie, Lenis |
| serotoninn.com | SOTD | Lottie (205 refs), Swiper, Lenis, **OGL** |
| showcase.noomoagency.com | SOTD | Nuxt, WebGL, **OGL** |
| soma.ca | Nominee | **OGL**, Locomotive, Lenis, GSAP |
| theeightclub.com | Nominee | Nuxt, Lottie |
| twofoldny.com | Nominee | Nuxt, Lottie |
| hollywoodexhibit2026.com | SOTD | Next.js, WebGL |
| members-play.lacoste.com | SOTD | WebGL, **Rive** |
| engine.xyz | gradient coll. | **Rive** (95 refs), Barba |
| roninamsterdam.com | gradient coll. | Rive, p5, Barba, radial-gradient |
| yourmajesty.co | gradient coll. | Rive |
| juliebonnemoy.com | gradient coll. | **Pure CSS**: radial-gradient ×14, mix-blend-mode ×14, backdrop-filter |

### Three findings that matter

1. **OGL — not Three.js — is the 2026 house shader library.** It appeared on 5 of 6 Site of
   the Day winners. Three.js appeared once, and on that same site OGL was *also* present.
   Unpacked size: OGL 423 KB vs Three.js 23.2 MB. Tree-shaken OGL for a fullscreen gradient
   quad is roughly 10–13 KB gzipped.
2. **Rive has quietly displaced Lottie for interactive vector work.** It dominates the
   gradient collection and shipped on the Lacoste SOTD. Lottie survives for linear,
   non-interactive playback.
3. **Award-tier gradients are mostly not CSS — they are fragment shaders.** The one pure-CSS
   entry in the collection (juliebonnemoy.com) uses layered radial gradients plus
   `mix-blend-mode`. **That is the technique VoxGate should steal**, because it is the only
   one that costs nothing.

---

## 2. Gradient techniques, with honest cost

### 2a. Aurora / blob field, CSS-only — ADOPT

The pure-CSS approximation of a mesh gradient, and what juliebonnemoy.com actually ships.
Several oversized `radial-gradient` blobs over a dark base, blurred, drifting slowly.

```css
.aurora {
  position: fixed; inset: -20%; z-index: 0; pointer-events: none;
  background:
    radial-gradient(42vmax 42vmax at 18% 22%, #4fa8ff 0%, transparent 62%),
    radial-gradient(38vmax 38vmax at 78% 30%, #a06bff 0%, transparent 60%),
    radial-gradient(46vmax 46vmax at 52% 84%, #ff6fd8 0%, transparent 64%),
    #060810;
  filter: blur(52px) saturate(1.25);
  opacity: .28;
  will-change: transform;
  animation: drift 44s ease-in-out infinite alternate;
}
@keyframes drift {
  from { transform: translate3d(-3%, -2%, 0) scale(1.04); }
  to   { transform: translate3d( 3%,  2%, 0) scale(1.12); }
}
@media (prefers-reduced-motion: reduce) { .aurora { animation: none; } }
```

**Cost: effectively free after first paint.** One composited layer. The `blur(52px)` is paid
once at rasterization because only `transform` animates.

**The critical rule:** animating `filter` or the gradient stops re-rasterizes every frame and
costs 8–14 ms/frame on integrated GPUs. Animate transform, nothing else.

### 2b. Animated conic gradient via `@property` — ADOPT, accents only

Before `@property`, custom properties were unanimatable strings. Now they interpolate. This
is the legitimate way to rotate a gradient ring without JS.

```css
@property --ang { syntax: '<angle>'; initial-value: 0deg; inherits: false; }

.orb-ring::before {
  content: ''; position: absolute; inset: -1px; border-radius: inherit;
  background: conic-gradient(from var(--ang), #4fa8ff, #a06bff, #ff6fd8, #4fa8ff);
  animation: spin 6s linear infinite;
  mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  mask-composite: exclude; padding: 1px;   /* ring, not disc */
}
@keyframes spin { to { --ang: 360deg; } }
```

**Cost:** conic-gradient repaints each frame. Cheap on a 128 px element, expensive
fullscreen. **Keep the painted area under ~200×200 px.** Baseline across all engines in 2026.

### 2c. Grain / dither overlay — ADOPT, but baked, never as a live filter

```css
/* Correct: bake feTurbulence to a data URI, tile it */
.grain::after {
  content: ''; position: fixed; inset: 0; pointer-events: none; z-index: 9999;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.8' numOctaves='3'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  opacity: .035;               /* above .05, 12px text starts to shimmer */
  mix-blend-mode: overlay;
}
```

**Never use `filter: url(#noise)` fullscreen** — it re-runs Perlin turbulence on every
repaint over the filtered area, which is brutal on low-end hardware. The baked data URI is a
single texture upload.

Refs: [css-tricks grainy gradients](https://css-tricks.com/grainy-gradients/),
[Codrops feTurbulence](https://tympanus.net/codrops/2019/02/19/svg-filter-effects-creating-texture-with-feturbulence/)

### 2d. Progressive blur ("Apple blur") — ADOPT for exactly one surface

Blur that ramps along an axis. A single masked blur shows a hard edge, so the 2026 idiom is
stacked `backdrop-filter` layers each masked by an offset gradient.

```css
.progressive-blur { position: sticky; top: 0; height: 88px; pointer-events: none; }
.progressive-blur > i { position: absolute; inset: 0; display: block; }
.progressive-blur > i:nth-child(1){ backdrop-filter: blur(2px);
  mask-image: linear-gradient(#000 0%, #000 25%, transparent 50%); }
.progressive-blur > i:nth-child(2){ backdrop-filter: blur(6px);
  mask-image: linear-gradient(transparent 25%, #000 50%, transparent 75%); }
.progressive-blur > i:nth-child(3){ backdrop-filter: blur(14px);
  mask-image: linear-gradient(transparent 50%, #000 75%, #000 100%); }
```

**Cost:** each layer is a separate backdrop readback plus GPU blur. Three layers over an
88 px strip is fine; three layers over a viewport is not.

There is an active CSSWG proposal (Jan 2026) to add `blur(from/to)` natively, so this hack
has a shelf life. Refs: [w3.org public-css-archive 2026Jan](https://lists.w3.org/Archives/Public/public-css-archive/2026Jan/0001.html),
[devslovecoffee](https://www.devslovecoffee.com/blog/making-apple-progressive-blur-on-web),
[joshwcomeau on backdrop-filter](https://www.joshwcomeau.com/css/backdrop-filter/)

### 2e. WebGL mesh/shader gradient (Stripe lineage) — REJECT for VoxGate

The real thing: a fullscreen quad running fBm — layered simplex noise octaves — warping
colour positions. Descends from Stripe's `whatamesh` MiniGL. Modern packaging is
`@paper-design/shaders-react`.

```glsl
float fbm(vec2 p){
  float v = 0., a = .5;
  for(int i=0;i<5;i++){ v += a*snoise(p); p *= 2.03; a *= .5; }
  return v;
}
void main(){
  vec2 uv = vUv;
  uv += 0.18 * vec2(fbm(uv*2.+u_time*.06), fbm(uv*2.-u_time*.05));
  vec3 c = mix(mix(C1,C2,smoothstep(0.,1.,uv.x)), C3, smoothstep(.2,.9,uv.y));
  gl_FragColor = vec4(c + (hash(gl_FragCoord.xy)-.5)*0.02, 1.);  // dithered
}
```

**Cost:** a continuously running fullscreen fragment shader — 15–35 % sustained GPU on
integrated graphics, permanently, because it never stops. Measurable battery drain.

Also `@paper-design/shaders-react` is on `0.0.x` and the maintainers explicitly warn that
breaking changes ship in patch releases.

**Verdict: no.** It violates the no-CDN constraint, adds a GPU context that contends with
the canvas orb and the `backdrop-filter` layers, and a compliance reviewer staring at a
screen for six hours does not need a breathing background. Refs:
[shaders.paper.design](https://shaders.paper.design/),
[github.com/paper-design/shaders](https://github.com/paper-design/shaders),
[whatamesh](https://whatamesh.vercel.app/)

### 2f. Text gradient — ADOPT, narrowly

```css
.brandmark {
  background: linear-gradient(92deg, #4fa8ff, #a06bff 48%, #ff6fd8);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
```

Free. **But it must never touch a KPI number** — see §6.

---

## 3. Tools and libraries

### Worth adopting

| Tool | Version | For | Verdict |
|---|---|---|---|
| **GSAP** | 3.15.0 | Timeline sequencing, SVG path drawing | **Yes, if self-hosted.** Now 100 % free including all former Club plugins (DrawSVG, MorphSVG, SplitText, ScrollTrigger) since Webflow's 2025-04-30 relicense. ~23–27 KB gzip core. DrawSVG is the clean answer to the animated pipeline graph. |
| **OGL** | 1.0.11 | Minimal WebGL | **Only if** the orb later must be a shader. 423 KB unpacked / ~12 KB gzip tree-shaken. Not needed now. |

GSAP licensing confirmed: acquired by Webflow Oct 2024, made fully free 2025-04-30,
commercial use included, no Club tier. Refs:
[webflow.com/blog/gsap-becomes-free](https://webflow.com/blog/gsap-becomes-free),
[gsap.com standard license](https://gsap.com/community/standard-license/)

Honest caveat: an SVG pipeline graph can be animated with `stroke-dashoffset` in ~15 lines
of CSS. GSAP earns its 25 KB only if orchestrated multi-element timelines with scrubbing are
genuinely needed.

### Overkill or wrong fit

| Tool | Version | Why not |
|---|---|---|
| **Lenis** | 1.3.26 | **Actively harmful here.** On 4 of 6 winners, and completely wrong for an ops console. Smooth-scroll hijacking breaks scroll-position restoration, Ctrl+F jump-to-match, screen-reader virtual cursors, and keyboard PageDown. Compliance reviewers scan long lists. **Never ship this.** |
| Three.js | 0.185.1 | 23 MB unpacked. OGL does the one useful thing at 2 % the size. |
| Motion (ex-Framer Motion) | 13.0.0 | ~30–32 KB gzip; only pays off in React with layout animations and `AnimatePresence`. Current needs are CSS-expressible. |
| `lottie-web` | 5.13.0 | **25.4 MB unpacked**, needs an After Effects → JSON pipeline, typically CDN-hosted JSON. Violates the no-external-assets rule. |
| `@rive-app/canvas` | 2.39.2 | Genuinely interesting — state-machine vector animation, and what top studios switched to. But 5.3 MB, needs the Rive editor, ships `.riv` binaries. Wrong for a console. |
| Barba.js | 2.10.3 | Page-transition router. The View Transitions API is Baseline now and does this natively. Obsolete. |
| Splitting.js | — | **Red flag:** npm `latest` returns a corrupted `version` field (`"npm run build && git add ."`) — a botched publish left unfixed. Unmaintained. GSAP SplitText is free now and better. |
| Shadergradient / whatamesh | — | Fullscreen GPU tax. See §2e. |
| Theatre.js | — | A visual animation *authoring* IDE. There are zero cinematic sequences here. |
| Matter.js | — | 2D rigid-body physics. Nothing in a compliance console needs gravity. |
| curtains.js | — | Superseded by OGL. Legacy. |
| p5.js | — | Creative-coding sketchpad; wrong abstraction for a production widget. |

---

## 4. Voice orb visualizer — concrete recommendation

**Canvas 2D. Not WebGL. Not a shader.**

At 128×128 CSS px on a DPR-2 display that is 65,536 pixels — Canvas 2D fills it in well under
1 ms. A WebGL context costs 100–200 KB of library, a GPU context competing with the
`backdrop-filter` layers, and context-loss handling, to render an area smaller than a favicon
grid. The award sites use shaders because they cover 2M+ pixels. This does not.

### Audio graph

```js
const ctx = new AudioContext();
const src = ctx.createMediaStreamSource(stream);
const analyser = ctx.createAnalyser();
analyser.fftSize = 512;                 // 256 bins — plenty for an orb
analyser.smoothingTimeConstant = 0.72;
src.connect(analyser);                  // NOT connected to destination — avoids feedback

const time = new Uint8Array(analyser.fftSize);
```

### Amplitude: RMS from time-domain, not peak from frequency

Peak values jitter and make the orb twitch. RMS reads as "voice energy".

```js
function rms() {
  analyser.getByteTimeDomainData(time);
  let s = 0;
  for (let i = 0; i < time.length; i++) { const v = (time[i] - 128) / 128; s += v * v; }
  return Math.sqrt(s / time.length);    // ~0..0.5 for speech
}
```

### Asymmetric envelope — the detail that makes it feel alive

Fast attack, slow release. This single thing separates "reactive" from "cheap".

```js
let env = 0;
const ATTACK = 0.45, RELEASE = 0.08;
function envelope(target) {
  const k = target > env ? ATTACK : RELEASE;
  env += (target - env) * k;
  return env;
}
```

### State machine

```js
const STATES = {
  idle:      { gain: 0.0, breathe: 0.030, spin: 0.10, lobes: 3 },
  listening: { gain: 2.6, breathe: 0.015, spin: 0.35, lobes: 4 },
  thinking:  { gain: 0.0, breathe: 0.055, spin: 1.20, lobes: 5 },
  speaking:  { gain: 2.0, breathe: 0.020, spin: 0.55, lobes: 4 },
};
// lerp between state objects over ~280ms so transitions never pop
```

`thinking` has `gain: 0` — it ignores the mic entirely and self-animates faster. That is the
honest signal that the system is no longer listening.

### Render: polar harmonic blobs, additive compositing

The Siri look is N overlapping translucent blobs whose radius is a sum of sine harmonics,
composited with `lighter`:

```js
function draw(t) {
  const S = current;                                   // lerped state
  const a = envelope(S.gain ? rms() * S.gain : 0);
  const R = size * 0.30 * (1 + a * 0.42 + Math.sin(t * 0.0016) * S.breathe);

  c.clearRect(0, 0, size, size);
  c.globalCompositeOperation = 'lighter';

  const COLORS = ['#4fa8ff', '#a06bff', '#ff6fd8'];
  for (let b = 0; b < 3; b++) {
    const ph = t * 0.0009 * S.spin + b * 2.094;        // 120° apart
    c.beginPath();
    for (let i = 0; i <= 90; i++) {
      const th = (i / 90) * Math.PI * 2;
      const w = 1
        + 0.100 * a * Math.sin(S.lobes * th + ph * 3)
        + 0.055 * a * Math.sin((S.lobes + 2) * th - ph * 2)
        + 0.020 * Math.sin(2 * th + ph);
      const r = R * w * (1 - b * 0.07);
      const x = cx + Math.cos(th + ph * 0.4) * r;
      const y = cy + Math.sin(th + ph * 0.4) * r;
      i ? c.lineTo(x, y) : c.moveTo(x, y);
    }
    c.closePath();
    const g = c.createRadialGradient(cx, cy, R * 0.1, cx, cy, R * 1.25);
    g.addColorStop(0, COLORS[b] + 'e6');
    g.addColorStop(1, COLORS[b] + '00');
    c.fillStyle = g; c.fill();
  }
  c.globalCompositeOperation = 'source-over';
}
```

Add the outer glow with a CSS `box-shadow` or `filter: blur()` on the canvas's **parent** —
cheaper than drawing it, and static so it never re-rasterizes.

### Non-negotiable loop hygiene

```js
// Stop the rAF entirely when idle, hidden, or reduced-motion.
// A 60fps loop rendering a static orb is pure battery waste.
if (document.hidden || (state === 'idle' && !hovered)) cancelAnimationFrame(raf);
document.addEventListener('visibilitychange', …);
matchMedia('(prefers-reduced-motion: reduce)')   // → render one static frame, no loop
```

Accessibility: the orb is decorative (`aria-hidden="true"`). Back it with a text status in an
`aria-live="polite"` region ("Listening…", "Thinking…"). The orb conveys nothing to a screen
reader.

Refs: [Codrops 3D audio visualizer](https://tympanus.net/codrops/2025/06/18/coding-a-3d-audio-visualizer-with-three-js-gsap-web-audio-api/),
[Siri-style pen](https://codepen.io/fgnass/pen/LWeKNq),
[noisehack Web Audio visualizer](https://noisehack.com/build-music-visualizer-web-audio-api/)

---

## 5. Micro-interaction and motion patterns

**Easing.** Templates use `ease` / `ease-in-out`. Award sites use asymmetric custom curves —
fast out, slow settle. Tokenize them:

```css
:root {
  --e-out:    cubic-bezier(0.16, 1, 0.3, 1);       /* expo-out: the workhorse */
  --e-inout:  cubic-bezier(0.65, 0, 0.35, 1);
  --e-spring: cubic-bezier(0.34, 1.56, 0.64, 1);   /* slight overshoot */
  --d-fast: 140ms; --d-base: 240ms; --d-slow: 420ms;
}
```

Rule of thumb: entrances use `--e-out`; exits are ~40 % faster and can use plain `ease-in`.
Never the same duration in both directions.

**Stagger.** 40–70 ms between siblings. Below 30 ms reads as simultaneous; above 90 ms reads
as slow.

```css
.tile { animation: rise var(--d-base) var(--e-out) both;
        animation-delay: calc(var(--i) * 55ms); }
```

**Springs.** Real spring physics (Motion, react-spring) is lovely and unnecessary here;
`--e-spring` approximates it at 1/30000th the cost.

**Scroll-driven animations.** `animation-timeline: scroll()` / `view()` — Chrome/Edge 115+,
Safari 18+ (landed Safari 26, Sept 2025), **Firefox still behind a flag as of Firefox 152,
June 2026**. ~84 % global, technically **not Baseline**. Always gate:

```css
@supports (animation-timeline: scroll()) { /* enhancement only */ }
```

The one legitimate VoxGate use: a scroll-progress indicator on a long audit log.

**View Transitions API.** Baseline in 2026; Level 2 `@view-transition` handles cross-document
navigation declaratively. Good for panel and route swaps, bad for data updates (§6).

Refs: [web-features scroll-driven-animations](https://web-platform-dx.github.io/web-features-explorer/features/scroll-driven-animations/),
[MDN animation-timeline](https://developer.mozilla.org/en-US/docs/Web/CSS/animation-timeline),
[Codrops Dash Creative](https://tympanus.net/codrops/2026/07/21/magnetic-commerce-building-the-dash-creative-website/)

---

## 6. Pure CSS that used to need JS — 2026 status

| Feature | Status | Replaces | VoxGate use |
|---|---|---|---|
| `@property` | **Baseline** | JS gradient-angle tweening | Animated Siri ring, KPI colour ramps |
| `color-mix()` | **Baseline** | Sass colour functions | Hover/active/disabled from one accent token |
| Relative colours `oklch(from …)` | **Baseline** | Preprocessor palettes | Derive a full ramp from `#4fa8ff` |
| Container queries | **Baseline** | JS ResizeObserver | KPI tiles reflowing by *their own* width — exactly right for a resizable console |
| `:has()` | **Baseline** | JS parent-state classes | Style a row that contains a failing check |
| CSS Nesting | **Baseline** | Sass | Makes 33 KB of CSS far more maintainable |
| View Transitions | **Baseline** (L2 for nav) | Barba.js | Route/panel transitions |
| `text-wrap: balance` / `pretty` | **Baseline** | JS widow-fixing | Card titles only (`balance` caps ~6 lines) |
| `backdrop-filter` | **Baseline** | — | Yes, but rationed (§7) |
| `mask-image` progressive blur | Works, but a hack | — | Header fade strip |
| `animation-timeline` | **~84 %, NOT Baseline** | GSAP ScrollTrigger | `@supports`-gated only |
| `field-sizing: content` | Chromium only | JS textarea autosize | Skip |

Two high-leverage wins for the existing 33 KB sheet:

```css
:root { --accent: #4fa8ff; }
.btn        { background: color-mix(in oklab, var(--accent) 14%, transparent); }
.btn:hover  { background: color-mix(in oklab, var(--accent) 26%, transparent); }
.btn:active { background: color-mix(in oklab, var(--accent) 34%, transparent); }
.accent-dim { color: oklch(from var(--accent) l c h / 0.62); }
```

```css
.kpi-tile { container-type: inline-size; }
@container (max-width: 220px) { .kpi-tile .delta-label { display: none; } }
@container (min-width: 380px) { .kpi-tile { grid-template-columns: 1fr auto; } }
```

Refs: [MDN color-mix](https://developer.mozilla.org/en-US/docs/Web/CSS/color_value/color-mix),
[modern-css.com what's new in CSS 2026](https://modern-css.com/whats-new-in-css-2026/),
[web.dev Baseline colour themes](https://web.dev/articles/baseline-in-action-color-theme)

---

## 7. The honest filter — what would actively hurt VoxGate

VoxGate is a dense console where a compliance reviewer makes consequential judgments, for
hours, and where the interface's job is to be **trustworthy and legible**, not memorable.
Award-site technique optimizes for a 45-second first impression. Those goals are close to
opposed.

### Do not ship

1. **Lenis / smooth scroll — the worst offender.** On 4 of 6 winners and catastrophically
   wrong here. Breaks scroll restoration, Ctrl+F scroll-to-match, keyboard PageDown, and
   screen-reader virtual cursors. Someone scanning a 900-row audit log does not want
   hijacked scrolling. **Never.**

2. **Fullscreen WebGL/shader gradient.** Permanent 15–35 % GPU on integrated graphics, all
   day, on a laptop. It contends with `backdrop-filter` and the orb canvas. And it moves
   *behind data* — peripheral vision keeps flagging motion where nothing changed.

3. **`backdrop-filter` on every panel — the biggest existing risk in the current CSS.** Each
   blurred surface is a separate backdrop readback plus GPU blur, recomputed on scroll. A
   console with 20 glass KPI tiles will drop frames on mid-range hardware. NN/g and Axess Lab
   both document the readability failure: text over a blurred, variable-luminance backdrop
   has *unpredictable* contrast — you cannot guarantee a WCAG ratio when the backdrop is
   whatever happened to scroll under it.

   **Ration it to 2–3 chrome surfaces** — top bar, side drawer, modal scrim. KPI tiles and
   table rows get a flat `#0b0e1a` with a 1 px `rgba(255,255,255,.06)` border. They will look
   better *and* be faster.

   ```css
   .chrome-surface { background: rgba(10,13,26,.94); }        /* opaque fallback */
   @supports (backdrop-filter: blur(12px)) {
     .chrome-surface { backdrop-filter: blur(14px) saturate(1.4);
                       background: rgba(10,13,26,.62); }
   }
   ```

   Refs: [NN/g glassmorphism](https://www.nngroup.com/articles/glassmorphism/),
   [Axess Lab](https://axesslab.com/glassmorphism-meets-accessibility-can-frosted-glass-be-inclusive/)

4. **Gradient text on any number, label, status, or table cell.** `background-clip: text`
   produces a *varying* contrast ratio across each glyph. Automated audits cannot measure it,
   and low-vision users lose the low-contrast end. **In a compliance tool, a misread digit is
   a real incident.** Gradient text is for the wordmark and nothing else.

   Contrast check on `#060810`: `#4fa8ff` ≈ 7.9:1, `#ff6fd8` ≈ 7.9:1, `#a06bff` ≈ 5.6:1 — all
   pass AA. But over a *glass* panel (effective background ≈ `#151a2e`) `#a06bff` drops toward
   ~4:1 and **fails**. Another argument for flat tiles.

5. **Grain over dense data.** Above ~0.04 opacity it visibly degrades 12–13 px type and
   hairline table rules — exactly what a reviewer stares at. Cap at 0.03 and mask it away
   from table regions.

6. **Magnetic cursors / cursor followers.** They deliberately displace the click target
   relative to the pointer — a direct Fitts's-law penalty. In a dense grid of small controls
   that causes misclicks. A misclicked "Approve" is unacceptable.

7. **Scroll-reveal / fade-in on rows and tiles.** Award sites use it to pace a narrative.
   Reviewers scan; content not painted until it scrolls into view is content they wait on.
   Animate on **initial mount only**, staggered, once — never on scroll.

8. **View Transitions on data mutation.** A cross-fade when a KPI refreshes reads as "this
   value changed" even when it did not. Reserve view transitions for *navigation*, where the
   animation's meaning is spatial rather than semantic.

9. **Lottie / Rive.** Both need external binary assets and an editor pipeline; both violate
   the no-CDN constraint. The pipeline graph is an SVG — animate it with `stroke-dashoffset`
   or GSAP DrawSVG.

### Do ship

- Static CSS aurora field (§2a), `opacity ≤ 0.30`, transform-only drift, killed under
  `prefers-reduced-motion`.
- `@property` conic ring on the **orb only** — small painted area, and the one element where
  motion is semantically correct because it indicates live state.
- Canvas 2D orb (§4), rAF stopped when idle or hidden.
- Progressive-blur strip under the sticky header (§2d) — solves the real problem of rows
  colliding with the header.
- Tokenized easing plus a one-time mount stagger.
- `color-mix()`, relative colours, container queries, `:has()`, nesting.
- Baked data-URI grain at 0.03, masked off tables.
- A genuine `prefers-reduced-motion` path, not a stub. Compliance software ships into
  regulated organizations with hard WCAG 2.2 AA procurement requirements.

### The one-line version

**Steal the award sites' craft — easing curves, stagger timing, layered depth, restraint in
the palette — and reject their spectacle.** The signal worth acting on is not the shaders:
it is that the winning gradient in that collection was pure CSS, and that OGL beat Three.js
because studios doing this professionally optimize ruthlessly for weight. Apply the same
ruthlessness and VoxGate ends up with maybe 4 of these 20 techniques — which is the correct
number for a tool people work in rather than look at.
