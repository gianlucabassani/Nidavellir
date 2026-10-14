# Royal Command review renders

Royal Command is the approved direction and the default React console at
`/console`. Legacy routes remain available as a tested fallback.
Most renders below use fixture or mock data. Rows marked “live” were captured
from the packaged React app during isolated Docker-local browser journeys;
see the [verification record](../../verification/ui-research-benchmark-live-2026-09-29.md).

| Window | Render |
|---|---|
| Research, day | [View render](renders/royal-command-research-day.png) |
| Research, night | [View render](renders/royal-command-research-night.png) |
| Research Git intake | [View render](renders/royal-command-research-intake.png) |
| Research OCI intake | [View render](renders/royal-command-oci-intake.png) |
| Research source bundle intake | [View render](renders/royal-command-bundle-intake.png) |
| Research source bundle intake, phone | [View render](renders/royal-command-bundle-intake-mobile.png) |
| Research archived finding, live | [View render](renders/royal-command-research-archive-live.png) |
| Benchmark | [View render](renders/royal-command-benchmark.png) |
| Benchmark result, live | [View render](renders/royal-command-benchmark-live.png) |
| Benchmark result, live phone | [View render](renders/royal-command-benchmark-live-mobile.png) |
| Cyber Range | [View render](renders/royal-command-cyber-range.png) |
| Scenario library | [View render](renders/royal-command-scenario-library.png) |
| Scenario import and topology review | [View render](renders/royal-command-scenario-import.png) |
| Scenario import, phone | [View render](renders/royal-command-scenario-import-mobile.png) |
| Arena workspace | [View render](renders/royal-command-arena.png) |
| Docker-local arena workspace | [View render](renders/royal-command-docker-local-arena.png) |
| Arena setup workspace | [View render](renders/royal-command-setup.png) |
| Arena agent access | [View render](renders/royal-command-agent-access.png) |
| Arena infrastructure and source diff | [View render](renders/royal-command-infrastructure.png) |
| HTTP research workspace | [View render](renders/royal-command-http.png) |
| Isolated browser workspace | [View render](renders/royal-command-browser.png) |
| Foothold file transfer | [View render](renders/royal-command-transfer.png) |
| Confined PoC workspace | [View render](renders/royal-command-poc.png) |
| Findings workspace | [View render](renders/royal-command-findings.png) |
| Evidence workspace | [View render](renders/royal-command-evidence.png) |
| Finding confirmation | [View render](renders/royal-command-finding-confirm.png) |
| New arena | [View render](renders/royal-command-new-arena.png) |
| New comparison | [View render](renders/royal-command-new-comparison.png) |
| Benchmark registry, builds | [View render](renders/royal-command-registry-builds.png) |
| Benchmark registry, suite on phone | [View render](renders/royal-command-registry-suites-mobile.png) |
| Evaluation result | [View render](renders/royal-command-evaluation.png) |
| Evaluation trial progress | [View render](renders/royal-command-evaluation-progress.png) |
| Evaluation infrastructure failure, phone | [View render](renders/royal-command-evaluation-failure-mobile.png) |
| Stop confirmation, mobile | [View render](renders/royal-command-stop-dialog-mobile.png) |
| Destroy confirmation | [View render](renders/royal-command-destroy-dialog.png) |
| Shared activity | [View render](renders/royal-command-activity.png) |
| Shared agents | [View render](renders/royal-command-agents.png) |
| Shared targets | [View render](renders/royal-command-targets.png) |
| Platform settings | [View render](renders/royal-command-settings.png) |
| Operator profile | [View render](renders/royal-command-profile.png) |

The three scenario renders above were captured against a local `MOCK_MODE`
development stack. The Docker-local arena render is from an isolated live
fixture; it shows the arena before its HTTP and finding steps. The evaluation
progress and failure renders use intercepted local fixture responses. Other
renders use local fixture records. The mock and fixture renders show visual
states only. The live
journey and its limits are recorded in
[the verification note](../../verification/ui-docker-local-2026-09-29.md).

The [interactive Royal Command prototype](royal-dashboards.html) still shows
additional planned workspace states. It uses demonstration data and does not
submit to the backend. The [earlier concepts](research.html) are retained only
as rejected comparison material.

The console migration is complete through UI-R1. Current behavior and its
verification boundary are recorded in [the route/action matrix](../../UI_ROUTE_ACTION_MATRIX.md),
[the closure report](../../verification/ui-r1-closure-2026-10-08.md), and
[ADR-0017](../../adr/0017-react-operator-console-rendering.md).
The [dated legacy console reference](../legacy-console-reference/2026-09-28/MANIFEST.md)
preserves the earlier layout. Rejected charcoal renders and the rejected
foundations smoke script remain reference material only.
