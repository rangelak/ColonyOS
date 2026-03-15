from __future__ import annotations

import argparse

from colonyos_pm.storage import LocalArtifactStore
from colonyos_pm.workflow import run_pm_workflow


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ColonyOS PM workflow v1.")
    parser.add_argument("prompt", help="Feature request or product/workflow idea.")
    parser.add_argument(
        "--out-dir",
        default="generated/pm-workflow",
        help="Directory for generated artifacts.",
    )
    args = parser.parse_args()

    artifacts = run_pm_workflow(args.prompt)
    store = LocalArtifactStore(base_dir=args.out_dir)
    locations = store.save_workflow_artifacts(artifacts)

    print(f"work_id={artifacts.work_id}")
    print(f"risk_tier={artifacts.risk_assessment.tier.value}")
    print(f"escalate_to_human={artifacts.risk_assessment.escalate_to_human}")
    print(f"prd_path={locations['prd_path']}")
    print(f"bundle_path={locations['bundle_path']}")


if __name__ == "__main__":
    main()
