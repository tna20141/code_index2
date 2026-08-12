#!/usr/bin/env bash
# Migrate local code_index2 state to prod: Mongo data (dump -> scp -> restore in the container) AND the FAISS
# search indexes (on-disk files -> rsync to the prod app dir). Skips the `projects` collection by default
# (seed it by hand on prod -- root_path differs).
#
# Dry run (default -- dumps to temp locally, prints the FAISS files, does NOT scp/restore/rsync):
#   scripts/migrate_to_prod.sh
# Apply:
#   scripts/migrate_to_prod.sh --apply
# Apply, REPLACING prod collections (drops each restored collection first -> prod == local, no E11000 dup-key
# skips; the excluded `projects` collection is NOT dropped, so a hand-seeded prod project row survives):
#   scripts/migrate_to_prod.sh --apply --drop
#
# Prod mongo credentials come from deploy/.env.mongo (MONGO_ROOT_USER / MONGO_ROOT_PASSWORD).
# Set REMOTE_APP_DIR to where code_index2 lives ON THE VPS (so FAISS indexes land at <app>/data/indexes/).
# Override defaults via env, e.g.:
#   SSH_HOST=wicom-old REMOTE_APP_DIR=/home/ubuntu/code_index2 EXCLUDE=projects,query_view_cache \
#     scripts/migrate_to_prod.sh --apply
#
# Requires: mongodump + rsync locally; docker + the mongo container on the prod host; deploy/.env.mongo filled.

set -euo pipefail

# --- config (override via env) ---
SSH_HOST="${SSH_HOST:-wicom-old}"                       # ssh alias / user@host
CONTAINER="${CONTAINER:-code-index-mongo}"              # mongo container name on prod
DB="${DB:-code_index2}"
LOCAL_URI="${LOCAL_URI:-mongodb://localhost:27017}"     # local mongo (no auth)
EXCLUDE="${EXCLUDE:-projects}"                          # collection(s) to skip (comma-separated)
REMOTE_TMP="${REMOTE_TMP:-/tmp}"
REMOTE_APP_DIR="${REMOTE_APP_DIR:-/home/ubuntu/code_index2}"   # code_index2 root ON THE VPS
FAISS_DIR="${FAISS_DIR:-./data/indexes}"               # local FAISS dir (matches settings.faiss_index_dir)

# prod mongo credentials from deploy/.env.mongo (the same file that provisioned the prod container).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_MONGO="${ENV_MONGO:-${SCRIPT_DIR}/../deploy/.env.mongo}"
if [[ -f "$ENV_MONGO" ]]; then
  set -a; source "$ENV_MONGO"; set +a
fi
MONGO_USER="${MONGO_ROOT_USER:-codeindex}"
MONGO_PASS="${MONGO_ROOT_PASSWORD:-}"

APPLY=false
DROP=false
for arg in "$@"; do
  [[ "$arg" == "--apply" ]] && APPLY=true
  [[ "$arg" == "--drop" ]] && DROP=true
done

ARCHIVE="/tmp/${DB}_$(date +%Y%m%d_%H%M%S).archive"
REMOTE_ARCHIVE="${REMOTE_TMP}/$(basename "$ARCHIVE")"
REMOTE_FAISS_DIR="${REMOTE_APP_DIR}/data/indexes"

# build --excludeCollection flags
EXCLUDE_ARGS=()
IFS=',' read -ra COLLS <<< "$EXCLUDE"
for c in "${COLLS[@]}"; do
  [[ -n "$c" ]] && EXCLUDE_ARGS+=(--excludeCollection="$c")
done

echo "=== code_index2 -> prod migration ==="
echo "  local db       : $DB @ $LOCAL_URI"
echo "  excluding      : $EXCLUDE"
echo "  ssh host       : $SSH_HOST"
echo "  container      : $CONTAINER (db $DB)"
echo "  local archive  : $ARCHIVE"
echo "  local faiss    : $FAISS_DIR"
echo "  remote faiss   : ${SSH_HOST}:${REMOTE_FAISS_DIR}"
echo "  restore mode   : $([[ $DROP == true ]] && echo 'DROP (replace collections; projects untouched)' || echo 'insert (skips existing _id -> E11000)')"
echo "  mode           : $([[ $APPLY == true ]] && echo APPLY || echo 'DRY RUN')"
echo

# --- 1. dump Mongo locally (always -- harmless, lets you inspect even on a dry run) ---
echo "[1/4] dumping Mongo locally..."
mongodump --uri="$LOCAL_URI" --db="$DB" "${EXCLUDE_ARGS[@]}" --archive="$ARCHIVE"
echo "      wrote $(du -h "$ARCHIVE" | cut -f1) -> $ARCHIVE"

# --- 2. show the FAISS files that would sync ---
echo "[2/4] FAISS indexes to sync:"
if [[ -d "$FAISS_DIR" ]]; then
  find "$FAISS_DIR" -type f | sed 's/^/        /'
else
  echo "        (none -- $FAISS_DIR does not exist; skipping FAISS sync)"
fi

if [[ $APPLY != true ]]; then
  echo
  echo "DRY RUN: stopping before scp/restore/rsync. Re-run with --apply to push to prod."
  echo "(local archive kept at $ARCHIVE for inspection)"
  exit 0
fi

if [[ -z "$MONGO_PASS" ]]; then
  echo "ERROR: no mongo password. Set MONGO_ROOT_PASSWORD in $ENV_MONGO (copy from .env.mongo.example)." >&2
  exit 1
fi

# --- 3. Mongo: scp archive -> into container -> restore ---
echo "[3/4] copying + restoring Mongo into $CONTAINER..."
scp "$ARCHIVE" "${SSH_HOST}:${REMOTE_ARCHIVE}"
ssh "$SSH_HOST" "docker cp '${REMOTE_ARCHIVE}' '${CONTAINER}:${REMOTE_ARCHIVE}'"
# --drop drops each collection in the archive before restoring it (prod ends up == local dump; no E11000
# dup-key skips). It only drops collections IN THE ARCHIVE, so the excluded `projects` row is NOT touched.
DROP_ARG=""; [[ $DROP == true ]] && DROP_ARG="--drop"
ssh "$SSH_HOST" "docker exec -i '${CONTAINER}' mongorestore ${DROP_ARG} \
  --uri='mongodb://${MONGO_USER}:${MONGO_PASS}@localhost:27017/?authSource=admin' \
  --archive='${REMOTE_ARCHIVE}'"
ssh "$SSH_HOST" "rm -f '${REMOTE_ARCHIVE}'" || true

# --- 4. FAISS: rsync the on-disk index files to the prod app dir ---
if [[ -d "$FAISS_DIR" ]]; then
  echo "[4/4] syncing FAISS indexes -> ${SSH_HOST}:${REMOTE_FAISS_DIR}/ ..."
  ssh "$SSH_HOST" "mkdir -p '${REMOTE_FAISS_DIR}'"
  # trailing slash on the source copies the CONTENTS of data/indexes/ into the remote data/indexes/.
  rsync -az --delete "${FAISS_DIR%/}/" "${SSH_HOST}:${REMOTE_FAISS_DIR}/"
else
  echo "[4/4] no local FAISS dir ($FAISS_DIR) -- skipping."
fi

echo
echo "DONE. Mongo restored (excluding: $EXCLUDE); FAISS indexes synced."
echo "NEXT on prod:"
echo "  - seed the projects row by hand (root_path = the repo path ON the VPS)."
echo "  - run: cd code_index2 && uv run python scripts/sanity_check.py"
