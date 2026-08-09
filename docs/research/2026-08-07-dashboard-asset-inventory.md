# Dashboard Asset Inventory

**Date:** 2026-08-07
**Purpose:** The dashboard build was stopped mid-write on 2026-08-06. Two files survived —
a complete CSS design system and an HTML shell — and `dashboard.js` was never written. This
note is a full inventory of what exists, so the intended feature surface can be recovered
from the CSS rather than re-invented.

**The key insight: the CSS *is* the spec.** Roughly 130 classes are styled; only ~50 appear
in the HTML. Every styled-but-unrendered class describes a component the missing JS was
supposed to build.

Files:
- `src/voxgate/service/static/dashboard.css` — 601 lines, 32,994 B
- `src/voxgate/service/static/index.html` — 145 lines
- `src/voxgate/service/static/dashboard.js` — **does not exist**, though `index.html:143`
  loads it.

---

## 1. Design tokens

All in `:root` (dashboard.css:7–65). `color-scheme: dark` is set on `:root`. There are **no
theme overrides and no scoped redefinitions** anywhere else in the file — this is a
single-theme dark system.

### Surfaces

| Token | Value | Used? |
|---|---|---|
| `--bg` | `#060810` | yes |
| `--bg-1` | `#0a0d18` | **never referenced** |
| `--glass` | `rgba(255,255,255,0.05)` | yes |
| `--glass-strong` | `rgba(255,255,255,0.08)` | **never referenced** |
| `--glass-border` | `rgba(255,255,255,0.10)` | yes |
| `--glass-border-soft` | `rgba(255,255,255,0.06)` | yes |
| `--surface-2` | `rgba(255,255,255,0.035)` | yes |

### Text

`--text: #eef1fa` · `--text-dim: #a6acc2` · `--text-faint: #6b7290`

### Siri gradient accent

- `--siri-1: #4fa8ff` · `--siri-2: #a06bff` · `--siri-3: #ff6fd8` · `--brand: #a06bff`
  (`--brand` never referenced)
- `--siri-gradient: linear-gradient(120deg, var(--siri-1) 0%, var(--siri-2) 50%, var(--siri-3) 100%)`
- `--siri-gradient-soft: linear-gradient(120deg, rgba(79,168,255,.35) 0%, rgba(160,107,255,.35) 50%, rgba(255,111,216,.35) 100%)`
  — never referenced

### Status semantics — names map 1:1 to backend `status` strings

`--status-awaiting_interview: #f5b95b` · `--status-processing: #4fa8ff` ·
`--status-awaiting_review: #b184ff` · `--status-approved: #38e0a8` ·
`--status-rejected: #ff6b7a` · `--status-needs_attention: #ff8a5c`

### Risk bands

`--risk-low: #38e0a8` · `--risk-medium: #f5b95b` · `--risk-high: #ff6b7a`

### Typography

- `--font-sans: -apple-system, "Segoe UI Variable Text", "Segoe UI", "Inter", system-ui, "Helvetica Neue", Arial, sans-serif`
- `--font-mono: ui-monospace, "Cascadia Code", "Consolas", "SFMono-Regular", Menlo, monospace`
- Body baseline: `15px / 1.5`

### Spacing, radii, elevation, motion

- Spacing: `--sp-1:4px --sp-2:8px --sp-3:12px --sp-4:16px --sp-5:20px --sp-6:24px --sp-7:32px --sp-8:40px` (`--sp-7` unused)
- Radii: `--r-sm:8px --r-md:14px --r-lg:20px --r-xl:28px --r-full:999px` (`--r-xl` unused)
- `--shadow-1: 0 1px 2px rgba(0,0,0,.35), 0 8px 24px rgba(0,0,0,.35)`
- `--shadow-2: 0 16px 48px rgba(0,0,0,.5)`
- `--glow-brand: 0 0 0 1px rgba(160,107,255,.25), 0 0 32px rgba(160,107,255,.25)`
- `--dur-fast: 150ms` · `--dur-med: 260ms` · `--dur-slow: 420ms`
- `--ease-out: cubic-bezier(.16,1,.3,1)` · `--ease-in-out: cubic-bezier(.65,0,.35,1)` (unused)

