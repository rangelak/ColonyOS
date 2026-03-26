"""Persistent memory storage layer for ColonyOS.

Stores structured observations in a SQLite database at ``.colonyos/memory.db``.
Memories are captured at phase boundaries and injected into prompts based on
relevance, recency, and keyword overlap — so run #50 is smarter than run #2.

Uses Python's built-in ``sqlite3`` with FTS5 for keyword search — zero new
dependencies.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from colonyos.sanitize import sanitize_untrusted_content

logger = logging.getLogger(__name__)

MEMORY_DB = "memory.db"

# Phase → relevant memory categories for injection ranking.
PHASE_CATEGORY_MAP: dict[str, list[str]] = {
    "plan": ["codebase", "failure", "preference"],
    "implement": ["codebase", "failure", "preference"],
    "fix": ["codebase", "failure", "preference"],
    "review": ["review_pattern", "codebase"],
    "decision": ["review_pattern", "codebase"],
    "direct_agent": ["codebase", "failure", "preference", "review_pattern"],
}


class MemoryCategory(str, Enum):
    """Categories for memory entries."""

    CODEBASE = "codebase"
    FAILURE = "failure"
    PREFERENCE = "preference"
    REVIEW_PATTERN = "review_pattern"


@dataclass
class MemoryEntry:
    """A single memory record."""

    id: int
    created_at: str
    category: MemoryCategory
    phase: str
    run_id: str
    text: str
    tags: list[str] = field(default_factory=list)


class MemoryStore:
    """SQLite-backed persistent memory store.

    Parameters
    ----------
    repo_root:
        Path to the repository root. The DB is created at
        ``<repo_root>/.colonyos/memory.db``.
    max_entries:
        Maximum number of memory entries to retain. Oldest entries
        are pruned (FIFO) when the cap is exceeded.
    """

    def __init__(self, repo_root: Path, max_entries: int = 500) -> None:
        self.repo_root = repo_root
        self.max_entries = max_entries
        self._db_path = repo_root / ".colonyos" / MEMORY_DB
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        """Create schema and FTS5 virtual table if they don't exist."""
        cur = self._conn.cursor()

        # Schema version tracking
        cur.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
        )
        row = cur.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            cur.execute("INSERT INTO schema_version (version) VALUES (1)")

        # Main memories table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                category TEXT NOT NULL,
                phase TEXT NOT NULL,
                run_id TEXT NOT NULL,
                text TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT ''
            )
        """)

        # FTS5 virtual table for keyword search
        cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
            USING fts5(text, content=memories, content_rowid=id)
        """)

        # Triggers to keep FTS in sync
        cur.executescript("""
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text);
            END;
            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, text)
                    VALUES('delete', old.id, old.text);
            END;
            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, text)
                    VALUES('delete', old.id, old.text);
                INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text);
            END;
        """)

        self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def add_memory(
        self,
        category: MemoryCategory,
        phase: str,
        run_id: str,
        text: str,
        tags: Optional[list[str]] = None,
    ) -> MemoryEntry:
        """Add a memory entry, sanitizing text and enforcing max_entries cap.

        Returns the created ``MemoryEntry``.
        """
        sanitized_text = sanitize_untrusted_content(text)
        tags = tags or []
        tags_str = ",".join(tags)
        now = datetime.now(timezone.utc).isoformat()

        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO memories (created_at, category, phase, run_id, text, tags)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (now, category.value, phase, run_id, sanitized_text, tags_str),
        )
        entry_id = cur.lastrowid
        self._conn.commit()

        # Enforce max_entries cap — prune oldest entries
        self._prune_if_needed()

        return MemoryEntry(
            id=entry_id,
            created_at=now,
            category=category,
            phase=phase,
            run_id=run_id,
            text=sanitized_text,
            tags=tags,
        )

    def _prune_if_needed(self) -> None:
        """Remove oldest entries if count exceeds max_entries."""
        count = self.count_memories()
        if count <= self.max_entries:
            return

        excess = count - self.max_entries
        cur = self._conn.cursor()
        cur.execute(
            """
            DELETE FROM memories WHERE id IN (
                SELECT id FROM memories ORDER BY created_at ASC, id ASC LIMIT ?
            )
            """,
            (excess,),
        )
        self._conn.commit()

    def query_memories(
        self,
        categories: Optional[list[MemoryCategory]] = None,
        limit: int = 50,
        keyword: Optional[str] = None,
        phase: Optional[str] = None,
    ) -> list[MemoryEntry]:
        """Query memories with optional filters.

        Results are ordered by recency (most recent first). When a keyword
        is provided, FTS5 is used for matching.
        """
        if keyword:
            return self._query_fts(keyword, categories, limit, phase)

        conditions: list[str] = []
        params: list[object] = []

        if categories:
            placeholders = ",".join("?" for _ in categories)
            conditions.append(f"category IN ({placeholders})")
            params.extend(c.value for c in categories)

        if phase:
            conditions.append("phase = ?")
            params.append(phase)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        cur = self._conn.cursor()
        cur.execute(
            f"SELECT * FROM memories {where} ORDER BY created_at DESC, id DESC LIMIT ?",
            (*params, limit),
        )
        return [self._row_to_entry(row) for row in cur.fetchall()]

    def _query_fts(
        self,
        keyword: str,
        categories: Optional[list[MemoryCategory]] = None,
        limit: int = 50,
        phase: Optional[str] = None,
    ) -> list[MemoryEntry]:
        """Full-text search via FTS5."""
        # Escape special FTS5 characters and build a prefix query
        safe_keyword = keyword.replace('"', '""')
        fts_query = f'"{safe_keyword}"'

        conditions = ["m.id IN (SELECT rowid FROM memories_fts WHERE memories_fts MATCH ?)"]
        params: list[object] = [fts_query]

        if categories:
            placeholders = ",".join("?" for _ in categories)
            conditions.append(f"m.category IN ({placeholders})")
            params.extend(c.value for c in categories)

        if phase:
            conditions.append("m.phase = ?")
            params.append(phase)

        where = f"WHERE {' AND '.join(conditions)}"

        cur = self._conn.cursor()
        cur.execute(
            f"SELECT m.* FROM memories m {where} ORDER BY m.created_at DESC, m.id DESC LIMIT ?",
            (*params, limit),
        )
        return [self._row_to_entry(row) for row in cur.fetchall()]

    def delete_memory(self, memory_id: int) -> bool:
        """Delete a memory by ID. Returns True if a row was deleted."""
        cur = self._conn.cursor()
        cur.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def clear_memories(self) -> None:
        """Delete all memories."""
        cur = self._conn.cursor()
        cur.execute("DELETE FROM memories")
        self._conn.commit()

    def count_memories(self) -> int:
        """Return the total number of memory entries."""
        cur = self._conn.cursor()
        row = cur.execute("SELECT COUNT(*) FROM memories").fetchone()
        return row[0]

    def count_by_category(self) -> dict[MemoryCategory, int]:
        """Return counts grouped by category."""
        cur = self._conn.cursor()
        rows = cur.execute(
            "SELECT category, COUNT(*) as cnt FROM memories GROUP BY category"
        ).fetchall()
        result: dict[MemoryCategory, int] = {}
        for row in rows:
            try:
                cat = MemoryCategory(row["category"])
                result[cat] = row["cnt"]
            except ValueError:
                logger.warning("Unknown memory category in DB: %s", row["category"])
        return result

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> MemoryEntry:
        """Convert a database row to a MemoryEntry."""
        tags_str = row["tags"]
        tags = [t for t in tags_str.split(",") if t] if tags_str else []
        return MemoryEntry(
            id=row["id"],
            created_at=row["created_at"],
            category=MemoryCategory(row["category"]),
            phase=row["phase"],
            run_id=row["run_id"],
            text=row["text"],
            tags=tags,
        )


