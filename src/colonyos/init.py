from __future__ import annotations

import json
import logging
import signal
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import click
from rich.table import Table
from rich.text import Text

from colonyos.config import (
    DEFAULTS,
    VALID_MODELS,
    ColonyConfig,
    BudgetConfig,
    PhasesConfig,
    config_dir_path,
    load_config,
    save_config,
)
from colonyos.models import Persona, Phase, PhaseResult, ProjectInfo, RepoContext
from colonyos.persona_packs import PACKS, get_pack, pack_keys, packs_summary
from colonyos.ui import console

logger = logging.getLogger(__name__)

def is_git_repo(path: Path) -> bool:
    """Return True if *path* is inside a git repository.

    Walks from *path* up to the filesystem root looking for a ``.git``
    directory or file (submodules use a ``.git`` file).
    """
    for parent in [path, *path.parents]:
        if (parent / ".git").exists():
            return True
    return False


_MANIFEST_FILES: list[tuple[str, str]] = [
    ("README.md", ""),
    ("README.rst", ""),
    ("package.json", "javascript"),
    ("pyproject.toml", "python"),
    ("Cargo.toml", "rust"),
    ("go.mod", "go"),
    ("requirements.txt", "python"),
    ("Gemfile", "ruby"),
    ("pom.xml", "java"),
    ("build.gradle", "java"),
]

_MANIFEST_TRUNCATE_CHARS = 2000


MODEL_PRESETS: dict[str, dict[str, str | dict[str, str]]] = {
    "Quality-first": {
        "model": "opus",
        "phase_models": {},
    },
    "Cost-optimized": {
        "model": "opus",
        "phase_models": {},
    },
}


def _section(title: str, subtitle: str = "") -> None:
    """Render a styled section header matching the pipeline UI."""
    label = f" {title}"
    if subtitle:
        label += f"  [dim]{subtitle}[/dim]"
    console.print()
    console.rule(label, style="bold")


_ARROW = click.style("›", fg="bright_cyan", bold=True)


def _prompt(text: str, default: str = "") -> str:
    return click.prompt(
        f"  {_ARROW} {text}",
        default=default,
        show_default=bool(default),
        prompt_suffix=" ",
    )


# ---------------------------------------------------------------------------
# Repo auto-detection (FR-2) — deterministic, zero LLM tokens
# ---------------------------------------------------------------------------

