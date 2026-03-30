"""Memory management commands: list, search, delete, clear, stats."""

from __future__ import annotations

import click

from colonyos.cli._app import app
from colonyos.cli._helpers import _find_repo_root
from colonyos.config import load_config


@app.group(invoke_without_command=True)
@click.pass_context
def memory(ctx: click.Context) -> None:
    """Manage the persistent memory store."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


app.add_command(memory)


@memory.command("list")
@click.option("--category", type=click.Choice(["codebase", "failure", "preference", "review_pattern"]), default=None, help="Filter by category.")
@click.option("--limit", "limit_", default=20, show_default=True, help="Max entries to show.")
def memory_list(category: str | None, limit_: int) -> None:
    """List recent memory entries."""
    from rich.console import Console
    from rich.table import Table

    from colonyos.memory import MemoryCategory, MemoryStore

    repo_root = _find_repo_root()
    config = load_config(repo_root)
    if not config.memory.enabled:
        click.echo("Memory is disabled in config (memory.enabled: false).")
        return

    with MemoryStore(repo_root, max_entries=config.memory.max_entries) as store:
        categories = [MemoryCategory(category)] if category else None
        entries = store.query_memories(categories=categories, limit=limit_)

    if not entries:
        click.echo("No memories found.")
        return

    con = Console()
    table = Table(title="Memory Entries", show_header=True, header_style="bold", padding=(0, 1))
    table.add_column("ID", style="dim", justify="right")
    table.add_column("Category", style="cyan")
    table.add_column("Phase")
    table.add_column("Text", max_width=60)
    table.add_column("Created", style="dim")

    for entry in entries:
        text_preview = entry.text[:80] + "..." if len(entry.text) > 80 else entry.text
        table.add_row(
            str(entry.id),
            entry.category.value,
            entry.phase,
            text_preview,
            entry.created_at[:19],
        )

    con.print(table)


@memory.command("search")
@click.argument("query")
@click.option("--limit", "limit_", default=20, show_default=True, help="Max results.")
def memory_search(query: str, limit_: int) -> None:
    """Search memories by keyword."""
    from rich.console import Console
    from rich.table import Table

    from colonyos.memory import MemoryStore

    repo_root = _find_repo_root()
    config = load_config(repo_root)
    if not config.memory.enabled:
        click.echo("Memory is disabled in config (memory.enabled: false).")
        return

    with MemoryStore(repo_root, max_entries=config.memory.max_entries) as store:
        entries = store.query_memories(keyword=query, limit=limit_)

    if not entries:
        click.echo(f"No memories matching '{query}'.")
        return

    con = Console()
    table = Table(title=f"Search: {query}", show_header=True, header_style="bold", padding=(0, 1))
    table.add_column("ID", style="dim", justify="right")
    table.add_column("Category", style="cyan")
    table.add_column("Text", max_width=60)

    for entry in entries:
        text_preview = entry.text[:80] + "..." if len(entry.text) > 80 else entry.text
        table.add_row(str(entry.id), entry.category.value, text_preview)

    con.print(table)


@memory.command("delete")
@click.argument("memory_id", type=int)
def memory_delete(memory_id: int) -> None:
    """Delete a memory entry by ID."""
    from colonyos.memory import MemoryStore

    repo_root = _find_repo_root()
    config = load_config(repo_root)

    with MemoryStore(repo_root, max_entries=config.memory.max_entries) as store:
        deleted = store.delete_memory(memory_id)

    if deleted:
        click.echo(f"Deleted memory #{memory_id}.")
    else:
        click.echo(f"Memory #{memory_id} not found.", err=True)
        raise SystemExit(1)


@memory.command("clear")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def memory_clear(yes: bool) -> None:
    """Delete all memory entries."""
    from colonyos.memory import MemoryStore

    repo_root = _find_repo_root()
    config = load_config(repo_root)

    if not yes:
        if not click.confirm("Delete ALL memory entries?", default=False):
            click.echo("Aborted.")
            return

    with MemoryStore(repo_root, max_entries=config.memory.max_entries) as store:
        count = store.count_memories()
        store.clear_memories()

    click.echo(f"Cleared {count} memory entries.")


@memory.command("stats")
def memory_stats() -> None:
    """Show memory store statistics."""
    from colonyos.memory import MemoryStore

    repo_root = _find_repo_root()
    config = load_config(repo_root)
    if not config.memory.enabled:
        click.echo("Memory is disabled in config (memory.enabled: false).")
        return

    with MemoryStore(repo_root, max_entries=config.memory.max_entries) as store:
        total = store.count_memories()
        by_category = store.count_by_category()

    click.echo(f"Total memories: {total} / {config.memory.max_entries}")
    click.echo(f"Token budget:   {config.memory.max_inject_tokens}")
    if by_category:
        click.echo("\nBy category:")
        for cat, count in sorted(by_category.items(), key=lambda x: x[0].value):
            click.echo(f"  {cat.value}: {count}")
    else:
        click.echo("\nNo memories stored yet.")
