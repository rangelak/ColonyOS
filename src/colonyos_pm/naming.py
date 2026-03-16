from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
TIMESTAMP_FORMAT_LABEL = "YYYYMMDD_HHMMSS"
PRD_FILENAME_RE = re.compile(
    r"^(?P<timestamp>\d{8}_\d{6})_prd_(?P<slug>[a-z0-9_]+)\.md$"
)


@dataclass(frozen=True)
class PlanningNames:
    timestamp: str
    slug: str
    prd_filename: str
    task_filename: str
    changelog_heading: str


def normalize_feature_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "untitled"


def generate_timestamp(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime(TIMESTAMP_FORMAT)


def validate_timestamp(timestamp: str) -> str:
    try:
        datetime.strptime(timestamp, TIMESTAMP_FORMAT)
    except ValueError as exc:
        raise ValueError(
            f"Timestamp must match {TIMESTAMP_FORMAT}, got: {timestamp}"
        ) from exc
    return timestamp


def generate_planning_names(
    feature_name: str,
    *,
    title: str | None = None,
    timestamp: str | None = None,
) -> PlanningNames:
    normalized_timestamp = (
        validate_timestamp(timestamp) if timestamp else generate_timestamp()
    )
    slug = normalize_feature_slug(feature_name)
    heading_title = (title or feature_name).strip() or slug
    return PlanningNames(
        timestamp=normalized_timestamp,
        slug=slug,
        prd_filename=f"{normalized_timestamp}_prd_{slug}.md",
        task_filename=f"{normalized_timestamp}_tasks_{slug}.md",
        changelog_heading=f"## {normalized_timestamp} — {heading_title}",
    )


def task_filename_from_prd_path(prd_path: str) -> str:
    filename = Path(prd_path).name
    match = PRD_FILENAME_RE.match(filename)
    if not match:
        raise ValueError(
            "PRD filename must match YYYYMMDD_HHMMSS_prd_[feature-name].md"
        )
    return f"{match.group('timestamp')}_tasks_{match.group('slug')}.md"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Generate deterministic planning artifact names."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    bundle_parser = subparsers.add_parser(
        "bundle",
        help="Generate the PRD filename, task filename, and changelog heading.",
    )
    bundle_parser.add_argument("feature_name", help="Feature label to slugify.")
    bundle_parser.add_argument(
        "--title",
        default=None,
        help="Human-readable changelog title. Defaults to the feature label.",
    )
    bundle_parser.add_argument(
        "--timestamp",
        default=None,
        help=f"Optional override in {TIMESTAMP_FORMAT_LABEL} format.",
    )

    prd_parser = subparsers.add_parser(
        "prd",
        help="Generate only the PRD filename.",
    )
    prd_parser.add_argument("feature_name", help="Feature label to slugify.")
    prd_parser.add_argument(
        "--timestamp",
        default=None,
        help=f"Optional override in {TIMESTAMP_FORMAT_LABEL} format.",
    )

    task_from_prd_parser = subparsers.add_parser(
        "task-from-prd",
        help="Generate the paired task filename from an existing PRD path.",
    )
    task_from_prd_parser.add_argument("prd_path", help="Path to the PRD file.")

    heading_parser = subparsers.add_parser(
        "heading",
        help="Generate only the changelog heading.",
    )
    heading_parser.add_argument("feature_name", help="Feature label to slugify.")
    heading_parser.add_argument(
        "--title",
        default=None,
        help="Human-readable changelog title. Defaults to the feature label.",
    )
    heading_parser.add_argument(
        "--timestamp",
        default=None,
        help=f"Optional override in {TIMESTAMP_FORMAT_LABEL} format.",
    )

    args = parser.parse_args(argv)

    if args.command == "bundle":
        planning_names = generate_planning_names(
            args.feature_name,
            title=args.title,
            timestamp=args.timestamp,
        )
        print(json.dumps(asdict(planning_names), indent=2))
        return

    if args.command == "prd":
        planning_names = generate_planning_names(
            args.feature_name,
            timestamp=args.timestamp,
        )
        print(planning_names.prd_filename)
        return

    if args.command == "task-from-prd":
        print(task_filename_from_prd_path(args.prd_path))
        return

    if args.command == "heading":
        planning_names = generate_planning_names(
            args.feature_name,
            title=args.title,
            timestamp=args.timestamp,
        )
        print(planning_names.changelog_heading)
        return

    raise RuntimeError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
