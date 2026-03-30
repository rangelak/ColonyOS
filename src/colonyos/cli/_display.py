"""Display helpers — formatted summaries for runs, reviews, and queues.

These functions use Rich for rendering and are imported lazily where needed
so that ``import colonyos.cli`` stays fast.
"""

from __future__ import annotations

import click

from colonyos.models import (
    QueueItem,
    QueueItemStatus,
    QueueState,
    RunLog,
    RunStatus,
)
from colonyos.orchestrator import extract_review_verdict


def _print_run_summary(log: RunLog) -> None:
    """Print a formatted run summary to stdout."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    con = Console()

    status_style = "green" if log.status == RunStatus.COMPLETED else "red"
    status_icon = "\u2713" if log.status == RunStatus.COMPLETED else "\u2717"

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Phase", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Cost", justify="right")
    table.add_column("Duration", justify="right")

    for phase in log.phases:
        if phase.success:
            st = Text("\u2713 ok", style="green")
        else:
            st = Text("\u2717 FAIL", style="red bold")
        cost = f"${phase.cost_usd or 0:.2f}"
        dur_ms = phase.duration_ms or 0
        if dur_ms >= 60_000:
            mins, secs = divmod(dur_ms // 1000, 60)
            dur = f"{mins}m {secs}s"
        else:
            dur = f"{dur_ms // 1000}s"
        table.add_row(phase.phase.value, st, cost, dur)

    header = Text()
    header.append(f" {status_icon} ", style=status_style)
    header.append(log.run_id, style="bold")
    header.append(f"  \u2502  ", style="dim")
    header.append(f"${log.total_cost_usd:.2f}", style="bold cyan")
    header.append(f"  \u2502  ", style="dim")
    header.append(log.status.value, style=f"bold {status_style}")

    con.print()
    con.print(
        Panel(
            table,
            title=header,
            title_align="left",
            border_style="bright_black",
            padding=(1, 2),
            expand=True,
        )
    )


def _print_review_summary(
    phase_results: list,
    reviewers: list,
    total_cost: float,
    decision_verdict: str | None = None,
) -> None:
    """Print a formatted review summary table to stdout."""
    from colonyos.models import Phase

    click.echo(f"\n{'=' * 60}")
    click.echo("Review Summary")
    click.echo(f"{'=' * 60}")

    review_results = [r for r in phase_results if r.phase == Phase.REVIEW]
    # Match reviewers to review results (may be multiple rounds)
    num_reviewers = len(reviewers)
    if review_results and num_reviewers:
        # Show the last round of results
        last_round = review_results[-num_reviewers:]
        for persona, result in zip(reviewers, last_round):
            text = result.artifacts.get("result", "")
            verdict = extract_review_verdict(text)
            # Extract first finding line
            finding = ""
            for line in text.split("\n"):
                stripped = line.strip()
                if stripped.startswith("- [") and "]:" in stripped:
                    finding = stripped[:80]
                    break
            status = "\u2713 approve" if verdict == "approve" else "\u2717 request-changes"
            click.echo(f"  {persona.role:30s} {status}")
            if finding:
                click.echo(f"    {finding}")

    click.echo(f"\nTotal cost: ${total_cost:.4f}")

    if decision_verdict:
        click.echo(f"Decision: {decision_verdict}")

    click.echo(f"{'=' * 60}")


def _print_queue_summary(state: QueueState) -> None:
    """Print a comprehensive summary table after queue execution."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    con = Console()

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("#", style="dim", justify="right")
    table.add_column("Source", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Cost", justify="right")
    table.add_column("Duration", justify="right")
    table.add_column("PR", style="dim")

    completed = failed = rejected = 0
    total_cost = 0.0
    total_duration_ms = 0

    for idx, item in enumerate(state.items, 1):
        source = _format_queue_item_source(item)

        status_styles = {
            QueueItemStatus.COMPLETED: ("\u2713 completed", "green"),
            QueueItemStatus.FAILED: ("\u2717 failed", "red"),
            QueueItemStatus.REJECTED: ("\u2298 rejected", "yellow"),
            QueueItemStatus.PENDING: ("\u25cb pending", "dim"),
            QueueItemStatus.RUNNING: ("\u25c9 running", "blue"),
        }
        status_text, style = status_styles.get(item.status, ("?", "dim"))

        cost = f"${item.cost_usd:.2f}" if item.cost_usd else "-"
        dur_ms = item.duration_ms or 0
        if dur_ms >= 60_000:
            mins, secs = divmod(dur_ms // 1000, 60)
            dur = f"{mins}m {secs}s"
        elif dur_ms > 0:
            dur = f"{dur_ms // 1000}s"
        else:
            dur = "-"

        pr = item.pr_url or "-"

        table.add_row(
            str(idx),
            source,
            Text(status_text, style=style),
            cost,
            dur,
            pr,
        )

        if item.status == QueueItemStatus.COMPLETED:
            completed += 1
        elif item.status == QueueItemStatus.FAILED:
            failed += 1
        elif item.status == QueueItemStatus.REJECTED:
            rejected += 1
        total_cost += item.cost_usd
        total_duration_ms += item.duration_ms

    # Aggregate totals
    total_items = len(state.items)
    if total_duration_ms >= 60_000:
        t_mins, t_secs = divmod(total_duration_ms // 1000, 60)
        total_dur = f"{t_mins}m {t_secs}s"
    elif total_duration_ms > 0:
        total_dur = f"{total_duration_ms // 1000}s"
    else:
        total_dur = "-"

    header = Text()
    header.append(" Queue Summary ", style="bold")
    header.append(f" \u2502 ", style="dim")
    header.append(f"{completed} completed", style="green")
    if failed:
        header.append(f", {failed} failed", style="red")
    if rejected:
        header.append(f", {rejected} rejected", style="yellow")
    pending = total_items - completed - failed - rejected
    if pending:
        header.append(f", {pending} pending", style="dim")
    header.append(f" \u2502 ", style="dim")
    header.append(f"${total_cost:.2f} total", style="bold cyan")

    con.print()
    con.print(
        Panel(
            table,
            title=header,
            title_align="left",
            border_style="bright_black",
            padding=(1, 2),
            expand=True,
        )
    )


def _format_queue_item_source(item: QueueItem, max_len: int = 60) -> str:
    """Format a queue item's source for display."""
    if item.source_type == "issue":
        title = item.issue_title or ""
        return f"#{item.source_value} {title}"[:max_len]
    if item.source_type in ("slack", "slack_fix"):
        channel = item.slack_channel or "?"
        label = "fix" if item.source_type == "slack_fix" else "slack"
        text = item.source_value
        prefix = f"[{label}:{channel}] "
        remaining = max_len - len(prefix)
        if remaining > 0 and len(text) > remaining:
            text = text[: remaining - 3] + "..."
        return f"{prefix}{text}"[:max_len]
    text = item.source_value
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text
