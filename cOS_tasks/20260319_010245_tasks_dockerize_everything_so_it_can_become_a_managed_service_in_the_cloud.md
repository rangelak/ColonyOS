# Tasks: Dockerize ColonyOS for Cloud-Managed Deployment

**PRD:** `cOS_prds/20260319_010245_prd_dockerize_everything_so_it_can_become_a_managed_service_in_the_cloud.md`
**Date:** 2026-03-19

---

## Relevant Files

### Existing Files to Modify
- `src/colonyos/doctor.py` — Add container-aware environment checks (detect Docker runtime, validate required env vars)
- `src/colonyos/server.py` — Verify `--host 0.0.0.0` binding support for container networking
- `src/colonyos/cli.py` — Ensure `colonyos ui` command supports `--host` flag for container binding
- `.github/workflows/release.yml` — Add Docker build & push job to release pipeline
- `.gitignore` — Add Docker-specific ignores
- `README.md` — Add Docker deployment documentation section
- `pyproject.toml` — No changes expected (image installs from source)

### Existing Test Files to Modify
- `tests/test_cli.py` — Add tests for any new CLI flags (e.g., `--host`)
- `tests/conftest.py` — Add shared fixtures for Docker-related tests

### New Files to Create
- `Dockerfile` — Multi-stage build for the ColonyOS image
- `docker-compose.yml` — Single-command deployment configuration
- `docker-entrypoint.sh` — Container startup script (validation, git cleanup, default cmd)
- `.dockerignore` — Exclude unnecessary files from build context
- `.env.example` — Document all required/optional environment variables
- `tests/test_docker.py` — Tests for entrypoint script logic and Dockerfile validity

---

## Tasks

- [x] 1.0 Create the Dockerfile (multi-stage build)
  - [x] 1.1 Write tests for Dockerfile validity — `tests/test_docker.py`: test that Dockerfile parses correctly, test that `.dockerignore` excludes sensitive files (`.env`, `.colonyos/runs/`), test that the entrypoint script is executable
  - [x] 1.2 Create `.dockerignore` to exclude `.venv/`, `.git/`, `node_modules/`, `.env`, `.colonyos/runs/`, `dist/`, `__pycache__/`, `*.pyc`
  - [x] 1.3 Create multi-stage `Dockerfile`:
    - Stage 1 (`node-deps`): Based on `node:20-slim`, install `@anthropic-ai/claude-code` globally
    - Stage 2 (`web-build`): Build the Vite React SPA from `web/` into `web/dist/`
    - Stage 3 (`runtime`): Based on `python:3.11-slim`, install `git`, `gh` CLI, copy Node.js runtime + Claude CLI from stage 1, copy built SPA, install ColonyOS with `pip install .[ui,posthog,slack]`, create non-root `colonyos` user, set `WORKDIR /workspace`, expose port 7400
  - [x] 1.4 Verify the image builds successfully and `colonyos --version` runs inside the container

- [x] 2.0 Create the container entrypoint script
  - [x] 2.1 Write tests for entrypoint logic — `tests/test_docker.py`: test env var validation (missing `ANTHROPIC_API_KEY` exits with error), test git lock file cleanup logic, test repo clone logic when `COLONYOS_REPO_URL` is set
  - [x] 2.2 Create `docker-entrypoint.sh`:
    - Validate `ANTHROPIC_API_KEY` is set (fail with clear message)
    - Validate `GH_TOKEN` is set (warn but don't fail — some commands don't need it)
    - Clean stale `.git/index.lock` if present in `/workspace`
    - If `COLONYOS_REPO_URL` is set and `/workspace/.git` doesn't exist, run `git clone`
    - If `/workspace/.git` exists, run `git fetch --all`
    - Default command: `colonyos ui --host 0.0.0.0 --port 7400`
    - Pass through any explicit CMD arguments (`exec "$@"`)
  - [x] 2.3 Make the entrypoint executable and set it as `ENTRYPOINT` in the Dockerfile