def scan_repo_context(repo_root: Path) -> RepoContext:
    """Deterministically scan well-known manifest files to gather repo signals.

    Returns a ``RepoContext`` with the best-effort project name, description,
    stack, and truncated raw file contents.  This function never calls an LLM.
    """
    raw_signals: dict[str, str] = {}

    for rel_path, _stack_hint in _MANIFEST_FILES:
        full = repo_root / rel_path
        if full.is_file():
            try:
                content = full.read_text(encoding="utf-8", errors="replace")[
                    :_MANIFEST_TRUNCATE_CHARS
                ]
                raw_signals[rel_path] = content
            except OSError:
                pass

    # Also grab first CI workflow file
    workflows_dir = repo_root / ".github" / "workflows"
    if workflows_dir.is_dir():
        yml_files = sorted(workflows_dir.glob("*.yml"))
        if yml_files:
            try:
                content = yml_files[0].read_text(encoding="utf-8", errors="replace")[
                    :_MANIFEST_TRUNCATE_CHARS
                ]
                raw_signals[f".github/workflows/{yml_files[0].name}"] = content
            except OSError:
                pass

    # Extract project info from manifests
    name = ""
    description = ""
    stack_parts: list[str] = []
    manifest_type = ""
    readme_excerpt = ""

    # README
    for readme_name in ("README.md", "README.rst"):
        if readme_name in raw_signals:
            readme_excerpt = raw_signals[readme_name]
            break

    # package.json
    if "package.json" in raw_signals:
        manifest_type = manifest_type or "package.json"
        stack_parts.append("JavaScript/Node.js")
        try:
            pkg = json.loads(raw_signals["package.json"])
            name = name or pkg.get("name", "")
            description = description or pkg.get("description", "")
        except (json.JSONDecodeError, TypeError):
            pass

    # pyproject.toml
    if "pyproject.toml" in raw_signals:
        manifest_type = manifest_type or "pyproject.toml"
        stack_parts.append("Python")
        content = raw_signals["pyproject.toml"]
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("name") and "=" in stripped:
                val = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                name = name or val
            if stripped.startswith("description") and "=" in stripped:
                val = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                description = description or val

    # Cargo.toml
    if "Cargo.toml" in raw_signals:
        manifest_type = manifest_type or "Cargo.toml"
        stack_parts.append("Rust")
        content = raw_signals["Cargo.toml"]
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("name") and "=" in stripped:
                val = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                name = name or val

    # go.mod
    if "go.mod" in raw_signals:
        manifest_type = manifest_type or "go.mod"
        stack_parts.append("Go")
        content = raw_signals["go.mod"]
        for line in content.splitlines():
            if line.startswith("module "):
                mod_path = line.split(None, 1)[1].strip()
                name = name or mod_path.rsplit("/", 1)[-1]
                break

    # requirements.txt
    if "requirements.txt" in raw_signals and "Python" not in stack_parts:
        stack_parts.append("Python")
        manifest_type = manifest_type or "requirements.txt"

    # Gemfile
    if "Gemfile" in raw_signals:
        stack_parts.append("Ruby")
        manifest_type = manifest_type or "Gemfile"

    # pom.xml / build.gradle
    if "pom.xml" in raw_signals or "build.gradle" in raw_signals:
        stack_parts.append("Java")
        manifest_type = manifest_type or ("pom.xml" if "pom.xml" in raw_signals else "build.gradle")

    # Fallback: use directory name as project name
    if not name:
        name = repo_root.name

    stack = ", ".join(stack_parts) if stack_parts else ""

    return RepoContext(
        name=name,
        description=description,
        stack=stack,
        readme_excerpt=readme_excerpt,
        manifest_type=manifest_type,
        raw_signals=raw_signals,
    )


# ---------------------------------------------------------------------------
# LLM system prompt and response parsing (FR-3)
# ---------------------------------------------------------------------------

def _build_init_system_prompt(repo_context: RepoContext) -> str:
    """Compose the system prompt for the AI-assisted init LLM call."""
    packs_info = json.dumps(packs_summary(), indent=2)
    presets_info = json.dumps(
        {k: {"model": v["model"], "phase_models": v["phase_models"]} for k, v in MODEL_PRESETS.items()},
        indent=2,
    )
    defaults_info = json.dumps(DEFAULTS, indent=2)
    valid_pack_keys = pack_keys()

    return f"""\
You are a project setup assistant for ColonyOS, a development pipeline tool.

Your job: analyze the repository context below and recommend the best
configuration. Output ONLY a JSON object — no markdown fences, no
explanation text.

## Repository Context

- **Project name (detected):** {repo_context.name}
- **Description (detected):** {repo_context.description}
- **Tech stack (detected):** {repo_context.stack}
- **Manifest type:** {repo_context.manifest_type}

### README excerpt
{repo_context.readme_excerpt[:1500] if repo_context.readme_excerpt else "(none)"}

## Available Persona Packs
{packs_info}

## Available Model Presets
{presets_info}

## Default Configuration Values
{defaults_info}

## Your Task

Choose the best persona pack and model preset for this project.
Fill in project name, description, and stack.
Optionally suggest a vision string if the README contains an obvious
mission statement — otherwise leave it empty.

## Required JSON Output Schema

{{
  "pack_key": one of {valid_pack_keys},
  "preset_name": one of {list(MODEL_PRESETS.keys())},
  "project_name": "string",
  "project_description": "string",
  "project_stack": "string",
  "vision": "string (optional, empty string if unsure)"
}}

Output ONLY the JSON object. No other text."""


