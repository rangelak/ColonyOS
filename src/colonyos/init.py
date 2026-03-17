from __future__ import annotations

import sys
from pathlib import Path

import click

from colonyos.config import (
    ColonyConfig,
    BudgetConfig,
    PhasesConfig,
    config_dir_path,
    load_config,
    save_config,
)
from colonyos.models import Persona, ProjectInfo
from colonyos.persona_packs import PACKS, get_pack


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


def _prompt(text: str, default: str = "") -> str:
    return click.prompt(text, default=default, show_default=bool(default))


def collect_project_info() -> ProjectInfo:
    click.echo("\n--- Project Info ---\n")
    name = _prompt("Project name")
    description = _prompt("Brief description (what does this project do?)")
    stack = _prompt("Tech stack (e.g. Python/FastAPI, React, PostgreSQL)")
    return ProjectInfo(name=name, description=description, stack=stack)


def select_persona_pack() -> list[Persona] | None:
    """Present a menu of prebuilt persona packs and return the selected personas.

    Returns the list of Persona instances from the chosen pack, or None if
    the user selects "Custom (define your own)".
    """
    click.echo("\n--- Persona Packs ---")
    click.echo("Choose a prebuilt persona pack or define your own.\n")

    for i, pack in enumerate(PACKS, 1):
        click.echo(f"  {i}. {pack.name} — {pack.description}")
    custom_index = len(PACKS) + 1
    click.echo(f"  {custom_index}. Custom (define your own)")

    choice = click.prompt(
        "\nSelect a pack",
        type=click.IntRange(1, custom_index),
        default=1,
    )

    if choice == custom_index:
        return None

    pack = PACKS[choice - 1]

    click.echo(f"\n  {pack.name}:")
    for i, persona in enumerate(pack.personas, 1):
        click.echo(f"    {i}. {persona.role} — {persona.expertise}")

    if not click.confirm(f"\nUse these {len(pack.personas)} personas?", default=True):
        return None

    return list(pack.personas)


def collect_personas(existing: list[Persona] | None = None) -> list[Persona]:
    click.echo("\n--- Agent Personas ---")
    click.echo(
        "Define the expert personas who will review feature PRDs.\n"
        "Each persona has a role, area of expertise, and a perspective they bring.\n"
        "You'll typically want 3-5 personas.\n"
    )

    personas: list[Persona] = []

    if existing:
        click.echo("Current personas:")
        for i, p in enumerate(existing, 1):
            click.echo(f"  {i}. {p.role} — {p.expertise}")
        if click.confirm("\nKeep existing personas and add more?", default=True):
            personas = list(existing)

    while True:
        click.echo(f"\n--- Persona {len(personas) + 1} ---")
        role = _prompt("Role (e.g. Senior Backend Engineer, Product Lead)")
        expertise = _prompt("Expertise (e.g. API design, user research)")
        perspective = _prompt(
            "Perspective (what does this person think about?)",
            default="",
        )
        is_reviewer = click.confirm(
            "Should this persona participate in code reviews?", default=True
        )
        personas.append(Persona(role=role, expertise=expertise, perspective=perspective, reviewer=is_reviewer))

        if len(personas) >= 3 and not click.confirm("Add another persona?", default=len(personas) < 5):
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

    if click.confirm("Add custom personas on top?", default=False):
        return collect_personas(existing=pack_personas)

    return pack_personas


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

        click.echo("\n--- Strategic Direction ---\n")
        vision = _prompt(
            "Describe your project's vision and priorities (optional, press Enter to skip)",
            default="",
        )

        click.echo("\n--- Configuration ---\n")

        click.echo("Model presets:")
        preset_names = list(MODEL_PRESETS.keys())
        for i, name in enumerate(preset_names, 1):
            click.echo(f"  {i}. {name}")
        preset_choice = click.prompt(
            "Select a model preset",
            type=click.IntRange(1, len(preset_names)),
            default=1,
        )
        chosen_preset = MODEL_PRESETS[preset_names[preset_choice - 1]]
        model = chosen_preset["model"]
        phase_models = dict(chosen_preset["phase_models"])

        budget_phase = click.prompt(
            "Budget per phase (USD)", default=existing.budget.per_phase, type=float
        )
        budget_run = click.prompt(
            "Budget per run (USD)", default=existing.budget.per_run, type=float
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
    proposals_dir.mkdir(parents=True, exist_ok=True)

    # Warn if old non-prefixed directories exist alongside new cOS_ dirs
    for old_name, new_name in [("prds", config.prds_dir), ("tasks", config.tasks_dir)]:
        old_dir = repo_root / old_name
        if old_dir.exists() and old_name != new_name:
            click.echo(
                f"Warning: old '{old_name}/' directory exists alongside '{new_name}/'. "
                f"Consider migrating your files.",
                err=True,
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

    click.echo(f"\nConfig saved to {config_path}")
    click.echo(f"Created {prds_dir}/, {tasks_dir}/, {reviews_dir}/, and {proposals_dir}/ directories")
    click.echo(f"Defined {len(config.personas)} personas")
    click.echo('\nNext step:\n  colonyos run "Add a health check endpoint"')

    return config
