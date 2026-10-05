# Console topology and navigation review — 2026-09-30

The opt-in `/console` remains in mock development mode. The Cyber Range now uses a scenario catalog beside a larger topology work surface, with running arenas below the catalog. The arena overview shows attacker and target stations connected through declared network segments. These connections describe recipe membership, not verified reachability. Destroyed arenas label their stations as archived.

Shared Targets, Agents, Evidence and Activity links are in the command bar on desktop and its Tools menu at narrower widths. Profile contains Profile, Platform settings and Log out. Day colors use warm stone, brass and royal navy; the royal blue night mode remains available.

## Renders

- [Research, day](../assets/ui-concepts/renders/forge-research-day-2026-09-30.png)
- [Benchmark, day](../assets/ui-concepts/renders/forge-benchmark-day-2026-09-30.png)
- [Cyber Range, day](../assets/ui-concepts/renders/forge-cyber-range-day-2026-09-30.png)
- [Arena, day](../assets/ui-concepts/renders/forge-arena-day-2026-09-30.png)
- [Arena, night](../assets/ui-concepts/renders/forge-arena-night-2026-09-30.png)
- [Arena, phone](../assets/ui-concepts/renders/forge-arena-mobile-2026-09-30.png)

## Verification and limits

`npm run check`, `npm run build` and `make release-check` passed. The pinned gate reported 964 SQLite tests passed, 4 skipped and 6 deselected, then 968 PostgreSQL tests passed and 6 deselected. Chromium found zero JavaScript errors and no document width overflow on Research, Benchmark, Cyber Range and Arena at 390 and 320 px. Desktop captures showed no document width overflow. The BFF topology tests check that only visible nodes and their declared segments reach the browser, with no private recipe fields; a destroyed arena must report archived node state.

The renders use existing mock data, including an archived arena. They do not demonstrate a live Docker-local launch, reachability, manual accessibility, or researcher usability. UI-R1 remains open, and the new console is not the default experience.
