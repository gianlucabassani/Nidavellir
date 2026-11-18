#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=scripts/deployment-common.sh
source "$HERE/deployment-common.sh"
REF=''
for arg in "$@"; do
    case $arg in
        --dry-run) DRY_RUN=true ;;
        -*) echo 'Usage: deploy.sh [--dry-run] <ref>' >&2; exit 2 ;;
        *) [[ -z $REF ]] || exit 2; REF=$arg ;;
    esac
done
[[ -n $REF ]] || { echo 'Usage: deploy.sh [--dry-run] <ref>' >&2; exit 2; }
[[ -z $(git status --porcelain --untracked-files=all) ]] || { echo 'Dirty tree: abort (including dry-run)' >&2; exit 1; }
PREVIOUS=$(git rev-parse HEAD)
TARGET=$(git rev-parse --verify --end-of-options "$REF^{commit}")
# Never fetch: the operator must review and fetch the tag beforehand.
git cat-file -e "$TARGET:docker-compose.prod.yml"
git cat-file -e "$TARGET:scripts/deploy.sh"
preflight
if [[ $DRY_RUN != true ]]; then lock_deployment; fi
STAMP=$(date -u +%Y%m%dT%H%M%S)-$$
LOG=/tmp/nidavellir-deploy-$STAMP.log
BACKUP=''
SWITCHED=false
TOUCHED=false
STATUS=failed
smoke() {
    quiet "${COMPOSE[@]}" exec -T orchestrator python -c 'import os,urllib.request; r=urllib.request.Request("http://localhost:8000/deployments",headers={"X-API-Key":os.environ["BOOTSTRAP_API_KEY"]}); urllib.request.urlopen(r,timeout=10).read()' || return 1
    quiet curl --fail --silent --output /dev/null --max-time 10 http://127.0.0.1:5000/login || return 1
    quiet "${COMPOSE[@]}" exec -T agent-gateway python -c 'import urllib.request,urllib.error; r=urllib.request.Request("http://localhost:9000/mcp",headers={"Accept":"text/event-stream"});
try: urllib.request.urlopen(r,timeout=10).close()
except urllib.error.HTTPError as e:
 if e.code not in (400,406): raise'
}
if [[ $DRY_RUN == true ]]; then
    echo "+ tag previous service images nidavellir-rollback/<service>:$STAMP and pin those tags in a private rollback overlay"
    echo "# Existing installation backup branch:"
    env NIDAVELLIR_BACKUP_LEAVE_STOPPED=1 bash "$HERE/backup.sh" --dry-run
    show git checkout --detach "$TARGET"
    show make release-check
    show "${COMPOSE[@]}" build
    show "${COMPOSE[@]}" up -d --wait --wait-timeout 180 "${SERVICES[@]}"
    smoke
    echo '# On failure, recovery branch:'
    show "${COMPOSE[@]}" stop "${APP[@]}"
    show git checkout --detach "$PREVIOUS"
    show env NIDAVELLIR_DEPLOY_LOCKED=1 NIDAVELLIR_BACKUP_LEAVE_STOPPED=1 bash '<snapshot>/backup.sh' --restore '<completed-backup>'
    show "${COMPOSE[@]}" -f '<saved-images.json>' up -d --no-build --pull never --wait --wait-timeout 180 "${SERVICES[@]}"
    smoke
    echo "+ write deployments/$STAMP.json (mode 600)"
    printf '{"schema":"nidavellir-deployment/v1","sha":"%s","previous_sha":"%s","timestamp":"<UTC>","status":"success|rolled_back|rollback_failed|failed","backup":"<path-or-null>","images":{"orchestrator":{"image_id":"sha256:<local-content-digest>","repo_digests":["<registry-digest-if-available>"]}}}\n' "$TARGET" "$PREVIOUS"
    exit 0
