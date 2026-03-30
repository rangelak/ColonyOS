"""Cleanup command group: branches, artifacts, scan (with optional AI analysis)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import click

from colonyos.cli._app import app
from colonyos.cli._helpers import _find_repo_root
from colonyos.config import ColonyConfig, load_config, runs_dir_path
from colonyos.models import PreflightError
from colonyos.orchestrator import run as run_orchestrator


@app.group(invoke_without_command=True)
@click.pass_context
def cleanup(ctx: click.Context) -> None:
    """Codebase hygiene: prune branches, clean artifacts, scan for complexity."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cleanup.command("branches")
@click.option("--execute", is_flag=True, help="Actually delete branches (default: dry-run).")
@click.option("--include-remote", is_flag=True, help="Also prune merged branches from origin.")
@click.option("--all-branches", is_flag=True, help="Include all merged branches, not just colonyos/ prefix.")
@click.option("--prefix", default=None, help="Branch prefix to filter (default: from config).")
def cleanup_branches(
    execute: bool,
    include_remote: bool,
    all_branches: bool,
    prefix: str | None,
) -> None:
    """List and prune merged branches."""
    from rich.console import Console
    from rich.table import Table

    from colonyos.cleanup import (
        list_merged_branches,
        delete_branches,
        write_cleanup_log,
    )

    repo_root = _find_repo_root()
    config = load_config(repo_root)
    branch_prefix = prefix if prefix is not None else config.branch_prefix

    branches = list_merged_branches(
        repo_root,
        prefix=branch_prefix,
        include_all=all_branches,
    )

    if not branches:
        click.echo("No merged branches found to clean up.")
        return

    result = delete_branches(
        branches,
        repo_root,
        include_remote=include_remote,
        execute=execute,
    )

    con = Console()
    mode = "EXECUTED" if execute else "DRY-RUN"

    # Display results table
    table = Table(
        title=f"Branch Cleanup [{mode}]",
        show_header=True,
        header_style="bold",
        padding=(0, 2),
    )
    table.add_column("Branch", style="cyan")
    table.add_column("Last Commit", style="dim")
    table.add_column("Action", justify="center")

    for name in result.deleted_local:
        table.add_row(name, "", "[green]delete[/green]" if execute else "[yellow]would delete[/yellow]")

    for info in result.skipped:
        table.add_row(info.name, info.last_commit_date, f"[dim]skip ({info.skip_reason})[/dim]")

    con.print(table)

    # Summary
    click.echo(
        f"\n{len(result.deleted_local)} local branch(es) {'deleted' if execute else 'would be deleted'}"
    )
    if include_remote:
        click.echo(
            f"{len(result.deleted_remote)} remote branch(es) {'deleted' if execute else 'would be deleted'}"
        )
    if result.skipped:
        click.echo(f"{len(result.skipped)} branch(es) skipped")
    for err in result.errors:
        click.echo(f"  Error: {err}", err=True)

    if not execute and result.deleted_local:
        click.echo("\nRe-run with --execute to delete.")

    # Audit log
    log_data = {
        "deleted_local": result.deleted_local,
        "deleted_remote": result.deleted_remote,
        "skipped": [{"name": s.name, "reason": s.skip_reason} for s in result.skipped],
        "errors": result.errors,
        "execute": execute,
    }
    write_cleanup_log(runs_dir_path(repo_root), "branches", log_data)


@cleanup.command("artifacts")
@click.option("--execute", is_flag=True, help="Actually delete artifacts (default: dry-run).")
@click.option("--retention-days", type=int, default=None, help="Override retention period in days.")
def cleanup_artifacts(
    execute: bool,
    retention_days: int | None,
) -> None:
    """Remove old run artifacts beyond the retention period."""
    from rich.console import Console
    from rich.table import Table

    from colonyos.cleanup import (
        list_stale_artifacts,
        delete_artifacts,
        write_cleanup_log,
    )

    repo_root = _find_repo_root()
    config = load_config(repo_root)
    days = retention_days if retention_days is not None else config.cleanup.artifact_retention_days
    runs_dir = runs_dir_path(repo_root)

    stale, skipped = list_stale_artifacts(runs_dir, retention_days=days)

    if not stale:
        click.echo(f"No stale artifacts found (retention: {days} days).")
        return

    result = delete_artifacts(stale, execute=execute)

    con = Console()
    mode = "EXECUTED" if execute else "DRY-RUN"

    table = Table(
        title=f"Artifact Cleanup [{mode}]",
        show_header=True,
        header_style="bold",
        padding=(0, 2),
    )
    table.add_column("Run ID", style="cyan")
    table.add_column("Date", style="dim")
    table.add_column("Status")
    table.add_column("Size", justify="right")

    for artifact in result.removed:
        size_kb = artifact.size_bytes / 1024
        table.add_row(
            artifact.run_id,
            artifact.date[:10] if len(artifact.date) >= 10 else artifact.date,
            artifact.status,
            f"{size_kb:.1f} KB",
        )

    con.print(table)

    total_mb = result.bytes_reclaimed / (1024 * 1024)
    click.echo(
        f"\n{len(result.removed)} artifact(s) {'removed' if execute else 'would be removed'}, "
        f"{total_mb:.2f} MB {'reclaimed' if execute else 'reclaimable'}"
    )
    for err in result.errors:
        click.echo(f"  Error: {err}", err=True)

    if not execute and result.removed:
        click.echo("\nRe-run with --execute to delete.")

    # Audit log
    log_data = {
        "removed": [{"run_id": a.run_id, "size_bytes": a.size_bytes} for a in result.removed],
        "bytes_reclaimed": result.bytes_reclaimed,
        "errors": result.errors,
        "execute": execute,
        "retention_days": days,
    }
    write_cleanup_log(runs_dir, "artifacts", log_data)


