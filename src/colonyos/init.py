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


def _prompt(text: str, default: str = "") -> str:
    return click.prompt(text, default=default, show_default=bool(default))


def collect_project_info() -> ProjectInfo:
    click.echo("\n--- Project Info ---\n")
    name = _prompt("Project name")
    description = _prompt("Brief description (what does this project do?)")
    stack = _prompt("Tech stack (e.g. Python/FastAPI, React, PostgreSQL)")
    return ProjectInfo(name=name, description=description, stack=stack)


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
        personas.append(Persona(role=role, expertise=expertise, perspective=perspective))

        if len(personas) >= 3 and not click.confirm("Add another persona?", default=len(personas) < 5):
            break

    return personas


def run_init(repo_root: Path, *, personas_only: bool = False) -> ColonyConfig:
    """Interactive init flow: collect project info + personas, save config."""
    existing = load_config(repo_root)

    if personas_only:
        personas = collect_personas(existing.personas)
        config = ColonyConfig(
            project=existing.project,
            personas=personas,
            model=existing.model,
            budget=existing.budget,
            phases=existing.phases,
            branch_prefix=existing.branch_prefix,
            prds_dir=existing.prds_dir,
            tasks_dir=existing.tasks_dir,
        )
    else:
        project = collect_project_info()
        personas = collect_personas(existing.personas if existing.personas else None)

        click.echo("\n--- Configuration ---\n")
        model = _prompt("Model", default=existing.model)
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
            budget=BudgetConfig(per_phase=budget_phase, per_run=budget_run),
            phases=PhasesConfig(),
            branch_prefix=existing.branch_prefix,
            prds_dir=existing.prds_dir,
            tasks_dir=existing.tasks_dir,
        )

    config_path = save_config(repo_root, config)

    prds_dir = repo_root / config.prds_dir
    tasks_dir = repo_root / config.tasks_dir
    prds_dir.mkdir(parents=True, exist_ok=True)
    tasks_dir.mkdir(parents=True, exist_ok=True)

    gitignore = repo_root / ".gitignore"
    runs_entry = ".colonyos/runs/"
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        if runs_entry not in content:
            with gitignore.open("a", encoding="utf-8") as f:
                f.write(f"\n{runs_entry}\n")
    else:
        gitignore.write_text(f"{runs_entry}\n", encoding="utf-8")

    click.echo(f"\nConfig saved to {config_path}")
    click.echo(f"Created {prds_dir}/ and {tasks_dir}/ directories")
    click.echo(f"Defined {len(config.personas)} personas")
    click.echo("\nRun `colonyos run \"<feature>\"` to start building.")

    return config
