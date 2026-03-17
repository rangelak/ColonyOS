from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
PRD_FILENAME_RE = re.compile(
    r"^(?P<timestamp>\d{8}_\d{6})_prd_(?P<slug>[a-z0-9_]+)\.md$"
)


@dataclass(frozen=True)
class PlanningNames:
    timestamp: str
    slug: str
    prd_filename: str
    task_filename: str


@dataclass(frozen=True)
class ReviewNames:
    timestamp: str
    slug: str
    task_review_filenames: tuple[str, ...]
    final_review_filename: str


MAX_SLUG_LEN = 80


def slugify(value: str, *, max_len: int = MAX_SLUG_LEN) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("_")
    return slug or "untitled"


def generate_timestamp(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime(TIMESTAMP_FORMAT)


def planning_names(
    feature_name: str,
    *,
    timestamp: str | None = None,
) -> PlanningNames:
    ts = timestamp or generate_timestamp()
    slug = slugify(feature_name)
    return PlanningNames(
        timestamp=ts,
        slug=slug,
        prd_filename=f"{ts}_prd_{slug}.md",
        task_filename=f"{ts}_tasks_{slug}.md",
    )


def review_names(
    feature_name: str,
    *,
    task_count: int,
    timestamp: str | None = None,
) -> ReviewNames:
    ts = timestamp or generate_timestamp()
    slug = slugify(feature_name)
    task_filenames = tuple(
        f"{ts}_review_task_{i}_{slug}.md" for i in range(1, task_count + 1)
    )
    return ReviewNames(
        timestamp=ts,
        slug=slug,
        task_review_filenames=task_filenames,
        final_review_filename=f"{ts}_review_final_{slug}.md",
    )


@dataclass(frozen=True)
class ProposalNames:
    timestamp: str
    slug: str
    proposal_filename: str


def proposal_names(
    feature_name: str,
    *,
    timestamp: str | None = None,
) -> ProposalNames:
    ts = timestamp or generate_timestamp()
    slug = slugify(feature_name)
    return ProposalNames(
        timestamp=ts,
        slug=slug,
        proposal_filename=f"{ts}_proposal_{slug}.md",
    )


def task_filename_from_prd(prd_filename: str) -> str:
    match = PRD_FILENAME_RE.match(prd_filename)
    if not match:
        raise ValueError(
            f"PRD filename must match YYYYMMDD_HHMMSS_prd_<slug>.md, got: {prd_filename}"
        )
    return f"{match.group('timestamp')}_tasks_{match.group('slug')}.md"