def _run_cleanup_scan_impl(
    repo_root: Path,
    config: ColonyConfig,
    *,
    max_lines: int | None,
    max_functions: int | None,
    use_ai: bool,
    refactor_file: str | None,
) -> None:
    """Shared implementation for CLI and TUI cleanup scans."""
    import logging

    from rich.console import Console
    from rich.table import Table

    from colonyos.cleanup import (
        scan_directory,
        synthesize_refactor_prompt,
        write_cleanup_log,
    )
    from colonyos.cli._legacy import _print_run_summary

    logger = logging.getLogger(__name__)

    lines_threshold = max_lines if max_lines is not None else config.cleanup.scan_max_lines
    funcs_threshold = max_functions if max_functions is not None else config.cleanup.scan_max_functions

    # If --refactor, synthesize prompt and delegate to colonyos run
    if refactor_file:
        results = scan_directory(repo_root, lines_threshold, funcs_threshold)
        prompt = synthesize_refactor_prompt(refactor_file, scan_results=results)
        click.echo(f"Delegating refactoring to `colonyos run`:\n\n{prompt}\n")
        try:
            log = run_orchestrator(
                prompt,
                repo_root=repo_root,
                config=config,
            )
            _print_run_summary(log)
        except PreflightError as exc:
            click.echo(f"Preflight error: {exc.format_message()}", err=True)
            sys.exit(1)
        return

    results = scan_directory(repo_root, lines_threshold, funcs_threshold)

    con = Console()

    if not results:
        click.echo(
            f"No files exceed thresholds (lines > {lines_threshold}, functions > {funcs_threshold})."
        )
        return

    table = Table(
        title="Structural Scan Results",
        show_header=True,
        header_style="bold",
        padding=(0, 2),
    )
    table.add_column("File", style="cyan")
    table.add_column("Lines", justify="right")
    table.add_column("Functions", justify="right")
    table.add_column("Category", justify="center")

    category_styles = {
        "large": "yellow",
        "very-large": "bold yellow",
        "massive": "bold red",
    }

    for fc in results:
        cat_style = category_styles.get(fc.category.value, "")
        cat_display = f"[{cat_style}]{fc.category.value}[/{cat_style}]"
        table.add_row(
            fc.path,
            str(fc.line_count),
            str(fc.function_count),
            cat_display,
        )

    con.print(table)
    click.echo(f"\n{len(results)} file(s) flagged.")

    # Audit log
    log_data = {
        "files_flagged": len(results),
        "thresholds": {"max_lines": lines_threshold, "max_functions": funcs_threshold},
        "results": [
            {"path": r.path, "lines": r.line_count, "functions": r.function_count, "category": r.category.value}
            for r in results
        ],
    }
    write_cleanup_log(runs_dir_path(repo_root), "scan", log_data)

    # AI scan
    if use_ai:
        click.echo("\nRunning AI structural analysis...")
        try:
            from colonyos.agent import run_phase_sync
            from colonyos.models import Phase

            instructions_dir = Path(__file__).parent / "instructions"
            base_prompt = (instructions_dir / "base.md").read_text(encoding="utf-8")
            scan_prompt = (instructions_dir / "cleanup_scan.md").read_text(encoding="utf-8")
            system_prompt = base_prompt + "\n\n" + scan_prompt

            scan_summary = "\n".join(
                f"- `{r.path}`: {r.line_count} lines, {r.function_count} functions ({r.category.value})"
                for r in results
            )
            prompt = (
                f"Analyze this codebase for structural issues. "
                f"The static scan found these files exceeding thresholds:\n\n{scan_summary}\n\n"
                f"Perform a deep qualitative analysis of the codebase."
            )

            phase_result = run_phase_sync(
                phase=Phase.REVIEW,
                prompt=prompt,
                cwd=repo_root,
                system_prompt=system_prompt,
                model=config.get_model(Phase.REVIEW),
                budget_usd=config.budget.per_phase,
                allowed_tools=["Read", "Glob", "Grep", "Agent"],
            )

            if phase_result.success and phase_result.artifacts.get("result"):
                report = phase_result.artifacts["result"]
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                report_path = runs_dir_path(repo_root) / f"cleanup_{timestamp}.md"
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(report, encoding="utf-8")
                click.echo(f"\nAI analysis report saved to: {report_path}")
            else:
                error = phase_result.error or "Unknown error"
                click.echo(f"\nAI scan failed: {error[:200]}", err=True)

        except Exception as exc:
            click.echo(f"\nAI scan error: {exc}", err=True)


@cleanup.command("scan")
@click.option("--max-lines", type=int, default=None, help="Line count threshold (default: from config).")
@click.option("--max-functions", type=int, default=None, help="Function count threshold (default: from config).")
@click.option("--ai", "use_ai", is_flag=True, help="Run AI-powered qualitative analysis (uses budget).")
@click.option("--refactor", "refactor_file", type=click.Path(), default=None, help="Delegate refactoring of FILE to colonyos run.")
def cleanup_scan(
    max_lines: int | None,
    max_functions: int | None,
    use_ai: bool,
    refactor_file: str | None,
) -> None:
    """Scan codebase for structural complexity."""
    repo_root = _find_repo_root()
    config = load_config(repo_root)
    _run_cleanup_scan_impl(
        repo_root,
        config,
        max_lines=max_lines,
        max_functions=max_functions,
        use_ai=use_ai,
        refactor_file=refactor_file,
    )