**Blur is not tokenized** — it is hardcoded per component: `.glass` `blur(20px) saturate(140%)`,
`.topbar` `blur(24px) saturate(160%)`, `.drawer-panel` `blur(28px) saturate(160%)`, `.toast`
`blur(16px)`. See the frontend research note §7.3 on why this needs rationing.

---

## 2. Component classes, and the states JS must toggle

**Shell primitives:** `.bg-ambient` (+ `::after` vignette), `.app-shell`, `.visually-hidden`,
`.hidden` (`display:none !important` — the generic show/hide hook), `.glass`, `.skeleton`,
`.layout`, `.panel`, `.panel-head`, `.board-panel` / `.analytics-panel` / `.monitor-panel`
(grid-areas named `board` / `analytics` / `monitor`).

**Topbar:** `.topbar`, `.brand`, `.brand-mark`, `.brand-tag`, `.header-actions`

**KPI:** `.kpi-row`, `.kpi-tile`, `.kpi-value`, `.kpi-label`
→ states: **`.kpi-tile.kpi-live`** (purple glow border), **`.kpi-value.updated`** (fires
`kpi-pulse`, 420 ms — JS adds then removes).

**Buttons:** `.btn`, `.btn-primary`, `.btn-ghost`, `.btn-danger`, `.btn-success`, `.btn-sm`,
`.btn-icon`, `.select-input`, `select.field-input`. `:disabled` styled.

**Connection badge:** `.conn-badge` > `.dot`
→ states: **`.live`**, **`.connecting`**, **`.down`** (bare `.conn-badge` = idle grey).
Note `.conn-label` exists in the HTML but **has no CSS rule**.

**Attention banner:** `.attention-banner`, `.attention-dot`
→ state: **`.show`** (animates `max-height 0 → 64px` plus padding).

**Case board:** `.case-list`, `.case-row`, `.case-id`, `.case-main`, `.case-pack`,
`.case-sub`, `.case-score`, and inside score `.band-low` / `.band-medium` / `.band-high`
→ states: **`.case-row.selected`** (purple ring), **`.case-row.flash`** (adds `row-flash`
900 ms on live update). `.case-row` animates `row-in` on insertion automatically.

**Status chips:** `.chip`, `.chip-sm`, plus one of `.status-awaiting_interview`,
`.status-processing`, `.status-awaiting_review`, `.status-approved`, `.status-rejected`,
`.status-needs_attention`
→ state: **`.chip.status-changed`** (fires `chip-morph`, 420 ms, add-then-remove).

**Empty states:** `.empty-state`, `.empty-icon`, `.empty-actions` (+ nested `h3`, `p`).

**Charts — all pure CSS, no library:**
- `.analytics-grid`, `.chart-card`, `.chart-title`, `.chart-empty`
- Risk distribution: `.dist-bar`, `.dist-seg` + `.low`/`.medium`/`.high`, `.dist-legend`
  (`span`, `i`, `.low i` / `.medium i` / `.high i`) — JS animates inline `width`
- Funnel: `.funnel`, `.funnel-row`, `.funnel-label`, `.funnel-track`, `.funnel-fill`
  (starts `width:0`), `.funnel-count`
- Top features: `.hbar-list`, `.hbar-row`, `.hbar-feat`, `.hbar-track`, `.hbar-axis`,
  `.hbar-fill` + **`.pos`** (red) / **`.neg`** (green), `.hbar-val` — JS sets `width` and `left`
- Check outcomes: `.check-row`, `.check-name`, `.check-stack`, `.check-seg` +
  **`.clear`** / **`.review`** / **`.hit`**

**Monitoring:** `.monitor-grid`, `.monitor-tile`, `.monitor-row` (`b`), and ID-scoped
`#sparkline`, `#sparkline polyline.spark-line` (stroke `url(#sparkGradient)`),
`#sparkline polygon.spark-fill`.

**Drawer:** `.drawer`, `.drawer-scrim`, `.drawer-panel`, `.drawer-head`, `.drawer-caseid`,
`.drawer-chips`, `.drawer-body`
→ state: **`.drawer.open`** — a single class on `#case-drawer` drives pointer-events, scrim
opacity, and panel `translateX(100% → 0)`.

