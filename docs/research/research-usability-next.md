# Research usability — next proposal

UI-R2's first slice is drafted for approval after the quality gate. These are proposed features, not
completed work. Extend the existing console and service contracts; keep source
authoring operator-only and arena execution confined and budgeted.

| Order | Observed friction | Proposed change | Acceptance |
|---|---|---|---|
| 1 | Valid controls and exploit effects were easy to confuse in raw probe JSON. | Show each hypothesis with its actor request, prerequisite controls, effect observations, verdict and linked evidence. Give unresolved results a clear label. | A real two-account test can be reviewed from the console; a failed positive control cannot appear as a refutation; evidence survives teardown. |
| 2 | Comparing owned/foreign requests required editing standalone scripts. | Extend existing replay with named request groups, duplicate requests, A/B response comparison and short notes. Keep credentials in existing secret storage. | An operator duplicates an owned request, changes the object/account, compares results and saves evidence without exporting credentials. |
| 3 | Source searches required manual pagination and an external evidence script. | Add an operator source-review view: immutable ref, full candidate counts, paged residuals, classification reasons and affected/fixed patch links. | Every retained site is reachable; incomplete scans and unresolved semantics stay visible; reopening a session preserves review state. |

The first two address the most costly mistakes observed in the live Paperless
round. The third makes the new inventory usable without treating syntax as proof.
Start with one small console slice and prove it against the same Docker-local
target before adding a wider toolkit.

Product inspiration is limited to interaction patterns. Burp Repeater supports
named/grouped request tabs and grouped execution
([official documentation](https://portswigger.net/burp/documentation/desktop/tools/repeater/managing-tabs)).
Caido Replay retains request/response pairs for comparison
([official documentation](https://docs.caido.io/app/quickstart/replay)).
Neither is evidence that a proposed Nidavellir feature is implemented or secure.

Before implementation: approve the first slice, confirm its place in TODO.md,
and record a scoped design and acceptance test. Provider expansion and repository
history cleanup remain outside this proposal.