- [x] 3.0 Create Docker Compose configuration
  - [x] 3.1 Create `.env.example` with all documented environment variables:
    - Required: `ANTHROPIC_API_KEY`, `GH_TOKEN`
    - Optional: `COLONYOS_REPO_URL`, `COLONYOS_POSTHOG_API_KEY`, `COLONYOS_POSTHOG_HOST`, `COLONYOS_SLACK_BOT_TOKEN`, `COLONYOS_SLACK_APP_TOKEN`, `COLONYOS_WRITE_ENABLED`
  - [x] 3.2 Create `docker-compose.yml`:
    - Service `colonyos`: build from `.`, port `7400:7400`, volume mount `./:/workspace` (or configurable), `env_file: .env`, restart `unless-stopped`, healthcheck via `colonyos doctor` or HTTP GET to dashboard
  - [x] 3.3 Verify `docker compose up` starts the dashboard and it is accessible at `http://localhost:7400`

- [x] 4.0 Update `colonyos doctor` for container-aware checks
  - [x] 4.1 Write tests — `tests/test_cli.py` or `tests/test_docker.py`: test that doctor detects Docker runtime (mocked `/.dockerenv` file), test that doctor checks `ANTHROPIC_API_KEY` and `GH_TOKEN` env vars when running in container
  - [x] 4.2 Modify `src/colonyos/doctor.py`:
    - Detect if running inside Docker (check `/.dockerenv` or `COLONYOS_DOCKER=1` env var)
    - When in Docker: validate `ANTHROPIC_API_KEY` env var is set
    - When in Docker: validate `GH_TOKEN` env var is set (or `gh auth status` passes)
    - When in Docker: check `/workspace` is a valid git repo
  - [x] 4.3 Ensure `colonyos doctor` still works identically outside Docker (no behavior changes for existing users)

- [x] 5.0 Ensure dashboard binds to `0.0.0.0` in container
  - [x] 5.1 Write tests — `tests/test_cli.py`: test that `colonyos ui --host 0.0.0.0` is accepted, test that the `--host` flag is properly passed to uvicorn
  - [x] 5.2 Verify `src/colonyos/cli.py` `ui` command supports `--host` flag; if not, add it (currently the server may bind to `127.0.0.1` by default, which is unreachable from outside the container)
  - [x] 5.3 Verify `src/colonyos/server.py` passes the host parameter to `uvicorn.run()`

- [x] 6.0 Add Docker image build & publish to CI/CD
  - [x] 6.1 Write a test/validation step — add a `docker-build-test` job to `.github/workflows/ci.yml` that builds the Docker image (but doesn't push) on every PR, to catch Dockerfile regressions
  - [x] 6.2 Modify `.github/workflows/release.yml`:
    - Add a `docker` job that runs after the `test` gate
    - Use `docker/build-push-action` (pinned to commit SHA) with `docker buildx` for multi-platform (`linux/amd64,linux/arm64`)
    - Push to `ghcr.io/${{ github.repository }}` with tags: `${{ github.ref_name }}` (version) and `latest`
    - Add `packages: write` permission to the job
  - [x] 6.3 Add `.github/workflows/ci.yml` job that builds (but does not push) the Docker image on PRs, to validate the Dockerfile

- [x] 7.0 Update documentation
  - [x] 7.1 Add "Docker Deployment" section to `README.md`:
    - Quick start with `docker compose up`
    - Environment variable reference table
    - Volume mount explanation
    - Running one-off commands (`docker run ... colonyos run "prompt"`)
    - Troubleshooting common issues (permissions, git auth, Claude CLI auth)
  - [x] 7.2 Update `.gitignore` to include `.env` (if not already present — it is) and any Docker-specific files that should be excluded

- [x] 8.0 End-to-end validation
  - [x] 8.1 Run existing test suite (`pytest`) to ensure no regressions
  - [x] 8.2 Build the Docker image locally and verify:
    - `docker compose up` starts successfully
    - Dashboard is accessible at `http://localhost:7400`
    - `colonyos doctor` passes inside the container
    - `colonyos run "test prompt"` executes successfully with valid API keys
  - [x] 8.3 Verify the CI pipeline builds the image successfully on a test branch