**Drawer tabs:** `.drawer-tabs`, `.drawer-tab`, `.drawer-tab .tab-dot` (unread indicator)
→ state: **`.drawer-tab.active`**. Selection key is
`data-tab="overview|interview|review|pipeline|events"`.

**Field readout:** `.drawer-section` (+ `h4`), `.field-grid`, `.field-item`, `.fk`, `.fv`

**Interview form:** `.form-grid`, `.form-field`, **`.form-field.full`** (spans both columns),
`.form-field label`, `.required`, `.field-input`, **`.field-input.reask`** (amber ring),
`.reask-hint`

**Check evidence:** `.check-evidence`, `.check-card`, `.check-card-head`, `.check-card-name`,
`.check-score`, `.candidate` (+ `b`)

**Reviewer gate:** `.decision-note`, `.decision-actions`

**Score waterfall:** `.waterfall`, `.wf-row`, `.wf-feat`, `.wf-track`, `.wf-axis`,
`.wf-fill` + **`.pos`** (anchors `left:50%`) / **`.neg`** (anchors `right:50%`), `.wf-val`,
`.wf-prob`, `.wf-prob .prob-num` (34 px, weight 220)

**Voice orb:** `.voice-pane`, `.orb-wrap`, **`#orb-canvas` (128×128 — a `<canvas>`, so a JS
render loop is implied)**, `.orb-state-label`

**Captions:** `.captions`, `.caption-empty`, `.caption-bubble` + **`.agent`** (left, blue) /
**`.applicant`** (right, purple), `.caption-role`, `.caption-word` + **`.interim`** (42 %
opacity, italic → streaming partial), `.caption-cursor` (blinking caret)

**Pipeline SVG:** `.pipeline-wrap`, `.pipeline-svg` (min-width 520 px), `.pl-node` (styles
child `rect`, `circle`, `text`) + **`.visited`** / **`.current`**, `.pl-node.current .pl-pulse`
(expanding ring), `.pl-edge` + **`.active`** (marching ants)

**Event feed:** `.event-feed` (**`column-reverse`** — JS appends, newest renders on top),
`.event-row`, `.event-dot`, `.event-kind`, `.event-time`

**Toasts:** `.toast-region`, `.toast` + **`.error`** / **`.success`** / **`.info`** +
**`.leaving`** (plays `toast-out` `forwards`, then JS removes the node)

**Responsive:** breakpoints at `1080px` (layout → 1 column; `.field-grid`/`.form-grid` → 1
column) and `640px` (topbar/layout padding, `.drawer-panel` full width, `.case-row` → 1
column, `.case-score` left-aligned). Plus a global `prefers-reduced-motion: reduce`
kill-switch.

---

## 3. Element IDs in index.html

| ID | Element | Purpose |
|---|---|---|
| `voxgate-app` | `div.app-shell` | Root, carries `data-app="voxgate"` |
| `kpi-row` | div | **Empty** — JS renders `.kpi-tile` children |
| `pack-select` | `select` | **Empty** — populate from `GET /packs` |
| `btn-new-case` | button | `POST /cases`; starts `disabled` until packs load |
| `conn-badge` | div | Toggle `.live`/`.connecting`/`.down`; child `.dot` + `.conn-label` |
| `attention-banner` | div, `role="alert"` | Toggle `.show` |
| `attention-text` | span | Message text |
| `attention-view` | button | Jump to offending case |
| `attention-dismiss` | button | Hide banner |
| `board-meta` | div | Counter line, defaults `—` |
| `case-list` | div | Container for `.case-row`s |
| `board-empty` | `.empty-state` | Hide when cases exist |
| `btn-new-case-empty` | button | Duplicate CTA, starts `disabled` |
| `chart-riskband` | div | Render `.dist-bar` + `.dist-legend` |
| `chart-funnel` | div | Render `.funnel` |
| `chart-topfeatures` | div | Render `.hbar-list` |
| `chart-checks` | div | Render `.check-row`s |
| `mon-ws-state` | b | WS state text |
| `mon-poll-latency` | b | ms |
| `mon-open-case` | b | Current case id |
| `mon-events-rate` | b | Events per minute |
| `sparkline` | svg, viewBox `0 0 240 44` | JS writes `points` on two pre-placed shapes |
| `sparkGradient` | linearGradient | Referenced by `.spark-line` stroke |
| `case-drawer` | aside, `aria-hidden="true"` | Toggle `.open` + flip `aria-hidden` |
| `drawer-scrim` | div | Click-to-close |
| `drawer-caseid` | div | Case id |
| `drawer-chips` | div | Render status/risk chips |
| `drawer-close` | button | Close |
| `drawer-tabs` | nav | Delegate clicks; 5 `.drawer-tab[data-tab]` children |
| `drawer-body` | div | **Empty** — all tab content rendered by JS |
| `toast-region` | div, `aria-live="polite"` | Toast mount |
| `btn-seed-demo`, `btn-seed-demo-empty` | button | **No matching backend endpoint exists** |

