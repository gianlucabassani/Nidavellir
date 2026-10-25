# Configuration lineage calibration

Build from the repository root with
`docker build -f cyber-range/fixtures/config-lineage/Dockerfile -t nidavellir/config-lineage:acceptance .`.

The pinned NV-06 seed and target-local observer are reused. `DISABLE_AUTH=false`
denies A's `/objects/B` request; `true` discloses it. Owner control remains valid.
`SIGNING_SECRET` is an inert synthetic sensitive value used only to test redaction.
No new-vulnerability or held-out capability claim is made.

`make verify-configuration-lineage-live` deploys secure, misconfigured and unrelated
later states through an isolated service stack, resets the secure/misconfigured
states, captures runtime inputs, submits actual agent requests, independently
validates effects and compares retained snapshots through REST/MCP.