def _parse_ai_config_response(raw_text: str) -> dict[str, Any] | None:
    """Parse and validate the LLM's JSON response.

    Returns a validated dict with keys (pack_key, preset_name,
    project_name, project_description, project_stack, vision),
    or None if parsing/validation fails.
    """
    # Try to extract JSON from the response (handle markdown fences)
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove first and last fence lines
        start = 1
        end = len(lines)
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip().startswith("```"):
                end = i
                break
        text = "\n".join(lines[start:end])

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        logger.debug("AI init response failed JSON parse: %s", raw_text[:200])
        return None

    if not isinstance(data, dict):
        return None

    # Validate pack_key
    pk = data.get("pack_key")
    if pk not in pack_keys():
        logger.debug("AI init response invalid pack_key: %s", pk)
        return None

    # Validate preset_name
    preset = data.get("preset_name")
    if preset not in MODEL_PRESETS:
        logger.debug("AI init response invalid preset_name: %s", preset)
        return None

    # Validate project_name is present and non-empty
    pname = data.get("project_name")
    if not pname or not isinstance(pname, str):
        logger.debug("AI init response missing project_name")
        return None

    return {
        "pack_key": pk,
        "preset_name": preset,
        "project_name": str(data.get("project_name", "")),
        "project_description": str(data.get("project_description", "")),
        "project_stack": str(data.get("project_stack", "")),
        "vision": str(data.get("vision", "")),
    }


# ---------------------------------------------------------------------------
# Config preview (FR-4)
# ---------------------------------------------------------------------------

def render_config_preview(
    config: ColonyConfig,
    pack_name: str,
    preset_name: str,
    *,
    console: Any | None = None,
) -> None:
    """Render a Rich panel previewing the proposed configuration.

    Accepts an optional ``console`` parameter for testability; when None a
    new ``Console`` is created.
    """
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    if console is None:
        console = Console()

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="bold cyan")
    table.add_column("Value")

    if config.project:
        table.add_row("Project", config.project.name)
        table.add_row("Description", config.project.description or "(none)")
        table.add_row("Tech stack", config.project.stack or "(none)")
    table.add_row("", "")

    table.add_row("Persona pack", pack_name)
    roles = ", ".join(p.role for p in config.personas)
    table.add_row("Personas", roles)
    table.add_row("", "")

    table.add_row("Model preset", preset_name)
    table.add_row("Default model", config.model)
    if config.phase_models:
        overrides = ", ".join(f"{k}={v}" for k, v in config.phase_models.items())
        table.add_row("Phase overrides", overrides)
    table.add_row("", "")

    table.add_row("Budget / phase", f"${config.budget.per_phase:.2f}")
    table.add_row("Budget / run", f"${config.budget.per_run:.2f}")

    if config.vision:
        table.add_row("", "")
        table.add_row("Vision", config.vision)

    console.print(Panel(
        table,
        title="Proposed Configuration",
        title_align="left",
        border_style="bright_blue",
        padding=(1, 2),
        expand=True,
    ))
    console.print(
        "  [dim]Config will be saved to .colonyos/config.yaml — "
        "you can edit it later.[/dim]\n"
    )


# ---------------------------------------------------------------------------
# AI-assisted init (FR-1, FR-3, FR-5, FR-6)
# ---------------------------------------------------------------------------

_AI_INIT_TIMEOUT_SECONDS = 30


class _AiInitTimeout(Exception):
    """Raised when the AI init LLM call exceeds the allowed time."""


def _friendly_init_error(exc: Exception) -> str:
    """Extract a human-readable message from SDK exceptions during init.

    Mirrors the ``_friendly_error`` helper in ``agent.py`` but is tailored
    to the init context where the user may not yet have a working API key.
    """
    raw = str(exc)
    stderr = getattr(exc, "stderr", None) or ""
    result = getattr(exc, "result", None) or ""

    for text in (result, stderr, raw):
        lower = text.lower()
        if "credit balance" in lower:
            return "Credit balance is too low to run AI setup."
        if "authentication" in lower or "unauthorized" in lower:
            return f"Authentication failed — check your API key or Claude login. {text.strip()}"
        if "rate limit" in lower:
            return f"Rate limited by the API. {text.strip()}"

    if isinstance(exc, _AiInitTimeout):
        return f"AI setup timed out after {_AI_INIT_TIMEOUT_SECONDS}s."

    return raw


