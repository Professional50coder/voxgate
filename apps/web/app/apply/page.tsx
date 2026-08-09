import type { Metadata } from "next";

import { InterviewFlow } from "@/components/interview-flow";

export const metadata: Metadata = {
  title: "Start your interview",
  description:
    "Answer a short set of onboarding questions out loud. Takes about two minutes.",
  // Open access, but there is nothing here worth ranking and a shared link
  // should not compete with the marketing page.
  robots: { index: false, follow: true },
};

/** Open entry point. Anyone landing here starts a fresh case. */
export default function Apply() {
  return <InterviewFlow />;
}
