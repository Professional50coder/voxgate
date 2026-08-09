# Agent Skills Inventory — which apply to VoxGate

**Date:** 2026-08-07
**Purpose:** A scan of the locally available agent skills, filtered to the ones that
genuinely apply to this project, with a note on *when* each should fire. Recorded so future
sessions invoke the right skill instead of improvising.

The full local roster is ~45 skills. Most are irrelevant here (banner design, logo
generation, Spotify, ClickUp). This note covers the ones that are not.

---

## 1. Process skills — these set the approach and come first

When several skills apply, process skills win: they decide *how* the work is done, then
implementation skills carry it out.

| Skill | Fires when | Why it matters here |
|---|---|---|
| **`superpowers:brainstorming`** | Before ANY creative/build work — new features, components, behaviour changes | Mandatory before planning. The whole next phase of VoxGate is greenfield (frontend rewrite, voice layer, graph upgrade) so this fires first, every time. |
| **`superpowers:writing-plans`** | Once requirements exist, before touching code | The Next.js migration and LangGraph upgrade both need a written plan before implementation. |
| **`superpowers:subagent-driven-development`** | Executing a plan with independent tasks in-session | **This is how the existing backend was built** — the ledger at `.superpowers/sdd/2026-08-06-voxgate-core-platform/` is its output. Continue the same pattern. |
| **`superpowers:executing-plans`** | Executing a written plan in a *separate* session with review checkpoints | The alternative to the above for long multi-session work. |
| **`superpowers:test-driven-development`** | Implementing any feature or bugfix, before writing implementation code | The project is at 54 green tests with real discipline. Do not break the habit. |
| **`superpowers:systematic-debugging`** | Any bug, test failure, or unexpected behaviour, before proposing a fix | |
| **`superpowers:requesting-code-review`** | Completing a task or feature, before merging | **Two reviews are outstanding**: graph Wave 1, and the final whole-project pass. |
| **`superpowers:receiving-code-review`** | Acting on review feedback | Requires verification, not performative agreement. |
| **`superpowers:verification-before-completion`** | About to claim work is done/fixed/passing | Evidence before assertions. Relevant given the memory note that a previous ship was "deploy triggered but UNVERIFIED". |
| **`superpowers:dispatching-parallel-agents`** | 2+ independent tasks with no shared state | Used heavily in this research session. |
| **`superpowers:using-git-worktrees`** | Feature work needing isolation | Newly relevant — the repo now has git (as of 2026-08-07). |
| **`superpowers:finishing-a-development-branch`** | Implementation complete, tests pass, deciding how to integrate | |

---

## 2. Frontend and design skills — the cluster the user asked about

The dashboard rewrite is the biggest single piece of remaining work, so this is where skill
selection matters most.

### Primary

| Skill | Fires when | Fit for VoxGate |
|---|---|---|
| **`ui-ux-pro-max`** | Designing, building, or reviewing any UI | **Strongest fit.** Searchable local database: 67 styles, 161 palettes, 57 font pairings, 25 chart types, 21 stacks including Next.js, React, Tailwind, shadcn/ui. Use it to validate the existing Siri palette and to pick the Next.js component architecture. |
| **`frontend-design`** | Distinctive, intentional visual design for new or reshaped UI | Guards against templated defaults. The existing design system already has a point of view; this skill helps preserve it through the port. |
| **`design-taste-frontend`** | Landing pages, portfolios, redesigns; audit-first on redesigns | **The "audit-first on redesigns" behaviour is exactly right** for porting a half-built dashboard rather than starting over. |
| **`hallmark`** | Greenfield pages, audits, redesigns, design extraction | Overlaps the above. Anti-AI-slop framing. Pick one of these three per task rather than stacking them. |

### Supporting