fi
touch "$LOG"
SNAPSHOT=$(mktemp -d /tmp/nidavellir-deploy.XXXXXX)
cp "$HERE/backup.sh" "$HERE/deployment-common.sh" "$HERE/deployment-state.py" "$SNAPSHOT/"
OLD_CONTAINERS=$("${COMPOSE[@]}" ps -aq)
OLD_IDS=()
if [[ -n $OLD_CONTAINERS ]]; then mapfile -t OLD_IDS <<< "$OLD_CONTAINERS"; fi
# Fails closed before anything is touched (no trap yet): no rollback, no deploy.
NIDAVELLIR_ROLLBACK_STAMP=$STAMP python3 "$SNAPSHOT/deployment-state.py" snapshot "$SNAPSHOT/images.json" "${OLD_IDS[@]}"
echo "Rollback images: $SNAPSHOT/images.json" >>"$LOG"

rollback() {
    quiet "${COMPOSE[@]}" stop "${APP[@]}" || return 1
    quiet git checkout --detach "$PREVIOUS" || return 1
    if [[ -n $BACKUP ]]; then
        quiet env NIDAVELLIR_DEPLOY_LOCKED=1 NIDAVELLIR_BACKUP_LEAVE_STOPPED=1 bash "$SNAPSHOT/backup.sh" --restore "$BACKUP" || return 1
    fi
    if ((${#OLD_IDS[@]})); then
        quiet "${COMPOSE[@]}" -f "$SNAPSHOT/images.json" up -d --no-build --pull never --wait --wait-timeout 180 "${SERVICES[@]}" || return 1
        smoke || return 1
    fi
}
finish() {
    local rc=$?
    trap - EXIT INT TERM
    set +e
    if ((rc != 0)); then
        if [[ $TOUCHED == true ]]; then
            if rollback; then
                STATUS=rolled_back
            else
                STATUS=rollback_failed
                quiet "${COMPOSE[@]}" stop "${APP[@]}" || true
            fi
        elif [[ $SWITCHED == true ]]; then
            quiet git checkout --detach "$PREVIOUS"
        fi
    fi
    mkdir -p deployments
    mapfile -t IDS < <("${COMPOSE[@]}" ps -aq)
    python3 "$SNAPSHOT/deployment-state.py" manifest "deployments/$STAMP.json" "$TARGET" "$PREVIOUS" "$STATUS" "$BACKUP" "${IDS[@]}" || rc=1
    if [[ $STATUS == success ]]; then
        # Retention never changes the deploy status or exit code.
        quiet python3 "$SNAPSHOT/deployment-state.py" prune-rollback 3 || echo 'Rollback tag retention failed (ignored).' >&2
    fi
    echo "Deployment status: $STATUS; receipt: deployments/$STAMP.json; private log: $LOG"
    exit "$rc"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if ! RUNNING_POSTGRES=$("${COMPOSE[@]}" ps --status running -q postgres); then
    echo 'Unable to determine PostgreSQL status; abort without changing it.' >&2
    exit 1
fi
if [[ -n $RUNNING_POSTGRES ]]; then
    TOUCHED=true
    quiet env NIDAVELLIR_DEPLOY_LOCKED=1 NIDAVELLIR_BACKUP_LEAVE_STOPPED=1 bash "$SNAPSHOT/backup.sh"
    # backup output is private, but its non-secret path is needed for recovery.
    BACKUP=$(sed -n 's/^Backup directory: //p' "$LOG" | tail -1)
    [[ -n $BACKUP && -f $BACKUP/complete ]]
elif ((${#OLD_IDS[@]})); then
    echo 'Existing stack has no running PostgreSQL; abort without changing it.' >&2
    exit 1
fi
quiet git checkout --detach "$TARGET"
SWITCHED=true
preflight
quiet make release-check
quiet "${COMPOSE[@]}" build
TOUCHED=true
quiet "${COMPOSE[@]}" up -d --wait --wait-timeout 180 "${SERVICES[@]}"
smoke
STATUS=success
