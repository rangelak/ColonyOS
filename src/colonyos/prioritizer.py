from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from colonyos.agent import run_phase_sync
from colonyos.config import ColonyConfig
from colonyos.models import Phase, QueueItem, QueueItemStatus, QueueState
from colonyos.queue_runtime import reprioritize_queue_item

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PriorityDecision:
    item_id: str
    urgency_score: float
    reason: str


def _build_prioritizer_prompt(queue_state: QueueState) -> tuple[str, str]:
    pending = [
        item for item in queue_state.items
        if item.status == QueueItemStatus.PENDING
    ]
    lines = [
        "You are a queue prioritization agent for an autonomous engineering system.",
        "Score each pending queue item with urgency_score from 0.0 to 1.0.",
        "Use higher urgency for user pain, repeated demand, hotfix/bug signals, or clear business urgency.",
        "Do not change ordering directly; only emit urgency scores and concise reasons.",
        "Return ONLY JSON in this shape:",
        '{"decisions":[{"item_id":"...", "urgency_score":0.0, "reason":"..."}]}',
        "",
        "Pending items:",
    ]
    for item in pending[:20]:
        lines.append(
            f"- id={item.id} source={item.source_type} priority={item.priority} "
            f"demand={item.demand_count} summary={item.summary or item.issue_title or item.source_value[:180]}"
        )
    system = "\n".join(lines)
    user = "Score the queue now."
    return system, user


def reprioritize_queue_with_agent(
    repo_root: Path,
    config: ColonyConfig,
    queue_state: QueueState,
) -> bool:
    decisions = score_queue_with_agent(repo_root, config, queue_state)
    if not decisions:
        return False
    return apply_priority_decisions(queue_state, decisions)


def score_queue_with_agent(
    repo_root: Path,
    config: ColonyConfig,
    queue_state: QueueState,
) -> list[PriorityDecision]:
    pending = [
        item for item in queue_state.items
        if item.status == QueueItemStatus.PENDING
    ]
    if len(pending) < 2:
        return []

    system, user = _build_prioritizer_prompt(queue_state)
    result = run_phase_sync(
        Phase.TRIAGE,
        user,
        cwd=repo_root,
        system_prompt=system,
        model=config.router.model,
        budget_usd=0.20,
        allowed_tools=[],
    )
    raw_text = ""
    if result.artifacts:
        raw_text = next(iter(result.artifacts.values()), "")
    if not raw_text:
        logger.warning("Prioritizer returned no JSON output")
        return []

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.warning("Prioritizer returned invalid JSON: %s", raw_text[:300])
        return []

    by_id = {item.id for item in pending}
    decisions: list[PriorityDecision] = []
    for entry in payload.get("decisions", []):
        item_id = str(entry.get("item_id", "")).strip()
        if item_id not in by_id:
            continue
        try:
            urgency_score = float(entry.get("urgency_score", 0.0))
        except (TypeError, ValueError):
            urgency_score = 0.0
        urgency_score = max(0.0, min(1.0, urgency_score))
        reason = str(entry.get("reason", "")).strip()[:200]
        decisions.append(
            PriorityDecision(
                item_id=item_id,
                urgency_score=urgency_score,
                reason=reason,
            )
        )
    return decisions


def apply_priority_decisions(
    queue_state: QueueState,
    decisions: list[PriorityDecision],
) -> bool:
    by_id = {
        item.id: item
        for item in queue_state.items
        if item.status == QueueItemStatus.PENDING
    }
    changed = False
    for decision in decisions:
        item = by_id.get(decision.item_id)
        if item is None:
            continue
        item.urgency_score = decision.urgency_score
        reprioritize_queue_item(item)
        if decision.reason:
            base = item.priority_reason or ""
            item.priority_reason = f"{base}, agent:{decision.reason}".strip(", ")
        changed = True
    return changed
