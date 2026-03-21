"""CEO Directions: a living strategy document that evolves with each iteration.

The directions file (.colonyos/directions.md) is a persistent context layer
for the CEO phase — inspired by mem0's evolving memory and gstack's separation
of CEO-level product taste from engineering execution.

It gets generated during init (user input + LLM research), reviewed by the CEO
before each proposal, and updated after each iteration with fresh insights.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from colonyos.config import ColonyConfig

DIRECTIONS_FILE = "directions.md"
_MAX_DIRECTIONS_LEN = 3000


def directions_path(repo_root: Path) -> Path:
    return repo_root / ".colonyos" / DIRECTIONS_FILE


def load_directions(repo_root: Path) -> str:
    """Load the current directions document, or return empty string."""
    path = directions_path(repo_root)
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8")
    if len(content) > _MAX_DIRECTIONS_LEN:
        content = content[:_MAX_DIRECTIONS_LEN] + "\n\n_(truncated)_\n"
    return content


def save_directions(repo_root: Path, content: str) -> Path:
    path = directions_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _load_instruction(name: str) -> str:
    """Load a markdown instruction template from the instructions directory."""
    instructions_dir = Path(__file__).parent / "instructions"
    path = instructions_dir / name
    if not path.exists():
        raise FileNotFoundError(f"Instruction template not found: {path}")
    return path.read_text(encoding="utf-8")


def build_directions_gen_prompt(
    config: "ColonyConfig",
    user_goals: str,
    repo_root: Path,
    *,
    existing_directions: str = "",
) -> tuple[str, str]:
    """Build system + user prompts for the directions generation agent.

    The agent receives project context and user goals, and is expected to
    produce a concise strategic directions document. If ``existing_directions``
    is provided, the agent uses it as a starting point to improve upon.
    """
    system = _load_instruction("directions_gen.md")

    readme_text = ""
    readme_path = repo_root / "README.md"
    if readme_path.exists():
        readme_text = readme_path.read_text(encoding="utf-8")[:4000]

    changelog_text = ""
    changelog_path = repo_root / "CHANGELOG.md"
    if changelog_path.exists():
        changelog_text = changelog_path.read_text(encoding="utf-8")[:3000]

    project_name = config.project.name if config.project else "Unknown"
    project_desc = config.project.description if config.project else ""
    project_stack = config.project.stack if config.project else ""

    user = (
        f"## Project Context\n\n"
        f"- **Name**: {project_name}\n"
        f"- **Description**: {project_desc}\n"
        f"- **Stack**: {project_stack}\n"
        f"- **Vision**: {config.vision or 'Not set'}\n\n"
    )

    if user_goals.strip():
        user += (
            f"## User's North Star\n\n"
            f"The user said this about where they want the project to go:\n\n"
            f"{user_goals.strip()}\n\n"
            f"Include this verbatim in the \"User's North Star\" section of the "
            f"output, then build the rest of the landscape around it.\n\n"
        )

    if existing_directions.strip():
        user += (
            f"## Previous Directions Document\n\n"
            f"Here is the existing directions document. Use it as a starting point — "
            f"keep what's still relevant, improve what's weak, and replace anything "
            f"stale with fresh research. Don't just copy it verbatim.\n\n"
            f"{existing_directions.strip()}\n\n---\n\n"
        )

    if readme_text:
        user += f"## README\n\n{readme_text}\n\n---\n\n"

    if changelog_text:
        user += f"## Development History\n\n{changelog_text}\n\n---\n\n"

    user += (
        "Research the landscape around this project. Find 5-8 similar or adjacent "
        "repos on GitHub, look at what makes the best ones great, and produce the "
        "directions document in the format specified in your instructions. "
        "Remember: this is a landscape map, not a task list."
    )

    return system, user


def build_directions_update_prompt(
    config: "ColonyConfig",
    current_directions: str,
    ceo_proposal: str,
    iteration: int,
    repo_root: Path,
) -> tuple[str, str]:
    """Build prompts for the post-CEO directions update agent.

    Keeps the document fresh by incorporating what the CEO just proposed.
    """
    project_name = config.project.name if config.project else "Unknown"

    system = (
        "You are a strategic analyst maintaining a landscape/inspiration document "
        "for an autonomous CEO agent. After each CEO iteration, you lightly "
        "refresh the document to keep it relevant.\n\n"
        "Rules:\n"
        "- Keep the same markdown structure and section headings\n"
        "- Update the iteration count and timestamp in the header\n"
        "- If the CEO just proposed something inspired by a listed project, "
        "add a brief note about what was drawn from it\n"
        "- If the proposal reveals a new adjacent project or pattern worth "
        "knowing about, add it\n"
        "- Keep total length under 90 lines — the CEO reads this every iteration\n"
        "- Do NOT turn this into a task list or changelog — it stays a landscape doc\n"
        "- Preserve the document's opinionated voice and specific pointers\n"
        "- Output ONLY the updated directions document, no commentary"
    )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    user = (
        f"## Current Directions (iteration {iteration - 1})\n\n"
        f"{current_directions}\n\n---\n\n"
        f"## CEO Proposal Just Generated (iteration {iteration})\n\n"
        f"{ceo_proposal}\n\n---\n\n"
        f"Update the directions document. Set iteration to {iteration} and "
        f"timestamp to {now}. Project: {project_name}."
    )

    return system, user


def display_directions(content: str, title: str = "Strategic Directions") -> None:
    """Render directions in a Rich panel via the shared UI console."""
    from rich.markdown import Markdown
    from rich.panel import Panel

    from colonyos.ui import console

    console.print()
    console.print(
        Panel(
            Markdown(content),
            title=f"[bold]{title}[/bold]",
            title_align="left",
            border_style="bright_black",
            padding=(1, 2),
            expand=True,
        )
    )


def parse_iteration_from_directions(content: str) -> int:
    """Extract the iteration number from the directions header line."""
    match = re.search(r"_Generated:.*?Iteration:\s*(\d+)\s*_", content)
    if match:
        return int(match.group(1))
    return 0
