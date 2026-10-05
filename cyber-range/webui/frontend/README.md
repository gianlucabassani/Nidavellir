# Nidavellir operator console

Royal Command is the selected React/TypeScript/Vite surface. The built assets
are served by Flask at `/console`; `/console/arena/<id>` opens the new arena
overview with stop/resume for the research gate. `/console/evaluations/new` starts a matched comparison and
`/console/evaluations/<id>` opens paired results. The default
route and all legacy task routes remain available while
the parity matrix is completed.

From this directory:

```sh
npm ci
npm run build
```

The build writes self-hosted assets to `../static/console/`. The WebUI Docker
image reproduces the build from the pinned lockfile. For local development,
run the Flask WebUI as usual after building; the Vite dev server is not yet
wired into Flask session and CSRF handling.

The shell reads narrow same-origin `/api/console/*` projections. Research
creation/tools, build/challenge/suite registration and Cyber Range lifecycle actions
currently open existing Flask pages. Fuzzing is a disabled planned control.
The day/night preference is the only console value stored in the browser.
