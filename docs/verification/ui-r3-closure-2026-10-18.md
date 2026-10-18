# UI-R3 request comparison — 2026-10-18

The operator separately approved the bounded UI-R3 design before implementation,
then requested only features useful to a researcher or agent. UI-R2 remains the
control/evidence review slice; source browsing is the later UI-R4 slice.

## Delivered behavior

The existing HTTP ledger supports **Duplicate and edit**, Set A/Set B, and side-by-side
request/response comparison. Duplication prepares an editor without sending anything.
An explicit replay can change node, object/path, method, query, body and safe headers.
Selected headers from another authorized stored transaction can replace account
credentials server-side. The browser sends a source digest and header names rather
than exporting the stored values. Replay creates a new immutable transaction linked
to its parent and uses the existing confined execution, lifecycle, stop and budget path.
Query replacement, empty-body clearing and case-insensitive header replacement work.

Comparison shows status, response size, original body digest, bounded body previews,
body diff and a projected response-header diff. Body previews are 8,192 characters per
side; body and header diffs are each limited to 16,384 characters. Request bodies keep
the existing request bound. Truncation, unknown capture completeness, absent bodies
and clipping remain explicit. Equality refers to captured body text, not proof about
uncaptured bytes. Differences are observations, never an automatic vulnerability
verdict; controls and effects remain independently reviewed in UI-R2.

Operator-only immutable named pairs retain A/B labels, notes and both digests in the
existing event store. Saving again creates a new snapshot; history is cursor-paged.
Reopening restores the pair and notes, and both references can enter the existing
finding form. Groups do not automatically duplicate request bodies or credentials.
The authenticated original transactions remain linked. No new credential vault,
batch execution, mutable multi-tab workspace or source browser was added.

The read-only attacker MCP tool `compare_http_transactions` uses the same projection
and consumes no action or gateway step. Agents need the existing arena binding and
may access only their own captures. A successful exact-digest action receipt preserves
ownership when content deduplication retains a different first manifest actor. Raw
reads, replay parents and selected credential sources share that boundary. Operators
retain their existing permissions. Session/CSRF rules protect console mutations;
operator notes are filtered from agent events. Comparison and saved-group reads work
after teardown without target execution.

## Active verification

The final [live report](ui-r3-live-2026-10-18-48ef5c41.json) records a real Docker-local
NV-06 synthetic two-account calibration, pinned by fixture image ID. The real
[browser journey](ui-r3-live-2026-10-18-48ef5c41.json.browser.json) proved:

- Duplicate did not send. An explicit object change from A's owned object to B's
  protected object returned 403; the named A/B pair and notes were saved.
- Reusing the stored B authorization header server-side returned 200 on B's object.
  Both browser replay payloads contained no synthetic account token values.
- Reload restored pair labels and notes; both digests populated the finding form;
  both protected original links returned 200. Two immutable groups were retained.
- The real MCP client listed and called comparison after a scoped replay, observing
  the owned 200 and foreign-object 403. Gateway traces contained metadata rather
  than account tokens or private response bodies.
- Agent access to operator-private comparison/groups returned 403; wrong-arena
  access returned 404. Comparison left the explicitly capped budget unchanged.
- Stopping the arena made replay return 423. Both comparison projections and group
  records were identical after destruction. The [retained browser check](ui-r3-live-2026-10-18-48ef5c41.json.retained-browser.json)
  reopened saved evidence and both protected links without sending requests.

Both browser phases recorded zero page errors and no page overflow at 320, 390 and
1440 px. Screenshots beside their JSON reports retain the rendered console; this is
focused browser verification, not a full accessibility certification. An earlier
October 18 [passed run](ui-r3-live-2026-10-18-56a8c67a.json) preceded only the reviewed
response-size wording correction. The `48ef5c41` run verifies the final UI build.
Each report records zero labelled arena containers, networks, volumes and images.
The [cleanup log](ui-r3-stack-cleanup-2026-10-18.log) records removal of the isolated
service stack, four volumes, network and four dedicated service image tags. Shared
base/fixture images were retained. Task-generated ignored browser configs were removed.
Checked-in reports and screenshots remain available after stack cleanup.

Three failed October 16 attempts remain labelled and retained, not counted as passes:
`3731bbac` exposed asynchronous duplicate-editor preparation/label lookup;
`055ef157` exposed a populated notes-field lookup failure; `d18f3fd2` passed the
active browser flow but stopped at an AnyIO harness call error before MCP acceptance.
The ready-state UI and explicit accessible labels were fixed, and the harness now
passes the callable to `anyio.run`. Every failed report records zero arena resources.

## Release and review

The final [release log](ui-r3-final-release-2026-10-18.log) is an exit-zero
`make release-check` on pinned Python 3.11.14: Ruff passed, Bandit reported no
issues, SQLite had **1,137 passed / four skipped / six deselected**, PostgreSQL had
**1,141 passed / six deselected**. Clean migrations and API/UI/gateway smoke passed.
The earlier [release run](ui-r3-release-2026-10-18.log) passed before the byte-label
correction; final acceptance uses the final log. [Frontend checks](ui-r3-frontend-2026-10-18.log)
passed TypeScript, Prettier and production build. Text logs trim terminal trailing
spaces; `.log.gz` siblings preserve the original bytes losslessly.

Eleven new focused service tests cover limits, missing evidence, secret-safe header
projection, teardown, immutable group pagination, actor/arena boundaries, ownership
under deduplication, private replay parents, safe validation errors, credential reuse,
query/body clearing and header casing. Gateway and BFF regressions cover read-only
comparison, incomplete identity-switch refusal, stance, session, CSRF and outage.
[Independent review](ui-r3-review-2026-10-18.md) found four important issues during
iteration; all were fixed and re-reviewed. The fresh final review found no remaining
important defects, and its minor size-label finding was corrected.

[Registration preservation](ui-r3-registration-preservation-2026-10-18.json) confirms
all four registered executable source hashes and ancestry of `b059439`. Historical
Paperless artifacts and conclusions remain unchanged.

## Limits and next TODO

This is public calibration workflow evidence, not a new vulnerability or held-out
agent capability result. Docker-local remains the only live-verified provider.
Header projection omits unknown headers and cookie Domain/Path/expiry; cookie values
and redirect credentials/query values/fragments are withheld. Authorized raw evidence
remains linked; arbitrary target content in bodies/paths/query is not a general
secret-redaction guarantee. Capture/preview/diff limits stay explicit. Notes are
immutable snapshots; source semantics and earlier historical proof gaps remain open.

Next: **UI-R4 source candidate review**. Confirm its bounded design and concrete
acceptance around immutable refs, complete counts, paged residuals, classification
reasons, affected/fixed links and unresolved semantics before implementation.
