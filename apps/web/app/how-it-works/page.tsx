import type { Metadata } from "next";

import { HowItWorks } from "@/components/how-it-works";
import { Nav } from "@/components/nav";

export const metadata: Metadata = {
  title: "How it works",
  description:
    "Talk to VoxGate's voice assistant, watch an interview move through the pipeline, and test each voice agent's own rules live, with the latency of every turn shown.",
  alternates: { canonical: "/how-it-works" },
};

export default function Page() {
  return (
    <>
      <Nav />
      <main id="main">
        <HowItWorks />
      </main>
    </>
  );
}
