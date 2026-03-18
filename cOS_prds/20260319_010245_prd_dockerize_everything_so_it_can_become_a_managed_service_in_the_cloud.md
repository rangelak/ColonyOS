# PRD: Dockerize ColonyOS for Cloud-Managed Deployment

**Date:** 2026-03-19
**Status:** Draft
**Author:** ColonyOS Planning Agent

---

## 1. Introduction / Overview

ColonyOS is an autonomous AI software engineering pipeline that orchestrates Claude Code agent sessions to plan, implement, review, and deliver pull requests. Today it is distributed exclusively as a Python CLI tool (via pip, pipx, Homebrew, and a curl installer) and runs directly on a developer's machine with local prerequisites (`claude` CLI, `gh` CLI, `git`).

This feature request adds Docker containerization to ColonyOS, enabling it to be deployed as a self-hosted managed service in the cloud. The Docker image will encapsulate the full pipeline — CLI, FastAPI web dashboard, and Claude Agent SDK execution — into a single deployable unit that teams can run on their own infrastructure with minimal setup.

### Why This Matters

- **Eliminates local setup friction**: No more installing Python 3.11+, Node.js (for Claude CLI), `gh`, and managing auth across tools
- **Enables cloud deployment**: Teams can run ColonyOS on cloud VMs, ECS, or Kubernetes without SSH-ing into a dev machine
- **Standardizes the runtime**: A Docker image is a reproducible, versioned artifact that works identically everywhere
- **Opens the path to managed service**: Self-hosted Docker → marketplace offering → eventual SaaS (future phases)

---

## 2. Goals

1. **Ship a production-ready Dockerfile** that bundles the complete ColonyOS runtime (Python 3.11+, Claude Code CLI, `gh` CLI, `git`, FastAPI dashboard with embedded React SPA)
2. **Provide a `docker-compose.yml`** for single-command local and self-hosted deployment
3. **Publish Docker images automatically** to GitHub Container Registry (ghcr.io) on every tagged release, alongside existing PyPI/Homebrew channels
4. **Maintain zero-secret images** — all credentials injected at runtime via environment variables
5. **Support persistent repo state** via volume mounts, preserving `.colonyos/` run history, learnings, and config across container restarts
6. **Keep existing distribution channels** (pip, pipx, Homebrew, curl installer) fully functional — Docker is additive

---

## 3. User Stories

### US-1: Self-Hosted Team Deployment
> As a **team lead**, I want to deploy ColonyOS on our cloud infrastructure using `docker compose up`, so that my team can trigger autonomous pipeline runs from the web dashboard without installing anything locally.

### US-2: CI/CD-Triggered Runs
> As a **DevOps engineer**, I want to run `docker run ghcr.io/colonyos/colonyos:latest colonyos run "Add health check"` in a CI pipeline, so that ColonyOS can be triggered by automated workflows.

### US-3: Quick Local Trial
> As a **developer evaluating ColonyOS**, I want to `docker compose up` with a `.env` file and a repo volume mount, so I can try the full pipeline without installing Python, Node.js, or configuring auth for multiple CLIs.

### US-4: Dashboard Access
> As a **project manager**, I want to access the ColonyOS web dashboard at `http://host:7400` from my browser after the container starts, so I can monitor runs, view PRDs, and inspect reviews without CLI access.

### US-5: Automated Image Updates
> As a **maintainer**, I want Docker images to be built and published automatically when I push a version tag, so the Docker distribution channel stays in sync with PyPI and Homebrew releases.

---

## 4. Functional Requirements

### FR-1: Dockerfile
- **FR-1.1**: Multi-stage build: (1) Node.js stage to install `@anthropic-ai/claude-code` globally, (2) Node.js stage to build the Vite React SPA, (3) Python runtime stage with the final image
- **FR-1.2**: Final image based on `python:3.11-slim` (pinned to digest, not tag)
- **FR-1.3**: Include `git`, `gh` CLI, Node.js runtime (required by Claude Code CLI), and all Python dependencies
- **FR-1.4**: Install ColonyOS with all optional extras: `colonyos[ui,posthog,slack]`
- **FR-1.5**: Run as non-root user (`colonyos` UID) for security
- **FR-1.6**: Expose port `7400` (dashboard default)
- **FR-1.7**: Set `WORKDIR` to `/workspace` (the mounted repo root)
- **FR-1.8**: Entrypoint script that: validates required env vars, cleans stale git lock files, optionally clones a repo if `/workspace` is empty, then starts the requested command

