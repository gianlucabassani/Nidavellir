#!/usr/bin/env bash
# Shared by deployment entrypoints; never source .env as executable shell code.
set -euo pipefail
umask 077
ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"
DRY_RUN=${DRY_RUN:-false}
COMPOSE=(docker compose --project-name nidavellir --env-file "$ROOT/.env" -f "$ROOT/docker-compose.yml" -f "$ROOT/docker-compose.prod.yml" --profile postgres --profile agent-gateway)
# Used by entrypoints that source this library.
# shellcheck disable=SC2034
APP=(webui agent-gateway beat worker orchestrator)
# shellcheck disable=SC2034
SERVICES=(postgres redis orchestrator worker beat webui agent-gateway poc-runner-image)
show() { printf '+ '; printf '%q ' "$@"; printf '\n'; }
run() { show "$@"; if [[ $DRY_RUN != true ]]; then "$@"; fi; }
quiet() {
    show "$@"
    if [[ $DRY_RUN != true ]]; then
        if ! "$@" >>"$LOG" 2>&1; then
            echo "Command failed; protected diagnostic log: $LOG" >&2
            return 1
        fi
    fi
}
preflight() {
    [[ -f .env ]] || { echo 'Missing .env' >&2; return 1; }
    # Compose parses dotenv; only metadata is printed, never rendered config.
    "${COMPOSE[@]}" config --format json 2>/dev/null | python3 -c '
import base64,json,sys
from urllib.parse import urlsplit, unquote
c=json.load(sys.stdin); s=c["services"]
e=s["orchestrator"]["environment"]; w=s["webui"]["environment"]
values={"NIDAVELLIR_API_KEY":e["BOOTSTRAP_API_KEY"],"WEBUI_PASSWORD":w["WEBUI_PASSWORD"],"SECRET_KEY":w["SECRET_KEY"],"SECRETS_ENCRYPTION_KEY":e["SECRETS_ENCRYPTION_KEY"],"POSTGRES_PASSWORD":s["postgres"]["environment"]["POSTGRES_PASSWORD"]}
for k,v in values.items():
    if not v or len(v)<16 or v in ("dev-insecure-key","nidavellir-dev-only"):
        sys.exit("Missing/weak production secret: "+k)
    print(k+"=…"+v[-4:])
try:
    if len(base64.urlsafe_b64decode(values["SECRETS_ENCRYPTION_KEY"]))!=32: raise ValueError()
except ValueError:
    sys.exit("SECRETS_ENCRYPTION_KEY must be a Fernet key")
u=urlsplit(e["DATABASE_URL"])
if (u.scheme,u.hostname,u.port,u.username,u.path)!=("postgresql+psycopg","postgres",5432,"nidavellir","/nidavellir") or unquote(u.password or "")!=values["POSTGRES_PASSWORD"]:
    sys.exit("DATABASE_URL must match production PostgreSQL credentials")
for name,service in s.items():
    for p in service.get("ports",[]):
        if p.get("host_ip")!="127.0.0.1": sys.exit("Non-loopback publication: "+name)
if s["redis"].get("ports"): sys.exit("Redis must be unpublished")
' || { echo 'Production configuration refused (values suppressed).' >&2; return 1; }
}
lock_deployment() {
    exec 9>"$ROOT/.git/nidavellir-deploy.lock"
    flock -n 9 || { echo 'Another deploy/backup holds the lock' >&2; exit 1; }
}