| Skill | Fires when | Fit |
|---|---|---|
| **`dataviz`** | **Before writing the first line of any chart code** | Directly applicable — four analytics charts are unbuilt, and the CSS explicitly says "pure CSS/JS, no libs". This skill's colour formula and accessibility validator apply even to hand-rolled CSS bars. |
| **`accessibility`** | A11y audit, WCAG compliance, keyboard nav, screen readers | **Non-optional.** Compliance software ships into regulated organizations with hard WCAG 2.2 AA procurement requirements. Also the voice orb needs an `aria-live` text equivalent. |
| **`web-design-guidelines`** | Reviewing UI code against interface guidelines | Good final gate before shipping the dashboard. |
| **`vercel-react-best-practices`** | Writing/reviewing React or Next.js code | Fires the moment the Next.js migration starts. |
| **`tailwind-design-system`** | Design systems with Tailwind v4, tokens, component libraries | Relevant if the port adopts Tailwind. The existing tokens map cleanly onto Tailwind v4 CSS variables. |
| **`ui-styling`** | shadcn/ui, Radix, Tailwind, accessible components | Useful for the drawer, tabs, dialogs, and form controls — all of which the current CSS styles but never implements accessibly. |
| **`building-components`** | Building modern accessible composable components | For the component library the Next.js port implies. |
| **`design-system`** | Token architecture, three-layer tokens, component specs | The current tokens are single-layer (primitive only). This skill's primitive→semantic→component structure is the natural upgrade. |
| **`core-web-vitals`** / **`performance`** | LCP/INP/CLS, load time | Relevant given the frontend research flagged `backdrop-filter` over-use as a real frame-rate risk. |
| **`web-quality-audit`** | Comprehensive perf + a11y + SEO + best-practices audit | Good single-command final gate. |
| **`best-practices`** | Security audit, modernization, vulnerability check | |

### Animation cluster

| Skill | Fires when |
|---|---|
| **`hyperframes-animation`** | Any motion/animation task — atomic motion rules, scene blueprints, runtime adapters (GSAP, Lottie, Three.js, CSS keyframes, Web Animations API) |
| **`find-animation-opportunities`** | "What could be animated here?" — read-only, proposes with exact values |
| **`improve-animations`** | Auditing existing motion and producing a prioritized roadmap |
| **`animation-vocabulary`** | Reverse-lookup: turning a vague description into the exact term |

The dashboard has 13 keyframes already defined plus an unbuilt canvas orb, so
`hyperframes-animation` is the relevant one for implementation; `improve-animations` for the
audit pass afterwards.

### Not a fit

`banner-design`, `brand`, `design` (logo/CIP/social), `slides`, `seo`,
`extract-design-system`, `ai-image-generation`. VoxGate is an internal ops console, not a
marketing surface.

---

## 3. Backend, API, and infra skills

| Skill | Fires when | Fit |
|---|---|---|
| **`claude-api`** | **Any LLM-shaped task where the provider is unstated**, or Claude/Anthropic is named | Has an explicit trigger rule: read it *before* opening the target file. Note the skill's own SKIP condition — it does not apply when another provider is actively being worked on. **Groq is now that provider**, so this skill will usually skip for VoxGate's LLM work. Worth knowing so it is not invoked reflexively. |
| **`security-review`** | Security review of pending changes | Relevant: this project handles KYC PII and now has a live API key in `.env`. |
| **`run`** | Launch and drive the app to confirm a change works in the real app | Directly useful — the memory notes a prior ship went out with no live UI pass. |
| **`init`** | Initialize a CLAUDE.md for the codebase | **Worth doing.** There is no CLAUDE.md; the constraints currently live in `.paul/` and the SDD ledger where a fresh agent will not automatically see them. |
| **`update-config`** | Hooks, permissions, env vars in settings.json | For automating the test-run-on-save style workflows. |
| **`fewer-permission-prompts`** | Reduce repeated permission prompts | Practical quality-of-life given how much `uv run` this project does. |

**Not a fit:** `deep-agents-memory`, `elite-longterm-memory`, `agentmemory-agents` — these
are for building agent memory systems, which VoxGate is not.

---

## 4. Recommended invocation order for the next phase

1. **`superpowers:brainstorming`** — before anything. The direction changed substantially
   (Next.js, production, multi-use-case, Groq, heavy Pipecat) and requirements need to be
   pinned down before a plan exists.
2. **`superpowers:writing-plans`** — turn the agreed direction into a written plan.
3. Per implementation area, the matching design/implementation skill:
   - Dashboard/Next.js → `ui-ux-pro-max` + `vercel-react-best-practices` + `dataviz` +
     `accessibility`
   - Voice layer → no dedicated skill; driven by
     `docs/research/2026-08-07-pipecat-integration.md`
   - Graph upgrade → no dedicated skill; driven by the LangGraph research note
4. **`superpowers:test-driven-development`** throughout.
5. **`superpowers:requesting-code-review`** at each task boundary, then
   **`superpowers:verification-before-completion`** before claiming anything is done.

---

## 5. One standing note

The `using-superpowers` meta-skill states the rule plainly: **if there is even a 1 % chance a
skill applies, invoke it** — before any response, including clarifying questions, and before
exploring the codebase. The failure mode it guards against is rationalizing that a task is
"too simple" for a skill. Worth re-reading at the start of each session rather than trusting
a remembered version, since skills evolve.