def run_ai_init(
    repo_root: Path,
    *,
    doctor_check: bool = False,
) -> ColonyConfig:
    """AI-assisted init: scan repo, call LLM, propose config, confirm.

    Falls back to ``run_init()`` on any failure.
    """
    from colonyos.agent import run_phase_sync
    from colonyos.models import Phase

    # --- Doctor pre-check (same as run_init) ---
    if doctor_check:
        from colonyos.doctor import run_doctor_checks

        checks = run_doctor_checks(repo_root)
        hard_prereqs = {"Python ≥ 3.11", "Claude Code CLI", "Git"}
        failures = [name for name, ok, _ in checks if not ok and name in hard_prereqs]
        if failures:
            raise click.ClickException(
                f"Missing prerequisite(s): {', '.join(failures)}. "
                f"Run `colonyos doctor` for details."
            )

    # Step 1: Deterministic repo scan
    repo_ctx = scan_repo_context(repo_root)

    # Step 2: LLM call
    click.echo(
        "\nUsing Claude Haiku to analyze your repo (typically <$0.05)...\n"
    )

    system_prompt = _build_init_system_prompt(repo_ctx)
    prompt = (
        "Analyze this repository and recommend the best ColonyOS configuration. "
        "Output only valid JSON matching the schema in your instructions."
    )

    def _timeout_handler(signum: int, frame: object) -> None:
        raise _AiInitTimeout(
            f"AI init LLM call exceeded {_AI_INIT_TIMEOUT_SECONDS}s deadline"
        )

    try:
        # Install a SIGALRM-based timeout on platforms that support it
        _has_alarm = hasattr(signal, "SIGALRM")
        if _has_alarm:
            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(_AI_INIT_TIMEOUT_SECONDS)

        try:
            result: PhaseResult = run_phase_sync(
                Phase.PLAN,
                prompt,
                cwd=repo_root,
                system_prompt=system_prompt,
                model="haiku",
                budget_usd=0.50,
                max_turns=3,
                allowed_tools=["Read", "Glob", "Grep"],
                permission_mode="default",
            )
        finally:
            if _has_alarm:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
    except Exception as exc:
        friendly = _friendly_init_error(exc)
        click.echo(f"AI setup unavailable ({friendly}), falling back to manual wizard.\n")
        return run_init(repo_root, defaults=repo_ctx)

    if not result.success:
        click.echo(
            f"AI setup failed ({result.error or 'unknown error'}), "
            "falling back to manual wizard.\n"
        )
        return run_init(repo_root, defaults=repo_ctx)

    # Step 3: Display cost
    cost = result.cost_usd or 0
    click.echo(f"Analysis complete (cost: ${cost:.4f}).\n")

    # Step 4: Parse response
    raw_text = (result.artifacts or {}).get("result", "")
    parsed = _parse_ai_config_response(raw_text)

    if parsed is None:
        click.echo(
            "Could not parse AI recommendation, falling back to manual wizard.\n"
        )
        return run_init(repo_root, defaults=repo_ctx)

    # Step 5: Build ColonyConfig from parsed response
    pack = get_pack(parsed["pack_key"])
    if pack is None:
        click.echo("Invalid persona pack, falling back to manual wizard.\n")
        return run_init(repo_root, defaults=repo_ctx)

    preset = MODEL_PRESETS[parsed["preset_name"]]
    existing = load_config(repo_root)

    config = replace(
        existing,
        project=ProjectInfo(
            name=parsed["project_name"],
            description=parsed["project_description"],
            stack=parsed["project_stack"],
        ),
        personas=list(pack.personas),
        model=preset["model"],
        phase_models=dict(preset["phase_models"]),
        vision=parsed.get("vision", ""),
    )

    # Step 6: Preview and confirm
    render_config_preview(config, pack.name, parsed["preset_name"])

    if not click.confirm("Save this configuration?", default=True):
        click.echo("\nDropping to manual wizard with detected defaults...\n")
        return run_init(repo_root, defaults=repo_ctx)

    # Step 7: Save — reuse _finalize_init to avoid duplicating dir/gitignore logic
    return _finalize_init(repo_root, config)


