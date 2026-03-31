"""PR outcome tracking for ColonyOS.

Tracks the fate of every PR created by ColonyOS — from creation through
merge or close — so the pipeline can learn from its delivery history.

Uses the same ``memory.db`` SQLite database as :class:`~colonyos.memory.MemoryStore`.
GitHub interactions use the ``gh`` CLI via subprocess, consistent with
``github.py``.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from colonyos.memory import MemoryCategory, MemoryStore
from colonyos.sanitize import sanitize_ci_logs

logger = logging.getLogger(__name__)

MEMORY_DB = "memory.db"

# Maximum characters for close_context extracted from reviewer comments.
_CLOSE_CONTEXT_MAX_CHARS = 500


class OutcomeStore:
    """SQLite-backed storage for PR outcome records.

    Shares ``memory.db`` with :class:`~colonyos.memory.MemoryStore` — no
    separate database file.  The ``pr_outcomes`` table is created on first
    init if it does not exist (safe to call repeatedly).

    Parameters
    ----------
    repo_root:
        Path to the repository root.  The DB lives at
        ``<repo_root>/.colonyos/memory.db``.
    """

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self._db_path = repo_root / ".colonyos" / MEMORY_DB
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    # -- Context manager protocol ------------------------------------------

    def __enter__(self) -> OutcomeStore:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()

    # -- Schema init -------------------------------------------------------

    def _init_db(self) -> None:
        """Create pr_outcomes table if it does not exist.

        Follows the same pattern as ``MemoryStore._init_db``: detect whether
        the table exists and create it if missing.  Safe to call multiple
        times (idempotent).
        """
        cur = self._conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pr_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                pr_number INTEGER NOT NULL UNIQUE,
                pr_url TEXT NOT NULL,
                branch_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                merged_at TEXT,
                closed_at TEXT,
                review_comment_count INTEGER DEFAULT 0,
                ci_passed INTEGER,
                labels TEXT DEFAULT '',
                close_context TEXT DEFAULT '',
                last_polled_at TEXT,
                last_sync_at TEXT,
                sync_failures INTEGER DEFAULT 0
            )
        """)
        self._conn.commit()
        # Migration: add sync columns to existing databases that lack them.
        self._migrate_sync_columns()

    def _migrate_sync_columns(self) -> None:
        """Add last_sync_at and sync_failures columns if missing (idempotent)."""
        cur = self._conn.cursor()
        cur.execute("PRAGMA table_info(pr_outcomes)")
        existing = {row[1] for row in cur.fetchall()}
        if "last_sync_at" not in existing:
            cur.execute("ALTER TABLE pr_outcomes ADD COLUMN last_sync_at TEXT")
        if "sync_failures" not in existing:
            cur.execute(
                "ALTER TABLE pr_outcomes ADD COLUMN sync_failures INTEGER DEFAULT 0"
            )
        self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    # -- CRUD --------------------------------------------------------------

    def track_pr(
        self,
        run_id: str,
        pr_number: int,
        pr_url: str,
        branch_name: str,
    ) -> None:
        """Register a newly created PR for outcome tracking.

        Inserts a record with status ``'open'`` and the current UTC timestamp.
        If a record for this PR number already exists, the insert is silently
        ignored (``INSERT OR IGNORE``) to prevent duplicate rows.
        """
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT OR IGNORE INTO pr_outcomes (run_id, pr_number, pr_url, branch_name, status, created_at)
            VALUES (?, ?, ?, ?, 'open', ?)
            """,
            (run_id, pr_number, pr_url, branch_name, now),
        )
        self._conn.commit()

    def get_outcomes(self) -> list[sqlite3.Row]:
        """Return all outcome records, most recent first."""
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM pr_outcomes ORDER BY created_at DESC")
        return cur.fetchall()

    def get_open_outcomes(self) -> list[sqlite3.Row]:
        """Return only outcomes with status ``'open'``."""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT * FROM pr_outcomes WHERE status = 'open' ORDER BY created_at DESC"
        )
        return cur.fetchall()

    def update_outcome(
        self,
        pr_number: int,
        status: str,
        merged_at: Optional[str] = None,
        closed_at: Optional[str] = None,
        review_comment_count: Optional[int] = None,
        ci_passed: Optional[bool] = None,
        labels: Optional[str] = None,
        close_context: Optional[str] = None,
    ) -> None:
        """Update an existing outcome record.

        Only non-None parameters are written to the database.
        ``last_polled_at`` is always updated to the current UTC time.
        """
        now = datetime.now(timezone.utc).isoformat()
        sets: list[str] = ["status = ?", "last_polled_at = ?"]
        params: list[Any] = [status, now]

        if merged_at is not None:
            sets.append("merged_at = ?")
            params.append(merged_at)
        if closed_at is not None:
            sets.append("closed_at = ?")
            params.append(closed_at)
        if review_comment_count is not None:
            sets.append("review_comment_count = ?")
            params.append(review_comment_count)
        if ci_passed is not None:
            sets.append("ci_passed = ?")
            params.append(int(ci_passed))
        if labels is not None:
            sets.append("labels = ?")
            params.append(labels)
        if close_context is not None:
            sets.append("close_context = ?")
            params.append(close_context)

        params.append(pr_number)
        self._conn.execute(
            f"UPDATE pr_outcomes SET {', '.join(sets)} WHERE pr_number = ?",
            params,
        )
        self._conn.commit()

    def update_sync_status(
        self,
        pr_number: int,
        last_sync_at: str,
        sync_failures: int,
    ) -> None:
        """Update sync tracking fields for a PR.

        Parameters
        ----------
        pr_number:
            The PR to update.
        last_sync_at:
            ISO-8601 timestamp of the sync attempt.
        sync_failures:
            Cumulative count of consecutive sync failures.
        """
        self._conn.execute(
            "UPDATE pr_outcomes SET last_sync_at = ?, sync_failures = ? WHERE pr_number = ?",
            (last_sync_at, sync_failures, pr_number),
        )
        self._conn.commit()

    def get_sync_candidates(self, max_failures: int) -> list[sqlite3.Row]:
        """Return open PRs eligible for sync, ordered oldest-synced first.

        Only returns PRs with ``sync_failures < max_failures`` and
        ``status = 'open'``.  NULLs in ``last_sync_at`` sort first
        (never-synced PRs get priority).
        """
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT * FROM pr_outcomes
            WHERE status = 'open' AND sync_failures < ?
            ORDER BY last_sync_at IS NOT NULL, last_sync_at ASC
            """,
            (max_failures,),
        )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# GitHub interaction
