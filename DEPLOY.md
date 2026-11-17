# Deploying Nidavellir

This describes a single-host production deployment on `<deploy-host>`, a Linux
machine you control, using the scripts in `scripts/`. Running them is an explicit
operator action; nothing deploys automatically. Docker-local remains the supported
provider (ADR-0003); this adds no cloud support.

## Prepare a release on your workstation

Review and commit the deployment files along with the intended application version.
Leave unrelated work out of the release. Run the pinned gate and tag a clean commit:

```bash
make release-check
git status --short
git tag -a vX.Y.Z -m 'Nidavellir vX.Y.Z'
git push origin vX.Y.Z
```

Do not move a published tag. The deployment script resolves a local ref to its
commit SHA once, does not fetch, and checks out that SHA detached. Dirty tracked
files and untracked files both abort, including during dry-run. Ignored `.env`,
data directories and `deployments/` do not dirty a release checkout. Review ignored
build inputs too; a clean Git status alone cannot attest the Docker build context.

## Prepare the deploy host (operator only)

Reference host: a recent Linux distribution with ~8 GiB RAM (plus swap), Docker and
Compose v2. Require Bash, Git, Python 3, make, curl, gzip, tar, util-linux `flock`,
ripgrep, and **Compose 2.24.4 or newer** (`!override`/`!reset` support). The
production overlay expects an existing reverse proxy (Traefik v2) on an external
Docker network named `proxy`, with `exposedByDefault=false`, Host routers, and no
ACME. Verify that network exists; the scripts never create, remove or reconfigure
Traefik or any unrelated containers.

Use one fixed checkout path, `<repo-path>`: persistent bind mounts are relative to
it, so do not move it between releases. The Compose project is
always `nidavellir`; base container names are retained. Do not run another copy
of this production project on the same daemon. Use the local Docker daemon and
verify `docker context show` / `DOCKER_HOST` before any real execution.

Create `.env` from `.env.example`, `chmod 600 .env`, and set:

- `MOCK_MODE=false`, `RANGE_PROVIDER=docker-local`.
- Distinct random `NIDAVELLIR_API_KEY`, `WEBUI_PASSWORD`, `SECRET_KEY`, and
  `POSTGRES_PASSWORD` (at least 16 characters; `openssl rand -hex 32` works).
- `SECRETS_ENCRYPTION_KEY`: a valid Fernet key. Keep it in offline secure storage.
- `DATABASE_URL=postgresql+psycopg://nidavellir:<pw>@postgres:5432/nidavellir`.
  Use the same password, URL-encoded if needed. Hex avoids encoding ambiguity.

The gateway overrides the base demo key with an empty default. For a fixed agent
principal set `NIDAVELLIR_AGENT_KEY` to a separately created role-agent key; use the
existing scoped gateway/session workflow for research. Do not put the admin key
in an in-arena agent. Production preflight refuses missing/weak core secrets,
invalid Fernet keys, mismatched database credentials and non-loopback publications.
Scripts parse `.env` through Compose and never execute it. Avoid exported overrides
for those settings: Compose gives shell environment values precedence over `.env`.
The console prints only the last four characters of the five secrets; config,
command output and diagnostics go to private mode-600 logs under `/tmp`.
Do not use `bash -x`, `docker compose config` without `--quiet`, or share those logs.

The overlay leaves `docker-compose.yml` untouched. PostgreSQL uses the
`postgres-data` volume; `./data`, `./runs`, `./keys`, `./traces` stay persistent bind
mounts (paths shared with the recovery workflow). Redis and Terraform
cache volumes retain their base definitions. Keep enough disk for backups and
builds. Service memory ceilings total 4.375 GiB, including the one-shot runner;
worker concurrency is one. These are ceilings, not reservations: target arenas,
builds and any other containers on the host need additional headroom. Capacity on
a given host is not verified by this repository.

## Deploy a tag

On `<deploy-host>`, after fetching and reviewing the tag, from the clean checkout:

```bash
cd <repo-path>
git fetch origin tag vX.Y.Z
./scripts/deploy.sh --dry-run vX.Y.Z
./scripts/deploy.sh vX.Y.Z
```