# ---------------------------------------------------------------------------
# Interactive init (manual wizard)
# ---------------------------------------------------------------------------

def collect_project_info(defaults: RepoContext | None = None) -> ProjectInfo:
    """Collect project info interactively, optionally pre-filled from RepoContext."""
    _section("Project Info")
    name = _prompt("Project name", default=defaults.name if defaults else "")
    description = _prompt(
        "Brief description (what does this project do?)",
        default=defaults.description if defaults else "",
    )
    stack = _prompt(
        "Tech stack (e.g. Python/FastAPI, React, PostgreSQL)",
        default=defaults.stack if defaults else "",
    )
    return ProjectInfo(name=name, description=description, stack=stack)


def select_persona_pack() -> list[Persona] | None:
    """Present a menu of prebuilt persona packs and return the selected personas.

    Returns the list of Persona instances from the chosen pack, or None if
    the user selects "Custom (define your own)".
    """
    _section("Persona Packs", "choose a prebuilt team or define your own")

    for i, pack in enumerate(PACKS, 1):
        console.print(
            f"  [bold bright_cyan]{i}[/bold bright_cyan]. "
            f"[bold]{pack.name}[/bold] [dim]— {pack.description}[/dim]",
            highlight=False,
        )
    custom_index = len(PACKS) + 1
    console.print(
        f"  [bold bright_cyan]{custom_index}[/bold bright_cyan]. "
        f"[bold]Custom[/bold] [dim]— define your own[/dim]",
        highlight=False,
    )

    choice = click.prompt(
        f"\n  {_ARROW} Select a pack",
        type=click.IntRange(1, custom_index),
        default=1,
        prompt_suffix=" ",
    )

    if choice == custom_index:
        return None

    pack = PACKS[choice - 1]

    table = Table(
        show_header=True, header_style="bold", box=None, padding=(0, 2),
    )
    table.add_column("#", style="bold bright_cyan", width=3)
    table.add_column("Role", style="bold")
    table.add_column("Expertise", style="dim")
    for i, persona in enumerate(pack.personas, 1):
        table.add_row(str(i), persona.role, persona.expertise)

    console.print()
    console.print(f"  [bold]{pack.name}[/bold]", highlight=False)
    console.print(table)

    if not click.confirm(
        f"\n  {_ARROW} Use these {len(pack.personas)} personas?",
        default=True,
    ):
        return None

    return list(pack.personas)


def collect_personas(existing: list[Persona] | None = None) -> list[Persona]:
    _section("Agent Personas", "define the expert panel for reviews & planning")
    console.print(
        "  [dim]Each persona has a role, expertise, and a perspective they bring.\n"
        "  You'll typically want 3–5 personas.[/dim]",
        highlight=False,
    )

    personas: list[Persona] = []

    if existing:
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("#", style="bold bright_cyan", width=3)
        table.add_column("Role", style="bold")
        table.add_column("Expertise", style="dim")
        for i, p in enumerate(existing, 1):
            table.add_row(str(i), p.role, p.expertise)
        console.print()
        console.print(table)
        if click.confirm(
            f"\n  {_ARROW} Keep existing personas and add more?",
            default=True,
        ):
            personas = list(existing)

    while True:
        _section(f"Persona {len(personas) + 1}")
        role = _prompt("Role (e.g. Senior Backend Engineer, Product Lead)")
        expertise = _prompt("Expertise (e.g. API design, user research)")
        perspective = _prompt(
            "Perspective (what does this person think about?)",
            default="",
        )
        is_reviewer = click.confirm(
            f"  {_ARROW} Should this persona participate in code reviews?",
            default=True,
        )
        personas.append(Persona(role=role, expertise=expertise, perspective=perspective, reviewer=is_reviewer))

        if len(personas) >= 3 and not click.confirm(
            f"  {_ARROW} Add another persona?",
            default=len(personas) < 5,
        ):
            break

    return personas


