# Arena Forge prototype — first approval checkpoint

## Researcher proportions revision

The second revision reduces repeated context: the four arena status cards become one wrapping summary row, the extra workbench banner is removed, the topology uses a compact minimum height, and desktop station buttons are omitted when selectable graph stations are present. Phone station buttons remain. The inspector prioritizes the station, network and service count; provider and declared browser support are available through Station details. HTTP, Browser and PoC are compact workbench links below the canvas. Findings and Evidence share one record row. Planned Fuzz controls are omitted from this operational preview. Reset and Destroy are inside Arena actions, while Stop/Resume stays visible when applicable; all keep the existing confirmation dialog.

- [Revised day](../assets/ui-concepts/renders/forge-researcher-day-2026-09-30.png)
- [Revised night](../assets/ui-concepts/renders/forge-researcher-night-2026-09-30.png)
- [Revised phone](../assets/ui-concepts/renders/forge-researcher-mobile-2026-09-30.png)
- [Revised interaction recording](../assets/ui-concepts/renders/forge-researcher-interaction-2026-09-30.webm)

The revision passed TypeScript, Prettier, Vite, pointer and keyboard selection, trace expansion, reduced motion, and station selection/no document overflow at 1024, 760, 390 and 320 px. The archived mock record still limits what these captures demonstrate. Researcher review and wider rollout remain pending operator approval.

The release gate was rerun after the revision and passed its SQLite/PostgreSQL suites, Ruff, source-only Bandit and smoke; PostgreSQL reported 968 passed and 6 deselected.

The prototype is available on the existing development console at:

`http://localhost:5000/console/arena/7b2b268a-1a09-4cc3-aa71-f733e73450bc?tab=forge`

Use the **Forge preview** tab on any arena to inspect its own record. The current overview and other workspaces remain available while this composition is reviewed. This checkpoint is the operator's requested approval boundary before continuing the rest of the UI.

## Observable result

The topology, station inspector, tool strip, evidence summary and collapsible trace share one contiguous work surface. Station selection updates the inspector with a short transition and highlights the selected station. SVG stations support Enter and Space, and explicit station buttons provide an alternative on phones. Hover, focus, selection and trace transitions respect reduced motion. Network lines show recipe membership without traffic animation or claims of observed reachability. The original anvil emblem appears in the workbench header.

- [Day render](../assets/ui-concepts/renders/forge-prototype-day-2026-09-30.png)
- [Night render](../assets/ui-concepts/renders/forge-prototype-night-2026-09-30.png)
- [Phone render](../assets/ui-concepts/renders/forge-prototype-mobile-2026-09-30.png)
- [Expanded trace](../assets/ui-concepts/renders/forge-prototype-trace-2026-09-30.png)
- [Interaction recording](../assets/ui-concepts/renders/forge-prototype-interaction-2026-09-30.webm)

## Verification and limits

TypeScript, Prettier, production Vite build and `git diff --check` passed. Chromium verified keyboard and pointer selection, trace expansion, station selection at 1024, 760, 390 and 320 px, no document overflow at those widths, no JavaScript exceptions on the desktop interaction path, and disabled inspector animation under reduced motion.

The final pinned `make release-check` passed Ruff, source-only Bandit, 964 SQLite tests (4 skipped, 6 deselected), 968 PostgreSQL tests (6 deselected), and migration/API/UI/gateway smoke.

The captured record is an archived mock arena. Live lifecycle actions still use the existing parent confirmation dialog and service routes, but were not exercised in this visual checkpoint. Tools open their existing workbenches; station selection does not silently assign or authorize a tool target. This prototype does not close UI-R1 or establish production readiness. Wider rollout awaits the operator's visual approval.
