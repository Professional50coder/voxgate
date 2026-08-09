# VoxGate — Product Definition

**Decided:** 2026-08-07
**Goal:** A finished B2B SaaS that is genuinely launchable **and** demonstrates engineering
depth. Both, not one at the expense of the other.

---

## 1. What is actually being sold

**Not** "a KYC tool." The market for that is crowded, and the barrier to a first sale in
regulated finance is SOC 2, a pen test, indemnity insurance, and a 6 to 18 month procurement
cycle. That is the hardest possible entry point.

**The product is a durable, auditable, human-in-the-loop interview engine where the workflow
is a plugin.**

The hard, rare part is already built: a conversation that pauses for a human, survives a
process restart, resumes at the exact step it stopped, and records who decided what and why.
KYC is one pack. It is the flagship demo, not the boundary.

The same engine with a different pack is insurance first-notice-of-loss, patient intake, loan
origination, tenant screening, or benefits enrollment. Those have materially lower regulatory
barriers to a first paying customer.

**Positioning:** "Structured interviews that run themselves, with the judgment left to your
people and the paper trail handled."

## 2. Why this demonstrates engineering

The parts that are genuinely hard, and are the reason to show it to an employer:

- **Durable execution with human-in-the-loop.** `interrupt()` plus Postgres checkpointing.
  Most demo projects cannot survive a restart mid-workflow.
- **Explainable ML that a regulator could read.** Additive log-odds scoring where every
  contribution is attributable, not a black-box classifier.
- **Ensemble name matching built for Arabic romanization variants.** A real, specific,
  non-obvious problem.
- **A plugin architecture enforced by a generic conformance suite**, so the "zero platform
  changes" claim cannot quietly become false.
- **A local-first voice pipeline** where the graph drives the dialogue deterministically
  rather than an LLM improvising.

## 3. The three surfaces

| Route | Audience | Arrives via |
|---|---|---|
| `/` | The buyer: Head of Compliance, COO, Head of Ops | Search, outbound, demo link |
| `/apply/<token>` | The applicant: your customer's customer | A tokenized link sent to them |
| `/console` | The reviewer: compliance or ops officer | Daily driver, behind login |

The applicant never sees the marketing site. The buyer rarely uses `/apply` outside a demo.

## 4. Definition of "finished"

Shipping means all of these are true. Anything less is a prototype.

### Blocking for launch

- [ ] **Authentication.** Signup, login, sessions. Today anyone reaching `/console` sees
      every applicant's name and date of birth. For an identity product that is a breach,
      not a missing feature.
- [ ] **Enforced multi-tenancy.** Schema is tenant-ready; the auth boundary is stubbed.
      Cross-tenant access must be tested, and must return 404 rather than 403.
- [ ] **The production spine.** Async execution, Postgres case index, durable event stream.
      Specced and approved in `docs/superpowers/specs/2026-08-07-production-spine-design.md`.
      Without it the case board is wiped by any restart.
- [ ] **Tokenized applicant links.** An applicant reaches exactly one case and nothing else.
- [ ] **Deployment.** Real host, TLS, a domain, and CI that runs the suite.
- [ ] **Local voice.** The current Web Speech API path streams audio to Google. Acceptable
      for a demo, disqualifying for identity data. Pipecat with local faster-whisper replaces it.

### Blocking for credibility as a platform

- [ ] **A second pack.** The "adding a use case touches zero platform code" claim has only
      ever been exercised by one pack. Until a second exists it is an assertion.

### Not blocking for a first customer

- Billing. "Contact us" is a legitimate first pricing page; Stripe can follow the first
  signed customer.
- SOC 2. Necessary for regulated finance, not for the lower-barrier verticals above.
- Real sanctions data feeds. Licensed feeds (Dow Jones, Refinitiv, ComplyAdvantage) are a
  real cost. Synthetic data is correct until a customer requires otherwise, and the pack
  boundary means swapping the source touches one file.

## 5. Build sequence

Ordered by dependency, not by visibility. Each phase leaves the product working.

| # | Phase | Why here | Rough effort |
|---|---|---|---|
| 1 | **Production spine** | Everything else writes to Postgres. Auth needs a user table; the case board needs to survive restarts. Doing this later means doing the rest twice. | 1 week |
| 2 | **Auth + enforced tenancy + tokenized apply links** | The single largest gap between "demo" and "product". Shares the database work with phase 1. | 4 days |
| 3 | **Deploy** | A URL makes it real, makes it demoable, and makes CI meaningful. | 2 days |
| 4 | **Pipecat local voice** | The differentiator, and it removes the PII objection that blocks any serious conversation. | 1 week |
| 5 | **Second pack** | Converts the platform claim from assertion to demonstrated fact. | 3 days |
| 6 | **Console depth** | Score waterfall, live pipeline, analytics. Highest visual payoff, lowest structural risk, so it comes last. | 4 days |

**Honest total: roughly four focused weeks.** Anyone quoting less has not counted auth,
deployment, or the voice pipeline.

## 6. What is deliberately not being built

- A second product surface for mobile. The applicant flow is responsive web; a native app
  earns nothing until a customer asks.
- An admin panel for managing packs through a UI. Packs are a filesystem contract, and that
  is a feature, not a gap.
- Analytics dashboards beyond what a reviewer needs to make a decision. Vanity metrics do
  not sell compliance software.
- LLM-driven dialogue. The graph drives the questions deterministically. That is the
  auditability story and it should not be traded away for conversational polish.