def _collect_personas_with_packs(existing: list[Persona] | None = None) -> list[Persona]:
    """Collect personas via pack selection, with optional custom additions.

    First offers prebuilt packs; if a pack is selected, asks whether to add
    custom personas on top. Falls back to the fully custom flow if the user
    picks "Custom".
    """
    pack_personas = select_persona_pack()

    if pack_personas is None:
        return collect_personas(existing)

    if click.confirm(f"  {_ARROW} Add custom personas on top?", default=False):
        return collect_personas(existing=pack_personas)

    return pack_personas


def _collect_strategic_goals() -> str:
    """Prompt user for their north star that feeds into directions generation."""
    _section("CEO Directions", "north star & landscape inspiration")
    console.print(
        "  [dim]What's your north star for this project? Where should it go?\n"
        "  The system will research similar projects and build a landscape\n"
        "  doc that gives the CEO agent taste and inspiration.\n\n"
        "  Examples:[/dim] [italic]'become the best open-source CLI for X'[/italic][dim],\n"
        "  [/dim][italic]'match feature parity with tool Y'[/italic][dim], "
        "[/dim][italic]'developer experience first'[/italic]\n"
        "  [dim]Press Enter twice to finish.[/dim]",
        highlight=False,
    )
    console.print()
    lines: list[str] = []
    while True:
        line = click.prompt(
            f"  {_ARROW}",
            default="", show_default=False,
            prompt_suffix=" ",
        )
        if not line and lines:
            break
        if line:
            lines.append(line)
        elif not lines:
            break
    return "\n".join(lines)


_MAX_DIRECTION_REGEN_ATTEMPTS = 5


def generate_directions(
    repo_root: Path,
    config: ColonyConfig,
    user_goals: str,
    *,
    verbose: bool = False,
) -> str | None:
    """Run the directions generation agent and return the generated document.

    Returns None if the agent fails or produces no output.
    Allows up to ``_MAX_DIRECTION_REGEN_ATTEMPTS`` regeneration cycles.
    """
    from colonyos.agent import run_phase_sync
    from colonyos.directions import (
        build_directions_gen_prompt,
        display_directions,
        load_directions,
        save_directions,
    )
    from colonyos.ui import PhaseUI

    goals = user_goals
    previous = load_directions(repo_root)

    for attempt in range(_MAX_DIRECTION_REGEN_ATTEMPTS):
        console.print()
        console.print(
            "  [bold]Generating strategic directions…[/bold]\n"
            "  [dim]researching similar projects and best practices[/dim]",
            highlight=False,
        )

        system, user = build_directions_gen_prompt(
            config, goals, repo_root, existing_directions=previous,
        )

        ui = PhaseUI(verbose=verbose)

        ui.phase_header(
            "Directions",
            min(config.budget.per_phase, 2.0),
            config.get_model(Phase.CEO),
            extra="research & synthesis",
        )

        try:
            result = run_phase_sync(
                Phase.CEO,
                user,
                cwd=repo_root,
                system_prompt=system,
                model=config.get_model(Phase.CEO),
                budget_usd=min(config.budget.per_phase, 2.0),
                allowed_tools=["Read", "Glob", "Grep", "Bash"],
                ui=ui,
            )
        except Exception as exc:
            console.print(f"\n  [red]✗[/red] Directions generation failed: {exc}", highlight=False)
            console.print("  [dim]You can generate directions later with[/dim] [green]colonyos directions[/green]", highlight=False)
            return None

        content = result.artifacts.get("result", "")
        if not result.success or not content.strip():
            console.print(
                "\n  [red]✗[/red] Directions generation produced no output.\n"
                "  [dim]You can try again with[/dim] [green]colonyos directions[/green]",
                highlight=False,
            )
            return None

        display_directions(content)

        if click.confirm(
            f"\n  {_ARROW} Approve these directions?",
            default=True,
        ):
            save_directions(repo_root, content)
            console.print("  [green]✓[/green] Directions saved to .colonyos/directions.md", highlight=False)
            return content

        if attempt < _MAX_DIRECTION_REGEN_ATTEMPTS - 1 and click.confirm(
            f"  {_ARROW} Edit goals and regenerate?",
            default=False,
        ):
            new_goals = _collect_strategic_goals()
            if new_goals.strip():
                goals = new_goals
            else:
                console.print("  [dim](no new goals entered — reusing previous goals)[/dim]", highlight=False)
            continue

        break

    console.print(
        "  [dim]Directions skipped. You can generate them later with[/dim] "
        "[green]colonyos directions[/green]",
        highlight=False,
    )
    return None


