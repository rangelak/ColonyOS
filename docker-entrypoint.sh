#!/usr/bin/env bash
set -euo pipefail

# ColonyOS Docker Entrypoint
# Validates environment, prepares the workspace, and launches the requested command.

# ---------------------------------------------------------------------------
# 1. Validate required environment variables
# ---------------------------------------------------------------------------
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "ERROR: ANTHROPIC_API_KEY is not set." >&2
    echo "Pass it via: docker run -e ANTHROPIC_API_KEY=sk-... or in your .env file." >&2
    exit 1
fi

if [ -z "${GH_TOKEN:-}" ]; then
    echo "WARNING: GH_TOKEN is not set. GitHub operations (PR creation, issue management) will fail." >&2
    echo "Pass it via: docker run -e GH_TOKEN=ghp_... or in your .env file." >&2
fi

# ---------------------------------------------------------------------------
# 2. Clean stale git lock files (prevents failures after container crash)
# ---------------------------------------------------------------------------
if [ -f /workspace/.git/index.lock ]; then
    echo "INFO: Removing stale .git/index.lock"
    rm -f /workspace/.git/index.lock
fi

# ---------------------------------------------------------------------------
# 3. Clone or fetch the target repository
# ---------------------------------------------------------------------------
if [ -n "${COLONYOS_REPO_URL:-}" ] && [ ! -d /workspace/.git ]; then
    echo "INFO: Cloning ${COLONYOS_REPO_URL} into /workspace"
    git clone "${COLONYOS_REPO_URL}" /workspace
elif [ -d /workspace/.git ]; then
    echo "INFO: Fetching latest changes in /workspace"
    git -C /workspace fetch --all --quiet || echo "WARNING: git fetch failed (network issue?)"
fi

# ---------------------------------------------------------------------------
# 4. Launch the requested command (default: dashboard)
# ---------------------------------------------------------------------------
if [ $# -eq 0 ]; then
    exec colonyos ui --host 0.0.0.0 --port 7400
else
    exec "$@"
fi