def load_memory_for_injection(
    store: MemoryStore,
    phase: str,
    prompt_text: str,
    max_tokens: int = 1500,
) -> str:
    """Retrieve relevant memories, format as a markdown block, and truncate at budget.

    Token counting uses chars ÷ 4 as proxy per the PRD spec.

    Parameters
    ----------
    store:
        The MemoryStore to query.
    phase:
        Current pipeline phase (used to determine relevant categories).
    prompt_text:
        Current prompt/task text (used for keyword relevance — future use).
    max_tokens:
        Maximum approximate token budget for the injected block.

    Returns
    -------
    str
        A ``## Memory Context`` markdown block, or empty string if no
        relevant memories exist.
    """
    # Determine relevant categories for this phase
    category_names = PHASE_CATEGORY_MAP.get(phase, list(PHASE_CATEGORY_MAP["direct_agent"]))
    categories = []
    for name in category_names:
        try:
            categories.append(MemoryCategory(name))
        except ValueError:
            pass

    # Query with generous limit; we'll trim by token budget
    memories = store.query_memories(categories=categories, limit=100)

    if not memories:
        return ""

    # Build the block greedily until budget exhausted
    max_chars = max_tokens * 4
    header = "## Memory Context\n\n"
    current_chars = len(header)
    lines: list[str] = []

    for entry in memories:
        line = f"- **[{entry.category.value}]** {entry.text}"
        line_chars = len(line) + 1  # +1 for newline
        if current_chars + line_chars > max_chars:
            break
        lines.append(line)
        current_chars += line_chars

    if not lines:
        return ""

    return header + "\n".join(lines)
