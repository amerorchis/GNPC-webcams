#!/usr/bin/env bash
#
# Update the production checkout on the Pi to the commit that just passed CI.
#
# Run by .github/workflows/ci.yml on the self-hosted runner. The runner checks
# the repo out into its own work directory, so $PWD here is *not* the
# production checkout — everything below operates on $DEPLOY_PATH.

set -euo pipefail

DEPLOY_PATH="${DEPLOY_PATH:-$HOME/Modules/GNPC-webcams}"
UV="${UV:-$HOME/.local/bin/uv}"
LOCK_WAIT="${LOCK_WAIT:-180}"

log() { printf '==> %s\n' "$*"; }

cd "$DEPLOY_PATH"

# Cron starts main.py every minute and a run holds webcams.lock until it
# finishes. Take that same lock so a pull can never swap files out from under a
# live run. A run that fires meanwhile just skips its cycle, which is exactly
# what single_instance.py is built to do. Opened for append rather than
# truncation so the holder's PID survives.
exec 9>>webcams.lock
log "waiting for webcams.lock (up to ${LOCK_WAIT}s)"
if ! flock -w "$LOCK_WAIT" 9; then
    echo "could not acquire webcams.lock after ${LOCK_WAIT}s" >&2
    exit 1
fi
log "lock acquired"

PREVIOUS=$(git rev-parse HEAD)
git fetch --quiet origin main
TARGET=$(git rev-parse origin/main)

log "current:  $PREVIOUS"
log "deploying: $TARGET"

if [ "$PREVIOUS" = "$TARGET" ]; then
    log "already up to date; nothing to do"
    exit 0
fi

# --ff-only rather than `reset --hard`: if the Pi has somehow picked up local
# commits, stop and report it instead of silently discarding them. A
# fast-forward also leaves untracked local state (.python-version,
# environment.env, fonts/, images/, logs) completely alone.
git merge --ff-only "$TARGET"

# uv must not reach for one of its managed ARM Python builds — those segfault on
# this Pi. Pointing it at the interpreter already in .venv (pyenv 3.11) keeps it
# on the one known to work.
if [ -x .venv/bin/python ]; then
    export UV_PYTHON="$DEPLOY_PATH/.venv/bin/python"
fi
export UV_PYTHON_DOWNLOADS=never

sync_deps() {
    # --no-dev keeps test-only packages off the production box.
    "$UV" sync --no-dev
}

# Syncing on every deploy would be wasted work; the lockfile is the only thing
# that can change what .venv needs to contain.
if git diff --quiet "$PREVIOUS" "$TARGET" -- pyproject.toml uv.lock; then
    log "no dependency changes"
else
    log "dependencies changed; syncing"
    sync_deps
fi

# Importing main builds every camera from webcams.yaml and touches no network,
# so this catches import errors and broken config now rather than letting the
# next cron tick fail in production.
log "smoke test"
if ! .venv/bin/python -c "import main"; then
    echo "smoke test failed; rolling back to $PREVIOUS" >&2
    git reset --hard "$PREVIOUS"
    sync_deps || true
    exit 1
fi

log "deployed $TARGET"