The tooling must already be installed in the current ref and the target ref.
It locks concurrent deployment/backup operations, saves existing container image
IDs, backs up a running PostgreSQL installation, checks out the target, runs
`make release-check`, builds, applies database migrations, and starts the declared
services with `up -d --wait --wait-timeout 180`. PostgreSQL and Redis have health
checks; the API and WebUI have health checks. Smoke checks require authenticated API
`/deployments`, WebUI `/login`, and a responding MCP `/mcp` transport. The MCP probe
accepts the protocol's GET errors 400/406; it does not prove an arena session.
The one-shot runner's successful exit is expected.

Deployments take downtime: application services remain stopped from the backup
through build and validation. Schedule maintenance, stop active research and drain
work first; live arena processes and Redis queues are not included in the snapshot.
An existing stack with stopped PostgreSQL aborts. A first installation has no
predecessor backup. The release gate uses its separate `nidavellir-verify` project;
do not run another release gate concurrently. No `compose down`, prune, or
`--remove-orphans` is used against the production project.

A successful or failed attempt after deployment setup writes a private atomic
`deployments/<UTC>-<pid>.json` receipt, ignored by Git:

```json
{
  "schema": "nidavellir-deployment/v1",
  "timestamp": "2026-11-03T12:00:00+00:00",
  "sha": "<attempted-commit>",
  "previous_sha": "<previous-commit>",
  "status": "success",
  "backup": "<backup-dir>/<UTC>-<pid>",
  "images": {
    "orchestrator": {
      "image_id": "sha256:<immutable-local-image-id>",
      "repo_digests": []
    }
  }
}
```

Locally built images normally have no registry digest; their content-addressed
image IDs are recorded instead. Failure receipts describe images present after
recovery and retain the attempted SHA; inspect `status` and `previous_sha` together.
Preflight refusals do not write receipts.

## Exposure and trust

Only `127.0.0.1:5000`, `127.0.0.1:8000`, and `127.0.0.1:9001` (container 9000)
are published. PostgreSQL and Redis publish no host ports. Only WebUI joins
`proxy`, labelled for `Host(nidavellir.local)` and upstream port 5000. Traefik
provides an additional HTTP route through its own listeners: loopback publication
does **not** restrict that route to a private network. Restrict Traefik access
using the host's access policy (for example a VPN/overlay network or firewall).
No TLS or ACME is configured here. Clients resolve `nidavellir.local` to
`<deploy-host-ip>` (hosts file or private DNS). API/MCP can use SSH loopback
forwarding.

The orchestrator and worker mount `/var/run/docker.sock`. They have effectively
root-level authority over the entire Docker host, including every other container
on it. Arena network isolation does not remove that blast radius. Treat the
operator UI/API and approved images/source builds as privileged access; use only
trusted operators and authorized targets. The scripts scope their own operations
to Nidavellir but cannot sandbox a compromised Docker client or application.
A dedicated host (or VM) for Nidavellir is strongly recommended.

## Backups and restore

```bash
./scripts/backup.sh --dry-run
./scripts/backup.sh
```

Backups live under `<backup-dir>` (`${NIDAVELLIR_BACKUP_DIR:-$HOME/.local/share/nidavellir/backups}/<UTC>-<pid>/`
for the user running the script), mode 700 with private files. Applications stop;
PostgreSQL stays available. `pg_dump --clean --if-exists
--no-owner --no-acl` is gzipped to `database.sql.gz`; `files.tar.gz` includes `.env`
and all existing data/runs/keys/traces directories. The file archive is made by a
one-off container of the installed API image (`compose run --rm --no-deps`, root, the
checkout mounted read-only), because the services write files under those directories
as root that the host user cannot read. Ownership is recorded in the archive. The dump is restored with
`ON_ERROR_STOP` into a uniquely named scratch database on the same PostgreSQL
service, then dropped. Only verified sets receive a `complete` marker. Keep the
newest 14 complete sets; incomplete attempts stay for diagnosis and need manual
cleanup. Standalone backup restarts application containers afterward. A failed
scratch restore is a failed backup, never a completed set.

