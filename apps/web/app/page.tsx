import {
  ArrowRight,
  Books,
  Broadcast,
  ChartBar,
  ClockCounterClockwise,
  Eye,
  FileText,
  FlowArrow,
  Gavel,
  Lightning,
  ListChecks,
  Microphone,
  Plugs,
  ShieldCheck,
  Sparkle,
  UserFocus,
} from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";

import { AgentCard } from "@/components/agent-card";
import { FeatureCard, StatCard } from "@/components/feature-card";
import { GlassRibbons } from "@/components/glass-ribbons";
import { Nav } from "@/components/nav";
import { PipelineDiagram } from "@/components/pipeline-diagram";
import { Reveal } from "@/components/reveal";
import { ScrollProgress } from "@/components/scroll-progress";
import { SpotlightCard } from "@/components/spotlight-card";
import { WaveRibbon } from "@/components/wave-ribbon";

const SHELL = "mx-auto w-full max-w-[1200px] px-6";
const EYEBROW = "text-[11px] uppercase tracking-[0.18em] text-text-faint";
const H2 = "text-3xl font-semibold leading-[1.12] tracking-tight md:text-4xl";
const LEAD = "mt-5 max-w-[60ch] text-base leading-relaxed text-text-dim";
const SECTION = "border-t border-glass-border-soft py-24 md:py-32";
const GRID3 = "mt-14 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3";

/**
 * Structure, and why it is in this order.
 *
 * Hero, then what it does, then proof, then how it is built, then who it is
 * for, then trust, then the ask. The previous version put the essay before the
 * capability, so a visitor had to read four paragraphs about analyst workload
 * before learning what the product was — and the strongest single claim
 * (durable, resumable state) was buried as three mono words in the corner of a
 * bento cell. Those three words are now three cards, because each one is a
 * separate promise a buyer will want to interrogate.
 *
 * Density is deliberate. One repeated card shape at three spans reads as a
 * system; four different card treatments read as four unrelated pages.
 */
