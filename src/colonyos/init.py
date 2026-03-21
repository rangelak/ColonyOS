from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.table import Table
from rich.text import Text

from colonyos.config import (
    ColonyConfig,
    BudgetConfig,
    PhasesConfig,
    config_dir_path,
    load_config,
    save_config,
)
from colonyos.models import Persona, Phase, ProjectInfo
from colonyos.persona_packs import PACKS, get_pack
from colonyos.ui import console


MODEL_PRESETS: dict[str, dict[str, str | dict[str, str]]] = {
    "Quality-first": {
        "model": "opus",
        "phase_models": {},
    },
    "Cost-optimized": {
        "model": "sonnet",
        "phase_models": {
            "implement": "opus",
            "learn": "haiku",
            "deliver": "haiku",
        },
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


def collect_project_info() -> ProjectInfo:
    _section("Project Info")
    name = _prompt("Project name")
    description = _prompt("Brief description (what does this project do?)")
    stack = _prompt("Tech stack (e.g. Python/FastAPI, React, PostgreSQL)")
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
) -> ColonyConfig:
    """Interactive init flow: collect project info + personas, save config.

    When ``quick=True``, skip all interactive prompts and use first persona
    pack with default config values.  ``project_name``, ``project_description``,
    and ``project_stack`` supply the required project info in quick mode.
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

        from colonyos.config import DEFAULTS
        cost_preset = MODEL_PRESETS["Cost-optimized"]
        config = ColonyConfig(
            project=project,
            personas=personas,
            model=cost_preset["model"],
            phase_models=dict(cost_preset["phase_models"]),
            budget=BudgetConfig(
                per_phase=DEFAULTS["budget"]["per_phase"],
                per_run=DEFAULTS["budget"]["per_run"],
                max_duration_hours=DEFAULTS["budget"]["max_duration_hours"],
                max_total_usd=DEFAULTS["budget"]["max_total_usd"],
            ),
            phases=PhasesConfig(),
            branch_prefix=existing.branch_prefix,
            prds_dir=existing.prds_dir,
            tasks_dir=existing.tasks_dir,
            reviews_dir=existing.reviews_dir,
            proposals_dir=existing.proposals_dir,
        )

    elif personas_only:
        personas = _collect_personas_with_packs(existing.personas)
        config = ColonyConfig(
            project=existing.project,
            personas=personas,
            model=existing.model,
            budget=existing.budget,
            phases=existing.phases,
            branch_prefix=existing.branch_prefix,
            prds_dir=existing.prds_dir,
            tasks_dir=existing.tasks_dir,
            reviews_dir=existing.reviews_dir,
            proposals_dir=existing.proposals_dir,
            ceo_persona=existing.ceo_persona,
            vision=existing.vision,
        )
    else:
        project = collect_project_info()
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

        config = ColonyConfig(
            project=project,
            personas=personas,
            model=model,
            phase_models=phase_models,
            budget=BudgetConfig(per_phase=budget_phase, per_run=budget_run),
            phases=PhasesConfig(),
            branch_prefix=existing.branch_prefix,
            prds_dir=existing.prds_dir,
            tasks_dir=existing.tasks_dir,
            reviews_dir=existing.reviews_dir,
            proposals_dir=existing.proposals_dir,
            ceo_persona=existing.ceo_persona,
            vision=vision,
        )

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
    entries_needed = [".colonyos/runs/", "cOS_*/"]
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
