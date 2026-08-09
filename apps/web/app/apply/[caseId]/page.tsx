import type { Metadata } from "next";

import { InterviewFlow } from "@/components/interview-flow";

export const metadata: Metadata = {
  title: "Complete your interview",
  description: "Answer your onboarding questions out loud, whenever suits you.",
  // Invite links must never be indexed. They address one applicant's case.
  robots: { index: false, follow: false, nocache: true },
};

/**
 * Invited entry point. The applicant opens this at their convenience and the
 * completed case lands back on the reviewer's board.
 *
 * Security note, stated plainly: the case id is the bearer token here. A UUIDv4
 * is unguessable, but anyone holding the URL can answer the interview, and the
 * link does not expire. Before this carries real applicant data it needs a
 * separate signed, expiring token rather than the case id. Tracked in
 * docs/PRODUCT.md section 4.
 */
export default async function InvitedApply({
  params,
}: {
  params: Promise<{ caseId: string }>;
}) {
  const { caseId } = await params;
  return <InterviewFlow caseId={caseId} />;
}
