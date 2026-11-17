#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=scripts/deployment-common.sh
source "$HERE/deployment-common.sh"
RESTORE=''
while (($#)); do
    case $1 in
        --dry-run) DRY_RUN=true ;;
        --restore) RESTORE=${2:?Backup directory required}; shift ;;
        *) echo 'Usage: backup.sh [--dry-run] [--restore DIRECTORY]' >&2; exit 2 ;;
    esac
    shift
done
preflight
if [[ $DRY_RUN != true && ${NIDAVELLIR_DEPLOY_LOCKED:-} != 1 ]]; then lock_deployment; fi
BASE=${NIDAVELLIR_BACKUP_DIR:-$HOME/.local/share/nidavellir/backups}
STAMP=$(date -u +%Y%m%dT%H%M%S)-$$
DEST=$BASE/$STAMP
LOG=${LOG:-/tmp/nidavellir-backup-$STAMP.log}
if [[ $DRY_RUN != true ]]; then touch "$LOG"; fi
restore_dump() {
    local file=$1 database=$2
    printf '+ gzip -dc %q | ' "$file"
    printf '%q ' "${COMPOSE[@]}" exec -T postgres psql -X -v ON_ERROR_STOP=1 -U nidavellir -d "$database"
    printf '\n'
    if [[ $DRY_RUN != true ]]; then
        gzip -dc "$file" | "${COMPOSE[@]}" exec -T postgres psql -X -v ON_ERROR_STOP=1 -U nidavellir -d "$database" >>"$LOG" 2>&1
    fi
}
# The services run as root and write under data/, runs/, keys/ and traces/, so the
# host user often cannot read those files, or replace them on restore. Archive and
# extract inside a one-off container of the installed API image instead: it runs as
# root, starts no dependency and sees the checkout only through the mount named here.
# Ownership is recorded in the archive and restored with it.
files_container() {
    local mount=$1; shift
    "${COMPOSE[@]}" run --rm --no-deps -T -v "$mount" --entrypoint tar orchestrator "$@"
}
archive_files() {
    local target=$1; shift
    printf '+ '
    printf '%q ' "${COMPOSE[@]}" run --rm --no-deps -T -v "$ROOT:/backup-src:ro" --entrypoint tar orchestrator -czf - -C /backup-src "$@"
    printf '> %q\n' "$target"
    if [[ $DRY_RUN != true ]]; then
        if ! files_container "$ROOT:/backup-src:ro" -czf - -C /backup-src "$@" >"$target" 2>>"$LOG"; then
            echo "File archive failed; protected diagnostic log: $LOG" >&2
            return 1
        fi
        # An archive that cannot be listed is not a backup.
        tar -tzf "$target" >/dev/null 2>>"$LOG" || { echo "File archive unreadable; protected diagnostic log: $LOG" >&2; return 1; }
    fi
}
extract_files() {
    local source=$1
    printf '+ '
    printf '%q ' "${COMPOSE[@]}" run --rm --no-deps -T -v "$ROOT:/backup-dst" --entrypoint tar orchestrator -xzf - -C /backup-dst
    printf '< %q\n' "$source"
    if [[ $DRY_RUN != true ]]; then
        if ! files_container "$ROOT:/backup-dst" -xzf - -C /backup-dst <"$source" >>"$LOG" 2>&1; then
            echo "File restore failed; protected diagnostic log: $LOG" >&2
            return 1
        fi
    fi
}
SCRATCH=nidavellir_restore_$$
STOPPED=false
RESTORE_STARTED=false
cleanup() {
    local rc=$?
    trap - EXIT
    show "${COMPOSE[@]}" exec -T postgres dropdb -U nidavellir --if-exists "$SCRATCH"
    if [[ $STOPPED == true && ${NIDAVELLIR_BACKUP_LEAVE_STOPPED:-} != 1 && ( $RESTORE_STARTED == false || $rc == 0 ) ]]; then show "${COMPOSE[@]}" start "${APP[@]}"; fi
    if [[ $DRY_RUN != true ]]; then
        "${COMPOSE[@]}" exec -T postgres dropdb -U nidavellir --if-exists "$SCRATCH" >>"$LOG" 2>&1 || rc=1
        if [[ $STOPPED == true && ${NIDAVELLIR_BACKUP_LEAVE_STOPPED:-} != 1 && ( $RESTORE_STARTED == false || $rc == 0 ) ]]; then
            "${COMPOSE[@]}" start "${APP[@]}" >>"$LOG" 2>&1 || rc=1
        fi
    fi
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
STOPPED=true
quiet "${COMPOSE[@]}" stop "${APP[@]}"
if [[ -n $RESTORE ]]; then
    [[ -f $RESTORE/complete && -f $RESTORE/database.sql.gz && -f $RESTORE/files.tar.gz ]] || { echo 'Incomplete backup' >&2; exit 1; }
    # Validate the selected bytes now, before destroying the current database.
    quiet gzip -t "$RESTORE/database.sql.gz"
    quiet tar -tzf "$RESTORE/files.tar.gz"
    quiet "${COMPOSE[@]}" exec -T postgres createdb -U nidavellir "$SCRATCH"
    restore_dump "$RESTORE/database.sql.gz" "$SCRATCH"
    RESTORE_STARTED=true
    quiet "${COMPOSE[@]}" exec -T postgres dropdb -U nidavellir --force nidavellir
    quiet "${COMPOSE[@]}" exec -T postgres createdb -U nidavellir nidavellir
    restore_dump "$RESTORE/database.sql.gz" "nidavellir"
    extract_files "$RESTORE/files.tar.gz"
else
    run mkdir -p "$DEST"
    printf '+ '
    printf '%q ' "${COMPOSE[@]}" exec -T postgres pg_dump -U nidavellir --clean --if-exists --no-owner --no-acl nidavellir
    printf '| gzip > %q\n' "$DEST/database.sql.gz"
    if [[ $DRY_RUN != true ]]; then
        "${COMPOSE[@]}" exec -T postgres pg_dump -U nidavellir --clean --if-exists --no-owner --no-acl nidavellir 2>>"$LOG" | gzip >"$DEST/database.sql.gz"
    fi
    FILES=(.env)
    for path in data runs keys traces; do [[ ! -d $path ]] || FILES+=("$path"); done
    archive_files "$DEST/files.tar.gz" "${FILES[@]}"
    quiet "${COMPOSE[@]}" exec -T postgres createdb -U nidavellir "$SCRATCH"
    restore_dump "$DEST/database.sql.gz" "$SCRATCH"
    if [[ $DRY_RUN != true ]]; then
        touch "$DEST/complete"
        # Delete only complete backup sets created by this script, newest 14 kept.
        python3 - "$BASE" <<'PY'
import pathlib,re,shutil,sys
sets=sorted((p for p in pathlib.Path(sys.argv[1]).iterdir() if re.fullmatch(r"\d{8}T\d{6}-\d+",p.name) and (p/"complete").is_file()),reverse=True)
for p in sets[14:]: shutil.rmtree(p)
PY
    else
        echo '+ mark complete; retain newest 14 complete timestamped backup directories'
    fi
    echo "Backup directory: $DEST"
fi
