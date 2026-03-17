"""Cross-run learnings ledger: parse, append, prune, and inject."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

LEARNINGS_FILE = "learnings.md"
LEDGER_HEADER = "# ColonyOS Learnings Ledger\n"

_RUN_HEADER_RE = re.compile(r"^## Run:\s*(.+)$")
_DATE_LINE_RE = re.compile(r"^_Date:\s*([\d-]+)\s*\|\s*Feature:\s*(.+)_$")
_ENTRY_RE = re.compile(r"^- \*\*\[([a-z-]+)\]\*\*\s+(.+)$")


@dataclass(frozen=True)
class LearningEntry:
    category: str
    text: str


def learnings_path(repo_root: Path) -> Path:
    return repo_root / ".colonyos" / LEARNINGS_FILE


def parse_learnings(
    content: str,
) -> list[tuple[str, str, str, list[LearningEntry]]]:
    """Parse ledger markdown into (run_id, date, feature, entries) tuples."""
    sections: list[tuple[str, str, str, list[LearningEntry]]] = []
    current_run_id: str | None = None
    current_date = ""
    current_feature = ""
    current_entries: list[LearningEntry] = []

    for line in content.splitlines():
        line = line.strip()

        run_match = _RUN_HEADER_RE.match(line)
        if run_match:
            if current_run_id is not None:
                sections.append(
                    (current_run_id, current_date, current_feature, current_entries)
                )
            current_run_id = run_match.group(1).strip()
            current_date = ""
            current_feature = ""
            current_entries = []
            continue

        date_match = _DATE_LINE_RE.match(line)
        if date_match and current_run_id is not None:
            current_date = date_match.group(1).strip()
            current_feature = date_match.group(2).strip()
            continue

        entry_match = _ENTRY_RE.match(line)
        if entry_match and current_run_id is not None:
            current_entries.append(
                LearningEntry(
                    category=entry_match.group(1),
                    text=entry_match.group(2).strip(),
                )
            )

    if current_run_id is not None:
        sections.append(
            (current_run_id, current_date, current_feature, current_entries)
        )

    return sections


def format_learnings_section(
    run_id: str,
    date: str,
    feature_summary: str,
    entries: list[LearningEntry],
) -> str:
    """Produce the markdown block for one run section."""
    lines = [
        f"## Run: {run_id}",
        f"_Date: {date} | Feature: {feature_summary}_",
        "",
    ]
    for entry in entries:
        lines.append(f"- **[{entry.category}]** {entry.text}")
    return "\n".join(lines)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def append_learnings(
    repo_root: Path,
    run_id: str,
    date: str,
    feature_summary: str,
    new_entries: list[LearningEntry],
    max_entries: int = 100,
) -> None:
    """Append new entries with deduplication and cap enforcement."""
    path = learnings_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        content = path.read_text(encoding="utf-8")
    else:
        content = LEDGER_HEADER

    existing_sections = parse_learnings(content)

    existing_texts = set()
    for _rid, _d, _f, entries in existing_sections:
        for e in entries:
            existing_texts.add(_normalize(e.text))

    deduped = [
        e for e in new_entries if _normalize(e.text) not in existing_texts
    ]

    if not deduped:
        return

    new_section = format_learnings_section(run_id, date, feature_summary, deduped)

    if content.rstrip():
        content = content.rstrip() + "\n\n" + new_section + "\n"
    else:
        content = LEDGER_HEADER + "\n" + new_section + "\n"

    content = prune_ledger(content, max_entries)
    path.write_text(content, encoding="utf-8")


def prune_ledger(content: str, max_entries: int) -> str:
    """Drop oldest run sections until total entries <= max_entries."""
    sections = parse_learnings(content)
    total = sum(len(entries) for _, _, _, entries in sections)

    while total > max_entries and sections:
        _, _, _, removed = sections.pop(0)
        total -= len(removed)

    if not sections:
        return LEDGER_HEADER + "\n"

    parts = [LEDGER_HEADER]
    for run_id, date, feature, entries in sections:
        parts.append("")
        parts.append(format_learnings_section(run_id, date, feature, entries))

    return "\n".join(parts) + "\n"


def load_learnings_for_injection(repo_root: Path, max_entries: int = 20) -> str:
    """Read ledger and format the most recent N entries as a prompt-ready block."""
    path = learnings_path(repo_root)
    if not path.exists():
        return ""

    content = path.read_text(encoding="utf-8")
    sections = parse_learnings(content)

    if not sections:
        return ""

    recent_entries: list[LearningEntry] = []
    for _, _, _, entries in reversed(sections):
        for entry in reversed(entries):
            if len(recent_entries) >= max_entries:
                break
            recent_entries.append(entry)
        if len(recent_entries) >= max_entries:
            break

    recent_entries.reverse()

    if not recent_entries:
        return ""

    lines = []
    for entry in recent_entries:
        lines.append(f"- **[{entry.category}]** {entry.text}")
    return "\n".join(lines)


def count_learnings(repo_root: Path) -> int:
    """Count total entries across all run sections."""
    path = learnings_path(repo_root)
    if not path.exists():
        return 0

    content = path.read_text(encoding="utf-8")
    sections = parse_learnings(content)
    return sum(len(entries) for _, _, _, entries in sections)