# ---------------------------------------------------------------------------


def _call_gh_pr_view(pr_number: int, repo_root: Path) -> dict[str, Any]:
    """Call ``gh pr view`` and return parsed JSON.

    Uses the ``gh`` CLI (validated by ``doctor.py`` preflight).
    Assumes the GitHub CLI provider (GitHub Actions state/conclusion values).

    Raises :class:`subprocess.CalledProcessError` on failure.
    """
    result = subprocess.run(
        [
            "gh", "pr", "view", str(pr_number),
            "--json", "state,mergedAt,closedAt,reviews,comments,statusCheckRollup,labels,mergeStateStatus",
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(repo_root),
    )
    return json.loads(result.stdout)


def _extract_close_context(data: dict[str, Any]) -> str:
    """Extract and sanitize close context from the last comment or review.

    Returns a sanitized, length-capped string.  Empty if no comments/reviews.
    """
    # Prefer the last comment, fall back to the last review body
    comments = data.get("comments") or []
    reviews = data.get("reviews") or []

    last_text = ""
    if comments:
        last_text = comments[-1].get("body", "")
    elif reviews:
        last_text = reviews[-1].get("body", "")

    if not last_text:
        return ""

    # Sanitize untrusted content: strip XML tags + redact secrets
    sanitized = sanitize_ci_logs(last_text)
    # Cap at 500 characters to prevent memory budget abuse
    return sanitized[:_CLOSE_CONTEXT_MAX_CHARS]


def _extract_ci_passed(data: dict[str, Any]) -> Optional[bool]:
    """Determine overall CI pass/fail from statusCheckRollup.

    Returns True if all completed checks passed, False if any failed,
    None if no checks exist or any check is still in progress
    (conclusion is None/empty — GitHub Actions sets this while running).

    Assumes GitHub Actions as the CI provider (SUCCESS/NEUTRAL/SKIPPED
    are the passing conclusion values).
    """
    checks = data.get("statusCheckRollup") or []
    if not checks:
        return None

    # Filter out in-progress checks (conclusion is None or empty string)
    completed = [c for c in checks if c.get("conclusion")]
    if len(completed) < len(checks):
        # Some checks still running — we can't determine pass/fail yet
        return None

    return all(
        c["conclusion"].upper() in ("SUCCESS", "NEUTRAL", "SKIPPED")
        for c in completed
    )


def _extract_labels(data: dict[str, Any]) -> str:
    """Extract label names as comma-separated string."""
    labels = data.get("labels") or []
    return ",".join(label.get("name", "") for label in labels if label.get("name"))


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def poll_outcomes(repo_root: Path) -> None:
    """Poll GitHub for all open PR outcomes and update their status.

    For each PR with status ``'open'``, calls ``gh pr view`` to fetch
    current state.  Updates the record in the database.  On ``gh`` CLI
    failure for a specific PR, logs a warning and continues to the next
    PR (the next scheduled poll is the implicit retry).

    Does NOT poll already-resolved (merged/closed) PRs.
    """
    store = OutcomeStore(repo_root)
    try:
        open_outcomes = store.get_open_outcomes()
        if not open_outcomes:
            return

        for outcome in open_outcomes:
            pr_number = outcome["pr_number"]
            try:
                data = _call_gh_pr_view(pr_number, repo_root)
            except (subprocess.CalledProcessError, json.JSONDecodeError, OSError) as exc:
                logger.warning(
                    "Failed to poll PR #%d: %s", pr_number, exc
                )
                continue

            state = data.get("state", "OPEN").upper()

            if state == "MERGED":
                review_count = len(data.get("reviews") or []) + len(data.get("comments") or [])
                store.update_outcome(
                    pr_number=pr_number,
                    status="merged",
                    merged_at=data.get("mergedAt"),
                    review_comment_count=review_count,
                    ci_passed=_extract_ci_passed(data),
                    labels=_extract_labels(data),
                )
            elif state == "CLOSED":
                review_count = len(data.get("reviews") or []) + len(data.get("comments") or [])
                close_context = _extract_close_context(data)
                store.update_outcome(
                    pr_number=pr_number,
                    status="closed",
                    closed_at=data.get("closedAt"),
                    review_comment_count=review_count,
                    ci_passed=_extract_ci_passed(data),
                    labels=_extract_labels(data),
                    close_context=close_context,
                )
                # Capture reviewer feedback as a FAILURE memory entry so the
                # pipeline can learn from rejected PRs.  Only stored when there
                # is actual reviewer feedback (non-empty close_context).
                if close_context:
                    run_id = outcome["run_id"]
                    try:
                        with MemoryStore(repo_root) as mem:
                            mem.add_memory(
                                category=MemoryCategory.FAILURE,
                                phase="deliver",
                                run_id=run_id,
                                text=(
                                    f"PR #{pr_number} closed without merge. "
                                    f"Reviewer feedback: {close_context}"
                                ),
                            )
                    except Exception:
                        logger.warning(
                            "Failed to store memory for closed PR #%d",
                            pr_number,
                            exc_info=True,
                        )
            else:
                # Still open — just update last_polled_at
                store.update_outcome(
                    pr_number=pr_number,
                    status="open",
                    review_comment_count=len(data.get("reviews") or []) + len(data.get("comments") or []),
                    ci_passed=_extract_ci_passed(data),
                    labels=_extract_labels(data),
                )
    finally:
        store.close()


def compute_outcome_stats(repo_root: Path) -> dict[str, Any]:
    """Compute aggregate PR outcome metrics.

    Returns a dict with keys:
    - ``total_tracked``: Total number of tracked PRs
    - ``merged_count``: Number of merged PRs
    - ``closed_count``: Number of closed (not merged) PRs
    - ``open_count``: Number of still-open PRs
    - ``merge_rate``: Fraction merged out of resolved (merged + closed), 0.0 if none resolved
    - ``avg_time_to_merge_hours``: Average hours from creation to merge, 0.0 if none merged
    """
    store = OutcomeStore(repo_root)
    try:
        outcomes = store.get_outcomes()
    finally:
        store.close()

    if not outcomes:
        return {
            "total_tracked": 0,
            "merged_count": 0,
            "closed_count": 0,
            "open_count": 0,
            "merge_rate": 0.0,
            "avg_time_to_merge_hours": 0.0,
        }

    merged_count = sum(1 for o in outcomes if o["status"] == "merged")
    closed_count = sum(1 for o in outcomes if o["status"] == "closed")
    open_count = sum(1 for o in outcomes if o["status"] == "open")
    total = len(outcomes)

    resolved = merged_count + closed_count
    merge_rate = merged_count / resolved if resolved > 0 else 0.0

    # Average time to merge (hours)
    merge_durations: list[float] = []
    for o in outcomes:
        if o["status"] == "merged" and o["merged_at"] and o["created_at"]:
            try:
                created = datetime.fromisoformat(o["created_at"])
                merged = datetime.fromisoformat(o["merged_at"])
                delta = (merged - created).total_seconds() / 3600.0
                merge_durations.append(delta)
            except (ValueError, TypeError):
                pass

    avg_time = sum(merge_durations) / len(merge_durations) if merge_durations else 0.0

    return {
        "total_tracked": total,
        "merged_count": merged_count,
        "closed_count": closed_count,
        "open_count": open_count,
        "merge_rate": merge_rate,
        "avg_time_to_merge_hours": avg_time,
    }


def format_outcome_summary(repo_root: Path) -> str:
    """Format a compact outcome summary for CEO prompt injection.

    Returns a short string (~30-50 tokens) summarizing recent PR outcomes.
    Returns an empty string if no outcomes are tracked.

    The summary is capped at ~500 tokens (~2000 chars) to respect the
    CEO prompt budget.

    Uses a single ``OutcomeStore`` connection for both stats computation
    and close-context retrieval to avoid redundant SQLite connections.
    """
    store = OutcomeStore(repo_root)
    try:
        outcomes = store.get_outcomes()
    finally:
        store.close()

    if not outcomes:
        return ""

    # Compute stats inline from the fetched outcomes (avoids a second connection)
    merged_count = sum(1 for o in outcomes if o["status"] == "merged")
    closed_count = sum(1 for o in outcomes if o["status"] == "closed")
    open_count = sum(1 for o in outcomes if o["status"] == "open")
    total = len(outcomes)
    resolved = merged_count + closed_count
    merge_rate = merged_count / resolved if resolved > 0 else 0.0

    # Average time to merge (hours)
    merge_durations: list[float] = []
    for o in outcomes:
        if o["status"] == "merged" and o["merged_at"] and o["created_at"]:
            try:
                created = datetime.fromisoformat(o["created_at"])
                merged = datetime.fromisoformat(o["merged_at"])
                delta = (merged - created).total_seconds() / 3600.0
                merge_durations.append(delta)
            except (ValueError, TypeError):
                pass
    avg_hours = sum(merge_durations) / len(merge_durations) if merge_durations else 0.0

    parts: list[str] = []
    parts.append(f"Tracked PRs: {total}")
    if merged_count > 0:
        parts.append(f"{merged_count} merged")
        if avg_hours > 0:
            parts.append(f"avg {avg_hours:.1f}h to merge")
    if open_count > 0:
        parts.append(f"{open_count} still open")
    if closed_count > 0:
        parts.append(f"{closed_count} closed without merge")
    if merged_count + closed_count > 0:
        parts.append(f"merge rate: {merge_rate:.0%}")

    summary = "Your PR history: " + ", ".join(parts) + "."

    # Include close contexts for recent closed PRs (up to 3)
    closed_with_context = [
        o for o in outcomes
        if o["status"] == "closed" and o["close_context"]
    ][:3]

    if closed_with_context:
        summary += " Recent rejection feedback:"
        for o in closed_with_context:
            context = o["close_context"][:100]  # Extra truncation for summary
            summary += f" PR#{o['pr_number']}: \"{context}\";"

    # Hard cap at 2000 chars (~500 tokens)
    return summary[:2000]
