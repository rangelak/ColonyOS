# =============================================================================
# ColonyOS Docker Image — Multi-Stage Build
# =============================================================================
# Stage 1: Install Claude Code CLI (Node.js)
# Stage 2: Build React SPA (Vite)
# Stage 3: Final runtime image (Python + Node.js + git + gh)
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Node dependencies — install Claude Code CLI globally
# ---------------------------------------------------------------------------
FROM node:20-slim AS node-deps

RUN npm install -g @anthropic-ai/claude-code && \
    npm cache clean --force

# ---------------------------------------------------------------------------
# Stage 2: Web build — compile the Vite React SPA
# ---------------------------------------------------------------------------
FROM node:20-slim AS web-build

WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
COPY src/colonyos/ /build/src/colonyos/
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 3: Final runtime image
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    COLONYOS_DOCKER=1

# Install system dependencies: git, curl, gpg (for gh CLI repo setup)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        curl \
        gpg \
        ca-certificates && \
    # Install GitHub CLI from official apt repository
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends gh && \
    # Cleanup
    apt-get purge -y gpg && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Copy Node.js runtime from the node-deps stage (required by Claude Code CLI)
COPY --from=node-deps /usr/local/bin/node /usr/local/bin/node
COPY --from=node-deps /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/.bin/claude /usr/local/bin/claude

# Copy built web SPA from the web-build stage
COPY --from=web-build /build/src/colonyos/web_dist/ /tmp/web_dist/

# Install ColonyOS with all optional extras
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/

# Copy pre-built SPA into the package before installing
RUN cp -r /tmp/web_dist/ src/colonyos/web_dist/ && \
    rm -rf /tmp/web_dist/

RUN pip install --no-cache-dir ".[ui,posthog,slack]"

# Create non-root user for security
RUN groupadd --gid 1000 colonyos && \
    useradd --uid 1000 --gid colonyos --create-home colonyos && \
    mkdir -p /workspace && \
    chown colonyos:colonyos /workspace

# Copy and set entrypoint
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Configure git safe directory for the workspace (avoids ownership warnings)
RUN git config --system --add safe.directory /workspace

WORKDIR /workspace
USER colonyos

EXPOSE 7400

ENTRYPOINT ["docker-entrypoint.sh"]
