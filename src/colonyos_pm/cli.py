from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from colonyos_pm.storage import LocalArtifactStore
from colonyos_pm.workflow import run_pm_workflow


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run ColonyOS PM workflow v1.")
    parser.add_argument("prompt", help="Feature request or product/workflow idea.")
    parser.add_argument(
        "--out-dir",
        default="generated/pm-workflow",
        help="Directory for generated artifacts.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override the LLM model (default: gpt-4o or COLONYOS_MODEL env var).",
    )
    args = parser.parse_args()

    if args.model:
        import os
        os.environ["COLONYOS_MODEL"] = args.model

    try:
        artifacts = run_pm_workflow(args.prompt)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    store = LocalArtifactStore(base_dir=args.out_dir)
    locations = store.save_workflow_artifacts(artifacts)

    print(f"work_id:          {artifacts.work_id}")
    print(f"risk_tier:        {artifacts.risk_assessment.tier.value}")
    print(f"escalate_to_human:{artifacts.risk_assessment.escalate_to_human}")
    print(f"questions:        {len(artifacts.clarifying_questions)}")
    print(f"answers:          {len(artifacts.autonomous_answers)}")
    print(f"prd_path:         {locations['prd_path']}")
    print(f"bundle_path:      {locations['bundle_path']}")


if __name__ == "__main__":
    main()