---

## 4. Gap analysis — the intended feature surface

Everything below is **styled but never rendered**, i.e. exactly what the missing
`dashboard.js` was meant to build.

**A. KPI tiles.** `#kpi-row` is empty. JS generates `.kpi-tile > .kpi-value + .kpi-label`,
marks the active one `.kpi-live`, pulses `.kpi-value.updated` on change.

**B. Case rows.** `#case-list` holds only the empty state. Full template missing:
`.case-row > .case-id + .case-main(.case-pack/.case-sub) + .case-score(.band-*) + .chip.status-*`.
Selection, live-update flash, and status transition are all JS-driven.

**C. All four chart internals.** The `#chart-*` divs hold only `.chart-empty` placeholders.
All are width-transition driven (`transition: width var(--dur-slow)`), so JS should insert at
`width:0` and set the real width on the next frame to get the grow animation.

**D. The entire drawer body.** `#drawer-body` is empty; all five tabs are unwritten:
- *Overview* — `.drawer-section`, `.field-grid`, `.field-item`
- *Interview* — `.form-grid`, `.form-field(.full)`, `.field-input.reask` + `.reask-hint`,
  plus `.voice-pane` and `.captions`
- *Reviewer gate* — `.check-evidence`, `.check-card*`, `.candidate`, `.decision-note`,
  `.decision-actions` with `.btn-success`/`.btn-danger` → `POST /cases/{id}/decision`
- *Scoring* — `.waterfall`, `.wf-*`, `.wf-prob > .prob-num`: a signed contribution waterfall.
  **There is no `data-tab` for scoring** in the nav, so it presumably lives inside Overview
  or Reviewer gate.
- *Pipeline* — `.pipeline-wrap > svg.pipeline-svg` with `.pl-node` / `.pl-edge`, driven by
  `.visited`/`.current`/`.active`
- *Events* — `.event-feed`, fed from `WS /cases/{id}/events`

**E. Voice orb.** `.voice-pane`, `.orb-wrap`, `#orb-canvas` (128×128 canvas),
`.orb-state-label`. **Nothing in the CSS animates the orb** — it is a pure JS/canvas render
loop with an idle/listening/thinking/speaking state label. The single largest unwritten
piece. See the frontend research note §4 for a full implementation approach.

**F. Live captions.** `.caption-word.interim` implies streaming ASR with interim-versus-final
token rendering. **No backend supports this**, and per the Pipecat research note §5, **local
STT cannot produce interim transcripts at all.** This part of the spec needs redesigning, not
just implementing.

**G. Toasts.** No markup; `#toast-region` is empty.

**H. Unrendered misc.** `.skeleton`, `.visually-hidden`, `.chip-sm`, `.tab-dot`,
`.btn-danger`, `.btn-success`, `.field-input`, all `.conn-badge` states,
`.attention-banner.show`, `.drawer.open`.

**I. Backend gaps the markup implies:**
- `#btn-seed-demo` / `#btn-seed-demo-empty` have **no matching endpoint**. Routes today are
  `/packs`, `POST /cases`, `GET /cases`, `GET /cases/{id}`, `PATCH /cases/{id}/fields`,
  `POST /cases/{id}/interview-result`, `POST /cases/{id}/decision`, `WS /cases/{id}/events`.