export default function Home() {
  return (
    <>
      <Nav />
      <ScrollProgress />
      <main>
        {/* 1. Hero. Centered on purpose: launch-style composition where the
            message and the product card are the design. */}
        <section className="relative flex min-h-[calc(100dvh-4rem)] flex-col items-center justify-center overflow-hidden px-6 pt-10 pb-14">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                "radial-gradient(1100px 620px at 50% 34%, #4A1D69 0%, #2A123C 34%, #18071F 62%, #09030C 100%)",
            }}
          />
          <GlassRibbons className="pointer-events-none absolute inset-0 h-full w-full" />
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                "radial-gradient(120% 90% at 50% 42%, rgba(9,3,12,0) 32%, rgba(9,3,12,0.68) 100%)",
            }}
          />
          {/* Contrast scrim. The ribbons move, so the headline cannot rely on
              whatever happens to be behind it at a given moment. */}
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-0 top-0 h-[52%]"
            style={{
              background:
                "radial-gradient(60% 100% at 50% 30%, rgba(9,3,12,0.82) 0%, rgba(9,3,12,0.45) 55%, rgba(9,3,12,0) 100%)",
            }}
          />

          <div className="relative flex flex-col items-center text-center">
            <span className="mb-6 inline-flex items-center gap-2 rounded-[var(--r-pill)] border border-glass-border-soft px-3.5 py-1.5 text-[12px] text-text-dim">
              <Sparkle size={13} weight="fill" color="var(--color-siri-1)" />
              Nine live scenario packs, each a folder of Python
            </span>

            <h1 className="max-w-[22ch] text-[32px] font-bold leading-[1.1] tracking-tight text-white md:text-[42px] lg:text-[48px]">
              Automate compliance intake with voice agents
            </h1>
            <p className="mt-4 max-w-[52ch] text-[15px] leading-relaxed text-[#B7B7C2] md:text-[16.5px]">
              Your applicants answer out loud. VoxGate screens every answer and hands your
              reviewers a decision that already explains itself.
            </p>

            <div className="mt-7">
              <AgentCard />
            </div>

            <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
              <Link
                href="/console"
                className="inline-flex items-center gap-2 rounded-[var(--r-pill)] px-6 py-3 text-[14.5px] font-semibold text-[#0a0a12] transition-transform active:scale-[0.98]"
                style={{ background: "var(--siri-gradient)" }}
              >
                Open the console
                <ArrowRight size={16} weight="bold" />
              </Link>
              <Link
                href="#pipeline"
                className="inline-flex items-center gap-2 rounded-[var(--r-pill)] border px-6 py-3 text-[14.5px] font-medium text-white transition-colors active:scale-[0.98]"
                style={{
                  background: "rgba(255,255,255,0.06)",
                  borderColor: "rgba(255,255,255,0.12)",
                }}
              >
                See how it works
              </Link>
            </div>
          </div>
        </section>

        {/* Parametric wave band. */}
        <section className="relative h-[220px] overflow-hidden border-t border-glass-border-soft md:h-[280px]">
          <WaveRibbon className="absolute inset-0 h-full w-full" />
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                "linear-gradient(to bottom, rgba(6,8,16,0.85) 0%, rgba(6,8,16,0) 38%, rgba(6,8,16,0.9) 100%)",
            }}
          />
        </section>

        {/* 2. What it does. Moved ahead of the argument: a visitor should learn
            what the product IS before being told why the problem matters. */}
        <section id="capabilities" className={SECTION}>
          <div className={SHELL}>
            <Reveal>
              <p className={EYEBROW}>What it does</p>
              <h2 className={`mt-5 max-w-[24ch] ${H2}`}>
                Six things it does, end to end.
              </h2>
              <p className={LEAD}>
                Not a demo path. Each of these runs in the shipped system, against a
                real state machine, with tests behind it.
              </p>
            </Reveal>

            <div className={GRID3}>
              {[
                {
                  icon: Microphone,
                  tone: "ice" as const,
                  featured: true,
                  title: "Conducts the interview",
                  body: "The applicant speaks. The system asks one question at a time, in the pack's own wording, and re-asks when an answer does not fit.",
                },
                {
                  icon: UserFocus,
                  tone: "periwinkle" as const,
                  title: "Maps speech to schema",
                  body: "A spoken sentence becomes the exact value the schema requires. Allowed values come from the pack, so the extractor and validator cannot disagree.",
                },
                {
                  icon: ListChecks,
                  tone: "lavender" as const,
                  title: "Screens every answer",
                  body: "Sanctions, politically exposed persons and adverse media. Name matching handles romanization variants rather than exact strings.",
                },
                {
                  icon: ChartBar,
                  tone: "mint" as const,
                  title: "Scores it, showing its work",
                  body: "An additive scorecard, so every case can be broken down into which signal contributed what, and by how much.",
                },
                {
                  icon: Gavel,
                  tone: "periwinkle" as const,
                  title: "Routes to a human when it should",
                  body: "Low risk clears automatically. Anything near the line stops and waits for a named reviewer, with the evidence already attached.",
                },
                {
                  icon: FileText,
                  tone: "ice" as const,
                  title: "Writes the record as it goes",
                  body: "Every node logs what changed, who acted and how long it took, in order, as part of the case rather than as a side log.",
                },
              ].map((c, i) => (
                <Reveal key={c.title} delay={(i % 3) * 0.07}>
                  <SpotlightCard className="h-full">
                    <FeatureCard
                      icon={c.icon}
                      title={c.title}
                      tone={c.tone}
                      featured={c.featured}
                    >
                      {c.body}
                    </FeatureCard>
                  </SpotlightCard>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* 3. The hard part, now three cards instead of three words in a corner. */}
        <section id="durability" className={SECTION}>
          <div className={SHELL}>
            <Reveal>
              <p className={EYEBROW}>The hard part</p>
              <h2 className={`mt-5 max-w-[26ch] ${H2}`}>
                It pauses for humans without losing its place.
              </h2>
              <p className={LEAD}>
                A case can stop mid-flight waiting for someone to speak or for a reviewer
                to click, survive a process restart while stopped, and resume at the exact
                step it left. That is the hard engineering problem in this class of
                system. These are the three parts of it.
              </p>
            </Reveal>

            <div className={GRID3}>
              {[
                {
                  icon: ClockCounterClockwise,
                  tone: "ice" as const,
                  featured: true,
                  title: "Durable checkpoints",
                  body: "State is written to Postgres at every step, not held in memory. Kill the process mid-interview and the case is exactly where it was.",
                  meta: ["postgres", "per-node commit"],
                },
                {
                  icon: FlowArrow,
                  tone: "periwinkle" as const,
                  title: "Resumable threads",
                  body: "A paused case is a thread waiting on an interrupt, not a row with a status column. Resuming continues the graph rather than replaying it.",
                  meta: ["interrupt", "resume"],
                },
                {
                  icon: Eye,
                  tone: "lavender" as const,
                  title: "Full audit trail",
                  body: "The sequence of nodes, the timing of each, and the state before and after, kept as case data. A regulator's question has an answer in the record.",
                  meta: ["ordered", "immutable"],
                },
              ].map((c, i) => (
                <Reveal key={c.title} delay={i * 0.07}>
                  <SpotlightCard className="h-full">
                    <FeatureCard
                      icon={c.icon}
                      title={c.title}
                      tone={c.tone}
                      featured={c.featured}
                      meta={c.meta}
                    >
                      {c.body}
                    </FeatureCard>
                  </SpotlightCard>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* 4. Pipeline. The strongest visual on the page, so it gets a band. */}
        <section id="pipeline" className={SECTION}>
          <div className={SHELL}>
            <Reveal>
              <p className={EYEBROW}>The state machine</p>
              <h2 className={`mt-5 max-w-[22ch] ${H2}`}>
                One case, from first question to signed decision.
              </h2>
              <p className={LEAD}>
                This is the actual graph, not a simplification. It pauses at the two
                points where a human matters and picks up exactly where it stopped, even
                if the server restarted in between.
              </p>
            </Reveal>
            <Reveal delay={0.12}>
              <div className="mt-14 rounded-[var(--r-card)] border border-glass-border-soft bg-[var(--color-surface-2)] p-6 md:p-10">
                <PipelineDiagram />
              </div>
            </Reveal>
          </div>
        </section>

        {/* 5. The division of labour. Was three hairline cells of prose; the
            point of the product lives here, so it gets real cards. */}
        <section id="problem" className={SECTION}>
          <div className={SHELL}>
            <Reveal>
              <p className={EYEBROW}>Why this exists</p>
              <h2 className={`mt-5 max-w-[22ch] ${H2}`}>
                Onboarding one client takes an analyst most of an hour.
              </h2>
              <p className={LEAD}>
                Someone collects the details, checks them against sanctions and
                politically exposed person lists, judges how risky the applicant is, and
                writes a justification a regulator can read later. The parts that need
                judgment are worth an analyst&apos;s time. Collecting a date of birth is
                not.
              </p>
            </Reveal>

            <div className={GRID3}>
              {[
                {
                  icon: Microphone,
                  tone: "ice" as const,
                  title: "Collection",
                  body: "Fully automated. The applicant talks, the system fills the form, and re-asks anything that does not validate.",
                  meta: ["automated"],
                },
                {
                  icon: ShieldCheck,
                  tone: "periwinkle" as const,
                  title: "Screening",
                  body: "Fully automated. Name matching handles romanization variants, so a transliterated name still hits the list it should.",
                  meta: ["automated"],
                },
                {
                  icon: Gavel,
                  tone: "lavender" as const,
                  featured: true,
                  title: "Judgment",
                  body: "Still human, by design. It now arrives with the evidence attached, the score broken down, and the trail already written.",
                  meta: ["human, deliberately"],
                },
              ].map((c, i) => (
                <Reveal key={c.title} delay={i * 0.07}>
                  <SpotlightCard className="h-full">
                    <FeatureCard
                      icon={c.icon}
                      title={c.title}
                      tone={c.tone}
                      featured={c.featured}
                      meta={c.meta}
                    >
                      {c.body}
                    </FeatureCard>
                  </SpotlightCard>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* 6. Numbers. A page arguing from engineering should show figures. */}
        <section className={SECTION}>
          <div className={SHELL}>
            <Reveal>
              <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                <StatCard value="9" label="Scenario packs, live" tone="ice" />
                <StatCard value="272" label="Tests green against Postgres" tone="periwinkle" />
                <StatCard value="5" label="Files to add a new use case" tone="lavender" />
                <StatCard value="0" label="Platform changes to add one" tone="mint" />
              </div>
            </Reveal>
          </div>
        </section>

        {/* 7. Architecture. Two spans of the same card, plus the folder listing
            that makes the claim concrete. */}
        <section id="architecture" className={SECTION}>
          <div className={SHELL}>
            <Reveal>
              <p className={EYEBROW}>How it is built</p>
              <h2 className={`mt-5 max-w-[24ch] ${H2}`}>
                A new use case is a folder, not a rewrite.
              </h2>
            </Reveal>

            <div className="mt-14 grid grid-cols-1 gap-5 lg:grid-cols-3">
              <Reveal className="lg:col-span-2">
                <SpotlightCard className="h-full">
                  <article className="flex h-full flex-col overflow-hidden rounded-[var(--r-card)] border border-glass-border-soft bg-[var(--color-surface-2)] p-7 md:p-9">
                    <div className="grid grid-cols-1 gap-8 md:grid-cols-12 md:items-center">
                      <div className="md:col-span-7">
                        <span
                          aria-hidden="true"
                          className="inline-flex h-11 w-11 items-center justify-center rounded-[11px] border border-glass-border-soft"
                          style={{ background: "rgba(255,255,255,0.04)" }}
                        >
                          <Books size={20} weight="duotone" color="var(--color-siri-3)" />
                        </span>
                        <h3 className="mt-6 text-[17px] font-semibold leading-snug tracking-tight">
                          Every agent is five files on disk
                        </h3>
                        <p className="mt-3 text-[14px] leading-relaxed text-text-dim">
                          Each scenario is a self-contained pack holding its own schema,
                          checks, scoring model and prompts. Adding one touches no
                          platform code, and a generic conformance suite enforces that
                          claim so it cannot quietly stop being true.
                        </p>
                      </div>
                      <div className="md:col-span-5">
                        <pre
                          className="overflow-x-auto rounded-[var(--r-input)] border border-glass-border-soft bg-[#05070e] p-5 text-[12.5px] leading-[1.8] text-text-dim"
                          style={{ fontFamily: "var(--font-geist-mono), monospace" }}
                        >
                          {`packs/kyc_uae/
  pack.yaml
  schema.py
  checks.py
  scoring.py
  prompt.md`}
                        </pre>
                      </div>
                    </div>
                  </article>
                </SpotlightCard>
              </Reveal>

              <Reveal delay={0.08}>
                <SpotlightCard className="h-full">
                  <FeatureCard
                    icon={Lightning}
                    title="Packs can be authored, not just written"
                    tone="ice"
                    meta={["describe", "review", "publish"]}
                  >
                    Describe a business process in plain English and the system drafts a
                    pack for review. Publishing compiles it into a live graph without a
                    restart.
                  </FeatureCard>
                </SpotlightCard>
              </Reveal>

              <Reveal delay={0.04}>
                <SpotlightCard className="h-full">
                  <FeatureCard
                    icon={ChartBar}
                    title="Every risk number is explainable"
                    tone="mint"
                  >
                    The score is additive, so you can point at any case and say which
                    signal contributed what. For regulated work that matters more than raw
                    accuracy.
                  </FeatureCard>
                </SpotlightCard>
              </Reveal>

              <Reveal delay={0.08}>
                <SpotlightCard className="h-full">
                  <FeatureCard
                    icon={Broadcast}
                    title="The console watches cases live"
                    tone="periwinkle"
                  >
                    A WebSocket streams each state change as it happens, so a reviewer sees
                    a case move through the graph rather than refreshing a table.
                  </FeatureCard>
                </SpotlightCard>
              </Reveal>

              <Reveal delay={0.12}>
                <SpotlightCard className="h-full">
                  <FeatureCard
                    icon={Plugs}
                    title="Deploys behind your own DNS"
                    tone="lavender"
                  >
                    Two processes and a Postgres database. The frontend proxies to the API,
                    so the browser only ever talks to one origin.
                  </FeatureCard>
                </SpotlightCard>
              </Reveal>
            </div>
          </div>
        </section>

        {/* 8. Packs. Kept as a list: these are inventory, not claims, and turning
            them into cards too would flatten the page's rhythm entirely. */}
        <section id="packs" className={SECTION}>
          <div className={SHELL}>
            <Reveal>
              <p className={EYEBROW}>Use cases</p>
              <h2 className={`mt-5 max-w-[24ch] ${H2}`}>
                Built for KYC first. The shape generalizes.
              </h2>
            </Reveal>

            <div className="mt-14 grid grid-cols-1 gap-x-16 gap-y-10 md:grid-cols-2">
              {[
                {
                  name: "kyc-uae",
                  status: "Shipping",
                  d: "Client onboarding for a Dubai fintech. Sanctions, PEP and adverse media screening with a seven feature AML risk scorecard.",
                },
                {
                  name: "loan-intake",
                  status: "Shipping",
                  d: "Consumer lending applications, where the reviewer gate becomes a two person maker and checker approval.",
                },
                {
                  name: "claim-fnol",
                  status: "Shipping",
                  d: "First notice of loss for insurance, where a fraud investigation stage runs only when the score crosses a threshold.",
                },
                {
                  name: "patient-intake",
                  status: "Shipping",
                  d: "Clinical intake, where low risk cases skip the human gate entirely and route straight to triage.",
                },
                {
                  name: "tenant-screening",
                  status: "Shipping",
                  d: "Rental applications, scoring affordability and history before a letting agent ever reads the file.",
                },
                {
                  name: "recruit-screen",
                  status: "Shipping",
                  d: "First round candidate screening, where the pack's questions are the rubric and the score is the shortlist.",
                },
              ].map((pack, i) => (
                <Reveal key={pack.name} delay={(i % 2) * 0.07}>
                  <div className="group border-t border-glass-border-soft pt-6 transition-colors hover:border-[var(--color-siri-2)]/50">
                    <div className="flex items-baseline justify-between gap-4">
                      <h3
                        className="text-[15px] font-semibold text-text"
                        style={{ fontFamily: "var(--font-geist-mono), monospace" }}
                      >
                        {pack.name}
                      </h3>
                      <span className="shrink-0 text-[11.5px] text-text-faint">
                        {pack.status}
                      </span>
                    </div>
                    <p className="mt-3 text-[14px] leading-relaxed text-text-dim">{pack.d}</p>
                  </div>
                </Reveal>
              ))}
            </div>

            <Reveal delay={0.1}>
              <div className="mt-12">
                <Link
                  href="/agents"
                  className="inline-flex items-center gap-2 text-[14px] font-medium text-text transition-colors hover:text-[var(--color-siri-1)]"
                >
                  Browse the full agent library
                  <ArrowRight size={15} weight="bold" />
                </Link>
              </div>
            </Reveal>
          </div>
        </section>

        {/* 9. Trust. Same card shape as everything else, which is the point. */}
        <section id="trust" className={SECTION}>
          <div className={SHELL}>
            <Reveal>
              <p className={EYEBROW}>Handling</p>
              <h2 className={`mt-5 max-w-[24ch] ${H2}`}>
                Local first, because the data is somebody&apos;s identity.
              </h2>
            </Reveal>

            <div className={GRID3}>
              {[
                {
                  icon: Microphone,
                  tone: "ice" as const,
                  title: "Speech never has to leave the machine",
                  body: "Transcription runs locally by default. Hosted inference is an opt-in fallback for burst load, behind the same interface.",
                },
                {
                  icon: ShieldCheck,
                  tone: "mint" as const,
                  featured: true,
                  title: "Identifiers can be redacted before any network call",
                  body: "Deterministic checks mean an external model can be sent field shapes and verdicts rather than raw passport or ID numbers.",
                },
                {
                  icon: FileText,
                  tone: "lavender" as const,
                  title: "Every decision carries its own audit trail",
                  body: "Each node records what changed, who acted and how long it took, in order, as part of the case state rather than as a side log.",
                },
              ].map((c, i) => (
                <Reveal key={c.title} delay={i * 0.07}>
                  <SpotlightCard className="h-full">
                    <FeatureCard
                      icon={c.icon}
                      title={c.title}
                      tone={c.tone}
                      featured={c.featured}
                    >
                      {c.body}
                    </FeatureCard>
                  </SpotlightCard>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* 10. Close. */}
        <section className={SECTION}>
          <div className={SHELL}>
            <Reveal>
              <div className="glass rounded-[var(--r-card)] px-8 py-14 text-center md:px-16 md:py-20">
                <h2 className={`mx-auto max-w-[20ch] ${H2}`}>
                  Watch a case run end to end.
                </h2>
                <p className="mx-auto mt-6 max-w-[54ch] text-base leading-relaxed text-text-dim">
                  The console shows the live pipeline, the score broken down by
                  contribution, and the reviewer gate as it opens.
                </p>
                <div className="mt-9 flex flex-wrap justify-center gap-3">
                  <Link
                    href="/console"
                    className="inline-flex items-center gap-2 rounded-[var(--r-pill)] px-7 py-3.5 text-[14.5px] font-semibold text-[#0a0a12] transition-transform active:scale-[0.98]"
                    style={{ background: "var(--siri-gradient)" }}
                  >
                    Open console
                    <ArrowRight size={16} weight="bold" />
                  </Link>
                  <Link
                    href="/apply"
                    className="inline-flex items-center gap-2 rounded-[var(--r-pill)] border px-7 py-3.5 text-[14.5px] font-medium text-white transition-colors active:scale-[0.98]"
                    style={{
                      background: "rgba(255,255,255,0.06)",
                      borderColor: "rgba(255,255,255,0.12)",
                    }}
                  >
                    Take the interview yourself
                  </Link>
                </div>
              </div>
            </Reveal>
          </div>
        </section>
      </main>

      <footer className="border-t border-glass-border-soft py-12">
        <div
          className={`${SHELL} flex flex-col items-start justify-between gap-5 sm:flex-row sm:items-center`}
        >
          <div className="flex items-center gap-2.5">
            <span
              aria-hidden="true"
              className="h-4 w-4 rounded-full"
              style={{ background: "var(--siri-gradient)" }}
            />
            <span className="text-[13.5px] font-medium">VoxGate</span>
          </div>
          <p className="text-[12.5px] text-text-faint">
            All screening data in this build is synthetic and marked as such.
          </p>
        </div>
      </footer>
    </>
  );
}