### FR-2: Docker Compose
- **FR-2.1**: Single-service `docker-compose.yml` with the ColonyOS container
- **FR-2.2**: Volume mount for the target repository at `/workspace`
- **FR-2.3**: Environment variable passthrough via `.env` file (gitignored)
- **FR-2.4**: Port mapping `7400:7400` for the dashboard
- **FR-2.5**: Health check using `colonyos doctor` (or a lightweight HTTP check on the dashboard)
- **FR-2.6**: Restart policy `unless-stopped` for long-running deployments

### FR-3: Entrypoint Script
- **FR-3.1**: Validate `ANTHROPIC_API_KEY` and `GH_TOKEN` are set; fail fast with clear error messages if missing
- **FR-3.2**: Clean stale `index.lock` files from git repos (prevents failures after container crash/restart)
- **FR-3.3**: If `COLONYOS_REPO_URL` is set and `/workspace/.git` does not exist, clone the repo into `/workspace`
- **FR-3.4**: If `/workspace/.git` exists, run `git fetch --all` to ensure freshness
- **FR-3.5**: Default command: `colonyos ui --host 0.0.0.0 --port 7400` (dashboard mode)
- **FR-3.6**: Support override commands: `docker run ... colonyos run "prompt"`, `docker run ... colonyos auto`

### FR-4: CI/CD — Image Build & Publish
- **FR-4.1**: Add a `docker` job to `.github/workflows/release.yml` that runs after the `test` gate
- **FR-4.2**: Build multi-platform images (`linux/amd64`, `linux/arm64`) using `docker buildx`
- **FR-4.3**: Push to GitHub Container Registry (`ghcr.io`) with version tag and `latest` alias
- **FR-4.4**: Use the same `v*` tag that triggers PyPI publish
- **FR-4.5**: Pin all GitHub Actions to commit SHAs (matching existing security posture in `ci.yml` and `release.yml`)

### FR-5: Environment Variable Configuration
- **FR-5.1**: Required: `ANTHROPIC_API_KEY`, `GH_TOKEN`
- **FR-5.2**: Optional: `COLONYOS_POSTHOG_API_KEY`, `COLONYOS_POSTHOG_HOST`, `COLONYOS_SLACK_BOT_TOKEN`, `COLONYOS_SLACK_APP_TOKEN`, `COLONYOS_WRITE_ENABLED`
- **FR-5.3**: Optional: `COLONYOS_REPO_URL` (for auto-clone on start)
- **FR-5.4**: Provide a `.env.example` file documenting all variables with descriptions
- **FR-5.5**: The `colonyos doctor` command must validate container-specific prerequisites (env vars, git access, network connectivity)

### FR-6: Documentation
- **FR-6.1**: Add a "Docker Deployment" section to `README.md` with quick-start instructions
- **FR-6.2**: Document all environment variables, volume mounts, and port mappings
- **FR-6.3**: Include troubleshooting for common Docker issues (permissions, git auth, Claude CLI auth)

---

## 5. Non-Goals (Explicitly Out of Scope)

- **Multi-tenant SaaS**: No tenant isolation, shared infrastructure, or user management. Every persona agreed: the `bypassPermissions` agent model makes multi-tenancy a security non-starter without a ground-up rewrite.
- **Kubernetes Helm chart**: Docker Compose is the target orchestrator. K8s support is a future phase.
- **Database migration**: State remains file-based with volume mounts. No PostgreSQL/SQLite introduction.
- **Concurrent multi-run support**: The existing `threading.Semaphore(1)` in `server.py` (line 89) enforces one run at a time. This is preserved — concurrent runs require architectural changes to git workspace isolation.
- **Ephemeral per-run cloning**: Runs operate on a persistent volume-mounted repo. Per-run ephemeral clones are a future optimization for managed service scaling.
- **Docker Hub publishing**: Images go to GitHub Container Registry (ghcr.io) only.
- **Custom reverse proxy / auth layer**: The dashboard ships as-is. External auth (nginx, Cloudflare Tunnel, etc.) is the operator's responsibility.

---

## 6. Technical Considerations

### 6.1 Architecture Fit

The existing codebase is well-suited for containerization:

- **Single-process model**: `server.py` runs FastAPI + orchestrator in one process with background threads. This maps cleanly to one container.
- **Embedded SPA**: The React dashboard is pre-built into `src/colonyos/web_dist/` and served by FastAPI (`server.py` lines 426-451). No separate frontend container needed.
- **File-based state**: All state lives under `repo_root/.colonyos/` — a single volume mount preserves everything.
- **Env-var-driven config**: Secrets are already read from environment variables (`doctor.py`, `telemetry.py`, `slack.py`). No code changes needed for Docker secrets injection.

