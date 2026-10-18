# Research usability — delivered slice and next proposals

UI-R2's first slice was approved and completed on 2026-10-16. Its operator-only
control/evidence review and real Docker-local two-account acceptance are recorded in
[the closure report](../verification/ui-r2-closure-2026-10-16.md). It supports existing
structured validators; it does not import arbitrary standalone probe JSON. The second slice, UI-R3, was separately approved and delivered on 2026-10-18; see
[its closure report](../verification/ui-r3-closure-2026-10-18.md). UI-R4 remains a
proposal. Keep source authoring
operator-only and arena execution confined and budgeted.

| Order | Observed friction | Proposed change | Acceptance |
|---|---|---|---|
| 1 | Valid controls and exploit effects were easy to confuse in raw probe JSON. | Show each hypothesis with its actor request, prerequisite controls, effect observations, verdict and linked evidence. Give unresolved results a clear label. | A real two-account test can be reviewed from the console; a failed positive control cannot appear as a refutation; evidence survives teardown. |
| 2 | Comparing owned/foreign requests required editing standalone scripts. | Extend existing replay with named request groups, duplicate requests, A/B response comparison and short notes. Keep credentials in existing secret storage. | An operator duplicates an owned request, changes the object/account, compares results and saves evidence without exporting credentials. |
| 3 | Source searches required manual pagination and an external evidence script. | Add an operator source-review view: immutable ref, full candidate counts, paged residuals, classification reasons and affected/fixed patch links. | Every retained site is reachable; incomplete scans and unresolved semantics stay visible; reopening a session preserves review state. |

The first two address the most costly mistakes observed in the live Paperless
round. The third makes the new inventory usable without treating syntax as proof.
The first slice was proved on the existing NV-06 Docker-local two-account
calibration target. It does not replace or rerun the registered Paperless conclusions.

Product inspiration is limited to interaction patterns. Burp Repeater supports
named/grouped request tabs and grouped execution
([official documentation](https://portswigger.net/burp/documentation/desktop/tools/repeater/managing-tabs)).
Caido Replay retains request/response pairs for comparison
([official documentation](https://docs.caido.io/app/quickstart/replay)).
Neither is evidence that a proposed Nidavellir feature is implemented or secure.

Before implementing UI-R4: approve that slice’s design and record its scoped
acceptance test. The separately approved UI-R3 design uses two existing transactions,
explicit single-request replay, server-side reuse of selected stored headers, bounded
response comparison and immutable named pairs with notes. Its Docker-local acceptance
duplicates an owned request, changes object/account, saves and reopens evidence before
and after teardown, and exercises the read-only MCP comparison. No batch sending,
new credential vault, source browser or general workspace editor is included.
Provider expansion and repository
history cleanup remain outside this proposal.
