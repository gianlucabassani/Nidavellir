# Configuration lineage — independent review and fixes

An independent fresh-context reviewer read the complete feature against the
approved design and plan, including committed core logic, the worktree changes,
new modules/tests and live harness. Review was read-only. It found no Critical
issue and no confirmed raw-secret/HMAC disclosure. Its initial verdict was
not ready to merge, with Important findings below.

| Finding | Correction and verification |
|---|---|
| Layer-level coverage hid a required key's missing observation | Coverage is checked per key/layer. `test_required_runtime_observation_is_checked_per_key` failed then passed. |
| Different control plans could yield `proven` | Matched control-plan digests are required, in addition to validator/probe identities. `test_different_control_plans_cannot_prove_introduction` failed then passed. |
| Teardown skipped a fresh integrity check | New analysis cannot claim fresh replay integrity after teardown. Stored completed analysis remains readable. The reviewer reproduced the corrected downgrade. |
| Docker `Config.Env` was promoted to active configuration | Environment facts are incomplete supplied inputs. Opt-in `runtime_readback` uses a fixed size/time-bounded observer and target-specific reviewed semantics. Runtime adapter regressions failed then passed. |
| Setup provenance adapter was missing | Successful labelled steps in a finished session link to trusted active readback; command text/output is never parsed. `test_setup_provenance_requires_approved_success_and_active_readback` failed then passed; live setup provenance passed. |
| Agent projection lacked the enabling delta | Projection now includes snapshot identities, nonsecret before/after values, source classes/references and explicit completeness. REST regression failed then passed; real MCP and retained agent reads passed. |
| Conservative live acceptance and cleanup assertion were absent | Expanded gate covers simultaneous changes, failed controls, unresolved image refusal, conflicting/missing readbacks, omitted history and target mutation. Residual inventory is asserted empty. Final report: `configuration-lineage-live-2026-10-25-3750717d.json`. |

The implementer also verified fail-closed handling for unknown sensitivity and
profile deployment without record encryption, and added regression coverage.
These changes do not grant new participant privileges. Analysis creation and
capture remain operator-only; publication is explicit and limited to research
or discovery sessions. Evaluation truth remains private.

The reviewer declined to independently rerun the entire release gate, assess
unfinished closure prose, or certify harness changes made during review. Those
are covered by the implementer's final verification records, not attributed to
the reviewer. No second independent review was performed after the fix pass.
There were no reported deferred Minor findings.

Implementation rulings: use a separate REST adapter module; keep work isolated
from the dirty main checkout; use the pinned Docker verifier for focused tests;
group persistence/capture integration where their interfaces depend on one
another; require successful reset receipts; use active readback instead of
claiming environment consumption; run conservative arenas sequentially to avoid
host subnet exhaustion. Console work remains after UI-R4.