### 6.2 Key Files to Modify/Create

| File | Action | Purpose |
|------|--------|---------|
| `Dockerfile` | **Create** | Multi-stage build for the ColonyOS image |
| `docker-compose.yml` | **Create** | Single-command deployment |
| `docker-entrypoint.sh` | **Create** | Startup validation, git cleanup, default command |
| `.env.example` | **Create** | Document all environment variables |
| `.dockerignore` | **Create** | Exclude `.venv`, `.git`, `node_modules`, `.env`, `.colonyos/runs/` |
| `.github/workflows/release.yml` | **Modify** | Add Docker build & push job |
| `README.md` | **Modify** | Add Docker deployment section |
| `src/colonyos/doctor.py` | **Modify** | Add container-aware checks (detect Docker, validate env vars) |
| `tests/test_docker.py` | **Create** | Tests for entrypoint script and Dockerfile build |

### 6.3 External Dependencies in the Image

| Dependency | Source | Purpose |
|-----------|--------|---------|
| Python 3.11+ | Base image | ColonyOS runtime |
| Node.js 20+ | apt/nodesource | Required by Claude Code CLI |
| `@anthropic-ai/claude-code` | npm global install | Claude agent execution |
| `gh` CLI | GitHub's apt repo | PR creation, GitHub operations |
| `git` | apt | Version control operations |
| ColonyOS + extras | pip install | The application itself |

### 6.4 Image Size Considerations

The image will be larger than typical Python containers (~800MB-1.2GB estimated) due to Node.js + Claude Code CLI. Multi-stage builds minimize this by excluding build tools from the final image. This is an acceptable tradeoff — ColonyOS is a long-running service, not a serverless function.

### 6.5 Persona Consensus & Tensions

**Strong consensus across all 7 personas:**
- Single-tenant self-hosted (unanimous) — `bypassPermissions` makes multi-tenancy unsafe
- Environment variables for secrets (unanimous) — never bake credentials into images
- File-based state with volumes (6/7) — database is premature
- Docker Compose as target platform (5/7) — Cloud Run disqualified by long run durations
- Bundled dashboard container (5/7) — already monolithic by design

**Key tensions:**
- **Jony Ive & Karpathy** advocated for separate dashboard/worker containers for cleaner separation of concerns and independent scaling. The **majority view** (Michael Seibel, Steve Jobs, Linus Torvalds, Systems Engineer) correctly noted that `server.py` already bundles everything and splitting adds complexity with no current benefit. **Decision: Bundle now, split later.**
- **Security Engineer** raised valid concerns about the agent's ability to read all env vars via `bypassPermissions` shell access. Mitigation: document the trust model, recommend network-level controls for production. Full env-var isolation requires a sidecar proxy pattern (future work).
- **Karpathy & Security Engineer** preferred ephemeral clones per run for isolation. **Decision: Persistent volume for v1** (preserves `.colonyos/` state), with ephemeral clones as a future scaling feature.

---

## 7. Success Metrics

| Metric | Target | How to Measure |
|--------|--------|----------------|
| Docker image builds on every release | 100% | CI workflow success rate |
| `docker compose up` → dashboard accessible | < 60 seconds | Manual + automated test |
| `docker run ... colonyos run "prompt"` succeeds | End-to-end | Integration test with mock agent |
| Image size | < 1.5 GB | CI build output |
| Zero secrets in image layers | 100% | `docker history` + Trivy scan |
| Existing tests still pass | 100% | CI pytest matrix unchanged |
| `colonyos doctor` passes inside container | 100% | Entrypoint validation |

---

## 8. Open Questions

1. **Claude Code CLI headless auth**: Does the Claude Code CLI fully support `ANTHROPIC_API_KEY` env var for headless authentication, or does it require an interactive `claude login` step? This needs validation before the Dockerfile is finalized.
2. **Image signing**: Should we add cosign/Sigstore image signing in the initial release, or defer to a follow-up? (Security Engineer recommends it; others say defer.)
3. **Dashboard auth**: The FastAPI dashboard has no authentication on read endpoints (`server.py` lines 121-182). Should we add basic auth or recommend an external proxy? (Deferred per non-goals, but worth flagging.)
4. **Trivy/Grype scanning**: Should container image vulnerability scanning be added to CI in this iteration or a follow-up?
5. **ARM support priority**: Is `linux/arm64` support critical for launch (Apple Silicon local dev), or can we ship `amd64`-only first?
6. **`colonyos ui --host` flag**: The dashboard currently defaults to `127.0.0.1`. Need to verify the `--host` flag exists to bind to `0.0.0.0` inside the container, or add it.