These backups contain plaintext secrets and sensitive research evidence; store
additional encrypted/off-host copies under your normal backup policy. They do not
include image bytes, Docker volumes for target arenas, Redis queues, or host data
outside the listed directories. No automatic timer is installed.

Restore during an explicit maintenance window, from a trusted complete backup:

```bash
./scripts/backup.sh --dry-run --restore <backup-dir>/<UTC>-<pid>
./scripts/backup.sh --restore <backup-dir>/<UTC>-<pid>
```

Restore first revalidates the gzip dump and tar archive and restores the selected
dump into a scratch database. Files are extracted by the same kind of one-off
container, so root-owned files are replaced and keep their ownership. Only then it **drops and recreates the Nidavellir database**, extracts persistent files
and `.env`, and restarts applications on success. Failed destructive restore leaves
applications stopped. Keep database passwords and Fernet keys stable across a
release/rollback; credential rotation is a separate maintenance operation. Restore
overlays files, so files newly created after the snapshot are retained. For an exact
off-host disaster recovery use fresh empty bind directories and the matching code
and images; see also the encrypted recovery workflow in `docs/OPERATIONS.md`.

## Rollback

Any upgrade failure after stopping applications triggers automatic recovery:
checkout the previous SHA, restore the completed backup if available, and start
with the saved immutable image IDs (including the worker's runtime PoC runner) using `--no-build --pull never`. It repeats
health wait and smoke. The deploy command still exits nonzero; receipt status is
`rolled_back`, `rollback_failed` or `failed`. On a first install it stops new
application services and returns to the previous ref; PostgreSQL/Redis and their
volumes remain for diagnosis. Failures before service changes restore the ref
without disrupting the running stack. Do not prune saved images during deployment.

If automatic rollback fails, leave applications stopped, read the private log and
restore the receipt's backup with the previous release and matching image IDs.
For a planned code downgrade use `./scripts/deploy.sh <previous-tag>`: this makes a
fresh backup but does not rewind data. Schema compatibility is not assumed.
Never fix rollback by deleting shared Docker resources.

## Local verification

```bash
shellcheck scripts/deploy.sh scripts/backup.sh scripts/deployment-common.sh
python3 -m unittest tests/test_deployment_tooling.py -v
make release-check
```

The tooling tests use real Compose rendering and disposable Git commits/tag
`v-test`, with a fake Docker daemon/commands to inject failed upgrades and verify
ref, image and database-restore command paths. They exercise the shell scripts,
including clean-tree refusal, dry-run side effects, repeat deployment and failed
backup cleanup. They do not certify a full production deployment.

`scenarios/opencms-22-whitebox.yaml` is an explicit importable v3 scenario, not an
automatically installed template. Import it through the existing scenario API/UI.
It uses OpenCms 22.0, MariaDB 11 at node name `mysql`, and whitebox source pinned
to the upstream `build_22_0_0` commit `5aca15b30ba098beacfd622262e40dce3c7456af`.
See the [upstream release](https://github.com/alkacon/opencms-core/releases/tag/build_22_0_0)
and [image configuration](https://hub.docker.com/r/alkacon/opencms-docker).
Native startup is explicit. Arena-only fixture passwords are public, isolated test
credentials. Image tags remain mutable; resolve image digests through target intake
before evidence-bearing runs. **Known runtime blocker:** Docker-local names containers with an arena prefix and
currently does not assign node-name DNS aliases. `DB_HOST=mysql` therefore needs
an operator-assigned `mysql` alias on the database's arena network before the CMS
can connect. The imported scenario alone does not establish database connectivity.
With the exact database container, segment network and victim container taken
from that arena's outputs, the operator can reattach only that database container:

```bash
docker network disconnect <arena-segment-network> <arena-mysql-container>
docker network connect --alias mysql <arena-segment-network> <arena-mysql-container>
docker restart <arena-victim-container>
```

Do this only for the disposable arena, after MariaDB is ready. A reset/redeploy
needs the alias reapplied. A general node-alias provider change is outside this
task's no-app-logic boundary. Database readiness/startup and the full OpenCms arena
have not been live-verified by deployment-tooling checks.
