# NV-09 synthetic workflow assessment — 2026-09-27

The first live manifest is `nv09-live-2026-09-27-aed88ffd.json`; the final
post-change gate is `nv09-live-2026-09-27-b97417df.json` (the previous final
manifest was `nv09-live-2026-09-27-b17ac7a2.json`). The gate uses a
real client-rendered synthetic SPA, two test accounts, one B-owned object,
browser views for A and B, an A-to-B HTTP comparison, independent target-local
effect and healthy-control probes, and replacement trial arenas for reset.
Three matched pairs showed a verified regression only when the cross-account
path changed from `/objects/B` to `/protected/B`; no pair failed because of
infrastructure. The final gate recorded six trial verdicts (three confirmed,
three refuted), a -1 verified difference for the SPA challenge, a 24.85-second
setup stage and zero labelled residual resources. All results are public
calibration evidence.

Setup effort is recorded as elapsed seconds in each manifest's `setup` field.
The operator runs one command, `make verify-nv09-live`; the script builds the
fixture, starts an isolated stack, registers the challenge and builds, executes
the trials, checks evidence after teardown, and counts residual labelled
resources. It reuses the NV-02 replacement reset, NV-06 authorization validator,
NV-07 paired records, and scoped MCP browser/HTTP tools. The new work is the SPA,
the BH-13/NV-09 manifest contract and the isolated gate.

**Operator decision based on the stated product focus:** retain this as a
regression harness for Nidavellir's future testing and research on self-hosted
or open-source products. The synthetic result establishes useful harness
plumbing, but does not yet justify a maintained adapter in Bughunt's read-only
repository or show improvement in its live agentic workflow. Bughunt's
deterministic enumeration, baseline, worker and backup pipelines stay outside
this integration. NV-09 remains open for an actual agentic-client handoff and
an operator workflow measurement; no live campaign identity or capture was used.