- **There is no global event stream** — the WebSocket is per-case. So KPIs, the case board,
  and all analytics must be derived client-side from polled `GET /cases`. That is precisely
  why `#mon-poll-latency` exists.
- Case objects carry `case_id, pack_id, status, fields, live_fields, score, decision,
  check_results, audit, interrupt, error`. `interrupt.type` is `"interview"` or `"review"`,
  which should drive drawer tab selection and the `.tab-dot`.

---

## 5. Animations — 13 keyframes

| Keyframe | Attached to | Notes |
|---|---|---|
| `siri-shift` (8s / 6s) | `.brand-mark`, `.funnel-fill` | infinite gradient sweep on 200 % background |
| `kpi-pulse` (`--dur-slow`) | `.kpi-value.updated` | one-shot text-shadow flare; JS adds/removes |
| `dot-pulse` | `.conn-badge.live .dot` (1.8s), `.connecting .dot` (0.9s), `.attention-dot` (1.2s) | infinite opacity + scale breathe |
| `row-in` (`--dur-slow`) | `.case-row` (auto on insert) | slide-down fade-in |
| `row-flash` (900ms) | `.case-row.flash` | purple → `--surface-2` background wash |
| `chip-morph` (`--dur-slow`) | `.chip.status-changed` | scale 0.92→1 + currentColor glow burst |
| `skeleton-sheen` (1.5s) | `.skeleton` | infinite background-position sweep |
| `caption-in` (`--dur-med`) | `.caption-bubble`, `.event-row` | translateY(6px) + scale(0.98) entrance |
| `caret-blink` (900ms, `steps(1)`) | `.caption-cursor` | infinite |
| `pl-pulse-ring` (1.6s) | `.pl-node.current .pl-pulse` | animates SVG `r: 4 → 22` with fade — **requires an SVG `<circle class="pl-pulse">`** |
| `pl-flow` (900ms linear) | `.pl-edge.active` | `stroke-dashoffset: -18` marching ants (`stroke-dasharray: 5 4`) |
| `toast-in` (`--dur-med`) | `.toast` | auto on mount |
| `toast-out` (`--dur-med`, `forwards`) | `.toast.leaving` | JS adds class, removes node after ~260 ms |

All are neutralized under `@media (prefers-reduced-motion: reduce)` — duration forced to
`0.001ms`, iteration count 1. **Consequence: JS must not rely on `animationend` timing alone
without a fallback**, since under reduced motion those events fire almost immediately.

---

## 6. Comments stating intent

File header (lines 1–5):

> `VoxGate Ops Console — design system`
> `Ambient dark, glassmorphism, Siri-gradient accent (blue -> purple -> pink).`
> `Self-contained: no external fonts/CDN. System font stacks only.`

Inline intent comments worth preserving:

- `/* ---- spacing scale (dense ops console) ---- */`
- `/* ---- elevation (soft glow, not hard shadow) ---- */`
- `/* status chip — glowing translucent */`
- **`Analytics charts (pure CSS/JS, no libs)`** — explicit: do not add a chart library
- `Live interview captions — Siri voice pane`

Section banners: Glass panel primitive · Header/topbar · Buttons · connection badge ·
Attention banner · Layout · Case board · Empty/loading states · Monitoring strip · Drawer ·
interview form · Score waterfall · Pipeline graph · Event feed · Toasts · Responsive ·
Reduced motion.

One relevant non-CSS comment — `src/voxgate/service/runner.py:64–73` explicitly defers a
store rebuild-on-boot as "a Plan 3 concern (**the dashboard needs it, once one exists**)",
confirming the dashboard was a known-pending deliverable with a known backend dependency.

---

## 7. What this inventory implies

1. **The design system is genuinely complete and good.** Whatever frontend decision gets made
   (vanilla JS versus Next.js), these tokens, status colours, and component specs should
   survive the port. They encode real product thinking.
2. **Two specified features cannot be built as described**: word-by-word interim captions
   (no local STT source) and the demo-seed button (no endpoint). Both need a decision, not
   just code.
3. **The analytics are all client-derived from polled `GET /cases`** because no global event
   stream exists. If the backend gains one, roughly half the JS complexity disappears.
