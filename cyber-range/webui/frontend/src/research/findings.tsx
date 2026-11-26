// UX-18: every finding across arenas, opened in place. Decisions are made in
// the finding's arena, where its evidence review and controls live.
import type { FindingRecord } from "../types";
import { ErrorState, Loading, PageHead, useWorkspaceData } from "../ui";
import { FindingList } from "../shared/finding-list";

export function FindingsPage() {
  const { value, error, loading, refresh } = useWorkspaceData<{
    findings: FindingRecord[];
    observed_at: string;
  }>("/api/console/findings");
  if (loading && !value) return <Loading />;
  if (error && !value) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  return (
    <>
      <PageHead
        overline="Research"
        title="Findings"
        subtitle="Every finding across arenas. Open one to see the claim, how to reproduce it and its evidence. The validator's verdict and your decision are kept apart; yours wins."
        observed={value.observed_at}
        action={null}
        refresh={refresh}
      />
      <FindingList
        findings={value.findings}
        showArena
        arenaHref={(finding) =>
          finding.arena_known && finding.arena_id
            ? `/console/arena/${encodeURIComponent(finding.arena_id)}?tab=findings&finding=${encodeURIComponent(finding.id)}`
            : null
        }
        actions={(finding) =>
          finding.arena_known && finding.arena_id ? (
            finding.manual_verdict ? (
              <span className="muted">
                You {finding.manual_verdict} this finding.
              </span>
            ) : (
              <span className="muted">
                Confirm or refute it in its arena, next to its evidence review.
              </span>
            )
          ) : (
            <span className="muted">
              The arena record was removed; the finding stays readable.
            </span>
          )
        }
      />
    </>
  );
}