def run_init(
    repo_root: Path,
    *,
    personas_only: bool = False,
    quick: bool = False,
    project_name: str | None = None,
    project_description: str | None = None,
    project_stack: str | None = None,
    doctor_check: bool = False,
    defaults: RepoContext | None = None,
) -> ColonyConfig:
    """Interactive init flow: collect project info + personas, save config.

    When ``quick=True``, skip all interactive prompts and use first persona
    pack with default config values.  ``project_name``, ``project_description``,
    and ``project_stack`` supply the required project info in quick mode.

    When ``defaults`` is provided (from AI-assisted fallback), its values are
    used as pre-filled defaults in the interactive prompts.
    """
    # --- Doctor pre-check ---
    if doctor_check:
        from colonyos.doctor import run_doctor_checks

        checks = run_doctor_checks(repo_root)
        hard_prereqs = {"Python ≥ 3.11", "Claude Code CLI", "Git"}
        failures = [name for name, ok, _ in checks if not ok and name in hard_prereqs]
        if failures:
            raise click.ClickException(
                f"Missing prerequisite(s): {', '.join(failures)}. "
                f"Run `colonyos doctor` for details."
            )

    existing = load_config(repo_root)

    if quick:
        if not project_name:
            raise click.ClickException(
                "Project name is required for --quick init. "
                "Use --name to specify it."
            )

        project = ProjectInfo(
            name=project_name,
            description=project_description or "",
            stack=project_stack or "",
        )
        personas = list(PACKS[0].personas)

        cost_preset = MODEL_PRESETS["Cost-optimized"]
        config = replace(
            existing,
            project=project,
            personas=personas,
            model=cost_preset["model"],
            phase_models=dict(cost_preset["phase_models"]),
        )

    elif personas_only:
        personas = _collect_personas_with_packs(existing.personas)
        config = replace(existing, personas=personas)
    else:
        project = collect_project_info(defaults=defaults)
        personas = _collect_personas_with_packs(
            existing.personas if existing.personas else None,
        )

        _section("Strategic Direction")
        vision = _prompt(
            "Project vision and priorities (optional, Enter to skip)",
            default="",
        )

        _section("Configuration", "model & budget")

        preset_names = list(MODEL_PRESETS.keys())
        for i, name in enumerate(preset_names, 1):
            console.print(
                f"  [bold bright_cyan]{i}[/bold bright_cyan]. [bold]{name}[/bold]",
                highlight=False,
            )
        preset_choice = click.prompt(
            f"  {_ARROW} Select a model preset",
            type=click.IntRange(1, len(preset_names)),
            default=1,
            prompt_suffix=" ",
        )
        chosen_preset = MODEL_PRESETS[preset_names[preset_choice - 1]]
        model = chosen_preset["model"]
        phase_models = dict(chosen_preset["phase_models"])

        budget_phase = click.prompt(
            f"  {_ARROW} Budget per phase (USD)",
            default=existing.budget.per_phase, type=float,
            prompt_suffix=" ",
        )
        budget_run = click.prompt(
            f"  {_ARROW} Budget per run (USD)",
            default=existing.budget.per_run, type=float,
            prompt_suffix=" ",
        )

        config = replace(
            existing,
            project=project,
            personas=personas,
            model=model,
            phase_models=phase_models,
            budget=replace(existing.budget, per_phase=budget_phase, per_run=budget_run),
            vision=vision,
        )

    return _finalize_init(repo_root, config, personas_only=personas_only, quick=quick)


