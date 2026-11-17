# WebUI — operator console

**Scope:** the GUI-first operator surface for Nidavellir. It is server-rendered
Flask + Jinja, one tokenized CSS system, and vanilla JavaScript with no required
frontend build step.

**Responsibility:** make every normal operator workflow complete in the browser
while presenting and driving the orchestrator/service APIs. The WebUI owns
navigation, forms, progressive disclosure, visualization, and interaction state.

**Excluded:** business rules, provider/infra execution, durable benchmark
scheduling, scoring authority, agent-gateway policy, and primary authentication
authority. Those remain backend responsibilities.

Architecture decision: [`../../docs/adr/0012-gui-first-product-model.md`](../../docs/adr/0012-gui-first-product-model.md).

## Current implementation

| Route | Current page | Reality |
|---|---|---|
| `/` | Dashboard | Real: fleet stats, capacity, recent activity |
| `/arenas` | Arenas | Real: active and archived deployments |
| `/engagements/new` | New engagement | Real first C2 slice: purpose/source selection and validated-builder handoff |
| `/launch` | Launch | Real: predefined, custom, generated and imported scenarios |
| `/wizard` | SUT wizard | Real: Git/OCI/bundle intake, consent, review, launch |
| `/arena/<id>` | Arena detail | Real: topology, setup, bindings, findings, score, changes, activity, destroy |
| `/scenarios` | Inventory | Real: scenario registry and catalog |
| `/agents` | Live agent attribution | Real: bindings/connections, usage and event-derived activity |
| `/audit` | Logs | Real: attributed append-only audit feed |
| `/settings` | Settings | Real but limited: model connection, local preferences, access posture |
| `/profile` | Profile | Real but limited |

The first C1 shell slice is live. Canonical target-language aliases are
`/engagements`, `/library/challenges`, `/activity/agents`, `/activity/audit`, and
`/administration/settings`; the original paths continue to render the same
workflows. Foundation routes for Evaluations, Targets, agent builds, Findings,
Evidence, Providers, and Security state their current boundary and point back to
the available workflow rather than presenting placeholder data as real.

These pages remain supported until their replacement workflow reaches feature
parity. Do not remove or silently strand a current action during migration.

## Target information architecture

```text
Home

Engagements
  Active
  History
  New engagement

Evaluations
  Suites
  Runs
  Comparisons
  New evaluation

Library
  Challenges
  Targets
  Agents

Activity
  Findings
  Evidence
  Audit trail

Administration
  Providers & capacity
  Security
  Settings
```

`Launch`, `SUT`, and `Inventory` are implementation-era concepts and do not
remain top-level destinations. A global Create action starts an Engagement,
Evaluation, Challenge, Target, or Agent workflow.

## Existing-to-target mapping

| Existing function | New home |
|---|---|
| Fleet dashboard | Home, redesigned after the object pages exist |
| Arena fleet/archive | Engagements; evaluation-owned arenas appear under Runs |
| Launch + SUT wizard | Create → New engagement |
| Scenario registry/catalog | Library → Challenges |
| Git/OCI/bundle intake | Library → Targets and the engagement wizard |
| Agent bindings/connections | Engagement/Run → Agent tab |
| Agent versions/connectors | Library → Agents (new registry) |
| Global logs | Activity → Audit trail |
| Findings, artifacts and changes | Activity indexes plus contextual workspace tabs |
| Provider status/capacity | Administration |

Compatibility route aliases are acceptable during the transition. Navigation
labels and breadcrumbs should use the target product language even where a
legacy route still serves the page.

## Unified creation model

### New engagement

1. Purpose: calibration, benchmark, discovery, or manual research.
2. Challenge or ad-hoc target.
3. Immutable target identity and black/white-box visibility.
4. Human/agent participants and stance.
5. Setup mode, egress, time box, and explicit consent.
6. Tools, containment, and limits.
7. Monitoring/scoring policy.
8. Review and launch.

The wizard reuses current backend endpoints and validation. Advanced fields are
shown only when relevant. Generated infrastructure never auto-deploys; autonomous
configuration retains the platform+per-engagement double lock.

### New evaluation

1. Baseline/candidate agent builds.
2. Challenge suite.
3. Trials, seeds, visibility, and reset policy.
4. Budgets, timeouts, and containment.
5. Immutable experiment review.
6. Launch and live progress.

## Engagement/run workspace

The current arena detail page is decomposed into one contextual shell:

```text
Overview · Live · Target · Findings · Evidence · Changes
Agent · Trace · Score · Infrastructure
```

- Render only applicable tabs.
- Setup is a lifecycle phase in Overview/Live, not a permanent competing card.
- Keep the primary action/status visible while details move behind tabs.
- Destroyed arenas become read-only records; evidence and trace remain accessible.
- Use SSE for live state/events/actions/findings/budgets; retire five-second polling.
- Global Activity items deep-link back to the correct tab and entity.

## Shared console patterns

The C1 shell uses a small set of native, reusable patterns rather than adding a
frontend framework:

- `.page-head` with `.head-actions` for page identity and primary actions;
- `.toolbar` for filter/search controls, with `toolbar--spacious` as its only
  spacing modifier;
- `.card`, `.table`, `.badge`, and `.empty` for content, state, and no-data
  presentation;
- native `details`/`summary` controls for grouped navigation and global Create;
- one 1000px compact-navigation boundary shared by CSS and JavaScript.

The sidebar toggle declares its controlled element and expanded state. Compact
navigation closes through link activation, its dismissal layer, or Escape.
Live-browser checks at desktop, compact, and phone widths remain part of the C1
completion gate.

## Migration increments

1. **Prototype and route map — first slice shipped:** complete feature inventory,
   target routes, and honest foundation screens; live visual QA remains.
2. **Application shell — in progress:** grouped sidebar, global Create,
   target-language breadcrumbs, shared toolbars, and responsive/keyboard shell
   behavior are live. Finish live-browser visual verification and final review.
3. **Engagement creation — complete:** `/engagements/new` captures purpose,
   participant mode, enforced runtime limit, and challenge/target source before
   composing the existing builders. Purpose
   and policy are validated and stored as append-only intent across deployment
   paths; the time box sets deployment expiry.
   Generated/imported challenges return to the builder with intent and selection
   preserved rather than ending the creation journey in the library.
   Review surfaces visibility, containment, binding/stance, and automatic
   monitoring/scoring authority without exposing unenforced toggles.
4. **Workspace:** move arena-detail capabilities tab by tab and add SSE.
5. **Activity and Home:** add global indexes; redesign Home from real objects.
6. **Evaluation workbench:** agent registry, suites, trials, runs, comparisons.

## Acceptance rules

- Every current operator action is present or intentionally deprecated with a
  documented replacement.
- Normal workflows require no terminal/CLI.
- No business rule is implemented only in Flask/Jinja/JavaScript.
- Destructive, autonomous, and egress-changing actions retain review/consent.
- Pages remain responsive and keyboard-operable.
- UI tests cover route access, proxy behavior, state/error/empty cases, and
  destructive confirmations; the live Docker product path is visually verified.
