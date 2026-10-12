# Historical research evidence reconciliation

The current record supersedes the following unsupported claims. Old artifacts and
journal entries remain unchanged so their original assertions stay inspectable.

| Historical claim | Accepted status |
|---|---|
| Nine initial endpoint refutations | Unverified: no retained per-probe requests, responses or controls. They are not evidence-backed refutations. |
| Two fixture builds proved deterministic IDs and state | Unverified: the retained historical manifest establishes one build and seven status controls only. |
| October release totals 977/981, 991/995, 1002/1006 | Unverified historical counts; no corresponding raw gate logs were located in the retained verification records. |
| Roughly fourfold efficiency gain | Withdrawn: the manual 600-line/10-call baseline was hardcoded. The retained six calls and 416 output lines do not establish comparative savings. |
| Paperless fix-derived search was exhausted | Withdrawn: syntactic candidates and manual-review residuals do not establish vulnerability absence. |

The 2026-10-07 audit already identified these gaps. This reconciliation makes their
status explicit and removes the fabricated comparison baseline from future
`accept-research-code.py` output. No historical result is certified by today's run.

Fresh baseline: [registered live probe](paperless-quality-baseline-2026-10-11.json),
registration commit `41918e0`. Its recorded refutation labels reproduce the old
classifier behavior, including M4's failed owner control; they are not accepted
authorization conclusions. Fresh inventory and later live gates are separately
dated and retain their own immutable source identities.