def _finalize_init(
    repo_root: Path,
    config: ColonyConfig,
    *,
    personas_only: bool = False,
    quick: bool = False,
) -> ColonyConfig:
    """Save config, create directories, update .gitignore, print summary."""
    config_path = save_config(repo_root, config)

    prds_dir = repo_root / config.prds_dir
    tasks_dir = repo_root / config.tasks_dir
    reviews_dir = repo_root / config.reviews_dir
    proposals_dir = repo_root / config.proposals_dir
    prds_dir.mkdir(parents=True, exist_ok=True)
    tasks_dir.mkdir(parents=True, exist_ok=True)
    reviews_dir.mkdir(parents=True, exist_ok=True)
    # Create review subdirectories with .gitkeep files
    for subdir in ("decisions", "reviews"):
        sub = reviews_dir / subdir
        sub.mkdir(parents=True, exist_ok=True)
        gitkeep = sub / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()
    proposals_dir.mkdir(parents=True, exist_ok=True)

    # Warn if old non-prefixed directories exist alongside new cOS_ dirs
    for old_name, new_name in [("prds", config.prds_dir), ("tasks", config.tasks_dir)]:
        old_dir = repo_root / old_name
        if old_dir.exists() and old_name != new_name:
            console.print(
                f"  [yellow]⚠[/yellow] old [bold]{old_name}/[/bold] exists alongside "
                f"[bold]{new_name}/[/bold] — consider migrating",
                highlight=False,
            )

    gitignore = repo_root / ".gitignore"
    entries_needed = [
        ".colonyos/runs/",
        ".colonyos/queue.json",
        ".colonyos/memory.db",
        ".colonyos/daemon_state.json",
        ".colonyos/logs/",
        ".colonyos/recovery/",
    ]
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        additions = [e for e in entries_needed if e not in content]
        if additions:
            with gitignore.open("a", encoding="utf-8") as f:
                for entry in additions:
                    f.write(f"\n{entry}")
                f.write("\n")
    else:
        gitignore.write_text("\n".join(entries_needed) + "\n", encoding="utf-8")

    _section("Setup Complete")
    console.print(f"  [green]✓[/green] Config saved to [bold]{config_path}[/bold]", highlight=False)
    console.print(
        f"  [green]✓[/green] Created [bold]{config.prds_dir}/[/bold], "
        f"[bold]{config.tasks_dir}/[/bold], [bold]{config.reviews_dir}/[/bold], "
        f"[bold]{config.proposals_dir}/[/bold]",
        highlight=False,
    )
    console.print(
        f"  [green]✓[/green] Defined [bold]{len(config.personas)}[/bold] personas",
        highlight=False,
    )

    # --- Strategic Directions generation ---
    if not personas_only and not quick:
        from colonyos.directions import directions_path

        existing_directions = directions_path(repo_root)
        generate = True
        if existing_directions.exists():
            if not click.confirm(
                f"\n  {_ARROW} Existing directions found. Regenerate?",
                default=False,
            ):
                generate = False

        if generate:
            goals = _collect_strategic_goals()
            if goals.strip():
                generate_directions(repo_root, config, goals)
            else:
                console.print(
                    "\n  [dim]No goals provided — skipping directions generation.\n"
                    "  Run[/dim] [green]colonyos directions[/green] [dim]later to create them.[/dim]",
                    highlight=False,
                )

        if existing_directions.exists():
            auto_update = click.confirm(
                f"\n  {_ARROW} Auto-update directions after each CEO iteration?",
                default=config.directions_auto_update,
            )
            if auto_update != config.directions_auto_update:
                config.directions_auto_update = auto_update
                save_config(repo_root, config)

    console.print(
        '\n  [dim]Next step:[/dim]  [green bold]colonyos run "Add a health check endpoint"[/green bold]\n',
        highlight=False,
    )

    return config
