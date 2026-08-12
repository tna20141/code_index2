#!/usr/bin/env bash
# Migrate the local code_index2 Mongo data to the prod container: dump locally -> scp -> restore in the
# container over SSH. Skips the `projects` collection by default (seed it by hand on prod -- root_path differs).
#
# Dry run (default -- prints what it would do, dumps to temp but does NOT scp/restore):
#   scripts/migrate_to_prod.sh
# Apply (actually scp + restore on prod):
#   scripts/migrate_to_prod.sh --apply
#
# Prod mongo credentials are read from deploy/.env.mongo (MONGO_ROOT_USER / MONGO_ROOT_PASSWORD).
# Override other defaults via env vars, e.g.:
#   SSH_HOST=wicom-old CONTAINER=code-index-mongo EXCLUDE=projects,query_view_cache scripts/migrate_to_prod.sh --apply
#
# Requires: mongodump (mongodb-database-tools) locally; docker + the mongo container on the prod host;
# deploy/.env.mongo present (copied from .env.mongo.example and filled).

set -euo pipefail

# --- config (override via env) ---
SSH_HOST="${SSH_HOST:-wicom-old}"                       # ssh alias / user@host
CONTAINER="${CONTAINER:-code-index-mongo}"              # mongo container name on prod
DB="${DB:-code_index2}"
LOCAL_URI="${LOCAL_URI:-mongodb://localhost:27017}"     # local mongo (no auth)
EXCLUDE="${EXCLUDE:-projects}"                          # collection(s) to skip (comma-separated)
REMOTE_TMP="${REMOTE_TMP:-/tmp}"

# prod mongo credentials come from deploy/.env.mongo (the same file that provisioned the prod container --
# vars MONGO_ROOT_USER / MONGO_ROOT_PASSWORD; see deploy/.env.mongo.example for the format).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_MONGO="${ENV_MONGO:-${SCRIPT_DIR}/../deploy/.env.mongo}"
if [[ -f "$ENV_MONGO" ]]; then
  set -a; source "$ENV_MONGO"; set +a
fi
MONGO_USER="${MONGO_ROOT_USER:-codeindex}"
MONGO_PASS="${MONGO_ROOT_PASSWORD:-}"

APPLY=false
[[ "${1:-}" == "--apply" ]] && APPLY=true

ARCHIVE="/tmp/${DB}_$(date +%Y%m%d_%H%M%S).archive"
REMOTE_ARCHIVE="${REMOTE_TMP}/$(basename "$ARCHIVE")"

# build --excludeCollection flags
EXCLUDE_ARGS=()
IFS=',' read -ra COLLS <<< "$EXCLUDE"
for c in "${COLLS[@]}"; do
  [[ -n "$c" ]] && EXCLUDE_ARGS+=(--excludeCollection="$c")
done

echo "=== code_index2 -> prod migration ==="
echo "  local db      : $DB @ $LOCAL_URI"
echo "  excluding     : $EXCLUDE"
echo "  ssh host      : $SSH_HOST"
echo "  container     : $CONTAINER (db $DB)"
echo "  local archive : $ARCHIVE"
echo "  mode          : $([[ $APPLY == true ]] && echo APPLY || echo 'DRY RUN')"
echo

# --- 1. dump locally (always -- harmless, lets you inspect even on a dry run) ---
echo "[1/3] dumping locally..."
mongodump --uri="$LOCAL_URI" --db="$DB" "${EXCLUDE_ARGS[@]}" --archive="$ARCHIVE"
echo "      wrote $(du -h "$ARCHIVE" | cut -f1) -> $ARCHIVE"

if [[ $APPLY != true ]]; then
  echo
  echo "DRY RUN: stopping before scp/restore. Re-run with --apply to push to prod."
  echo "(local archive kept at $ARCHIVE for inspection)"
  exit 0
fi

if [[ -z "$MONGO_PASS" ]]; then
  echo "ERROR: no mongo password. Set MONGO_ROOT_PASSWORD in $ENV_MONGO (copy from .env.mongo.example)." >&2
  exit 1
fi

# --- 2. scp to prod + into the container ---
echo "[2/3] copying to $SSH_HOST..."
scp "$ARCHIVE" "${SSH_HOST}:${REMOTE_ARCHIVE}"
ssh "$SSH_HOST" "docker cp '${REMOTE_ARCHIVE}' '${CONTAINER}:${REMOTE_ARCHIVE}'"

# --- 3. restore inside the container ---
echo "[3/3] restoring into $CONTAINER..."
ssh "$SSH_HOST" "docker exec -i '${CONTAINER}' mongorestore \
  --uri='mongodb://${MONGO_USER}:${MONGO_PASS}@localhost:27017/?authSource=admin' \
  --archive='${REMOTE_ARCHIVE}'"

# cleanup the remote host-side temp (leave the in-container copy; it's tmp)
ssh "$SSH_HOST" "rm -f '${REMOTE_ARCHIVE}'" || true

echo
echo "DONE. Restored (excluding: $EXCLUDE)."
echo "NEXT on prod:"
echo "  - seed the projects row by hand (root_path = the repo path ON the VPS)."
echo "  - run: cd code_index2 && uv run python scripts/sanity_check.py"
