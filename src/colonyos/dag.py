"""DAG parser for task dependencies in parallel implement mode.

This module provides functionality to:
1. Parse task files and extract dependency annotations (depends_on: [...])
2. Build a directed acyclic graph (DAG) of task dependencies
3. Detect circular dependencies
4. Compute topological sort for execution order
5. Get ready-to-execute tasks based on completed tasks
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Regex to match task lines like "- [ ] 1.0 Task description" or "- [x] 1.0 Task"
# Captures the task ID (e.g., "1.0", "2.0", "10.0")
TASK_LINE_PATTERN = re.compile(
    r"^-\s*\[[x ]\]\s*(\d+\.\d+)\s+",
    re.IGNORECASE | re.MULTILINE,
)

# Regex to match depends_on annotation like "depends_on: [1.0, 2.0]" or "depends_on: []"
# This pattern is flexible with whitespace
DEPENDS_ON_PATTERN = re.compile(
    r"^\s*depends_on:\s*\[([^\]]*)\]",
    re.IGNORECASE | re.MULTILINE,
)


class CircularDependencyError(Exception):
    """Raised when a circular dependency is detected in the task DAG."""

    def __init__(self, cycle_path: list[str]) -> None:
        self.cycle_path = cycle_path
        path_str = " → ".join(cycle_path)
        super().__init__(f"Circular dependency detected: {path_str}")


def parse_task_file(content: str) -> dict[str, list[str]]:
    """Parse a task file and extract task dependencies.

    Args:
        content: The full content of a task file (Markdown format).

    Returns:
        A dictionary mapping task IDs to lists of dependency task IDs.
        Tasks without explicit depends_on annotations are treated as
        having no dependencies (empty list).

    Example:
        >>> content = '''
        ... - [ ] 1.0 Add user model
        ...   depends_on: []
        ... - [ ] 2.0 Add authentication
        ...   depends_on: [1.0]
        ... '''
        >>> parse_task_file(content)
        {'1.0': [], '2.0': ['1.0']}
    """
    if not content.strip():
        return {}

    dependencies: dict[str, list[str]] = {}
    lines = content.splitlines()

    current_task_id: str | None = None

    for line in lines:
        # Check if this line starts a new task
        task_match = TASK_LINE_PATTERN.match(line)
        if task_match:
            current_task_id = task_match.group(1)
            # Initialize with empty dependencies (may be overwritten)
            dependencies[current_task_id] = []
            continue

        # Check if this line has a depends_on annotation
        depends_match = DEPENDS_ON_PATTERN.match(line)
        if depends_match and current_task_id is not None:
            deps_str = depends_match.group(1).strip()
            if deps_str:
                # Parse comma-separated dependency list
                dep_ids = [d.strip() for d in deps_str.split(",") if d.strip()]
                dependencies[current_task_id] = dep_ids
            else:
                dependencies[current_task_id] = []

    return dependencies


@dataclass
class TaskDAG:
    """Directed Acyclic Graph representation of task dependencies.

    Provides methods for cycle detection, topological sorting, and
    determining which tasks are ready to execute.
    """

    dependencies: dict[str, list[str]]
    _reverse_deps: dict[str, list[str]] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        """Build reverse dependency map for efficient lookups."""
        self._reverse_deps = {task_id: [] for task_id in self.dependencies}
        for task_id, deps in self.dependencies.items():
            for dep in deps:
                if dep in self._reverse_deps:
                    self._reverse_deps[dep].append(task_id)

    @property
    def task_count(self) -> int:
        """Return the total number of tasks in the DAG."""
        return len(self.dependencies)

    def get_all_tasks(self) -> list[str]:
        """Return all task IDs in the DAG."""
        return list(self.dependencies.keys())

    def detect_cycle(self) -> list[str] | None:
        """Detect if there is a cycle in the dependency graph.

        Returns:
            A list representing the cycle path (e.g., ["3.0", "4.0", "3.0"])
            if a cycle exists, or None if the graph is acyclic.
        """
        # Use DFS with three states: WHITE (unvisited), GRAY (in progress), BLACK (done)
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {task: WHITE for task in self.dependencies}
        parent: dict[str, str | None] = {task: None for task in self.dependencies}

        def dfs(node: str) -> list[str] | None:
            color[node] = GRAY

            for dep in self.dependencies.get(node, []):
                if dep not in color:
                    # Dependency points to unknown task - skip
                    continue

                if color[dep] == GRAY:
                    # Found a back edge - cycle detected
                    # Build cycle path
                    cycle = [dep, node]
                    current = parent[node]
                    while current is not None and current != dep:
                        cycle.append(current)
                        current = parent[current]
                    cycle.append(dep)
                    return list(reversed(cycle))

                if color[dep] == WHITE:
                    parent[dep] = node
                    result = dfs(dep)
                    if result is not None:
                        return result

            color[node] = BLACK
            return None

        for task in self.dependencies:
            if color[task] == WHITE:
                result = dfs(task)
                if result is not None:
                    return result

        return None

    def topological_sort(self) -> list[str]:
        """Return a topological ordering of tasks.

        Tasks are ordered so that all dependencies of a task appear
        before the task itself in the list.

        Returns:
            A list of task IDs in execution order.

        Raises:
            CircularDependencyError: If the graph contains a cycle.
        """
        cycle = self.detect_cycle()
        if cycle is not None:
            raise CircularDependencyError(cycle)

        # Kahn's algorithm
        in_degree: dict[str, int] = {task: 0 for task in self.dependencies}
        for deps in self.dependencies.values():
            for dep in deps:
                if dep in in_degree:
                    in_degree[dep] += 0  # Just ensure dep exists in map

        # Actually count in-degrees
        for task, deps in self.dependencies.items():
            for dep in deps:
                if dep in self.dependencies:
                    # task depends on dep, so task has an incoming edge from dep
                    pass

        # Recalculate: in_degree[X] = number of tasks that X depends on
        # Actually, we need: in_degree[X] = number of tasks that depend on X
        # For topological sort of dependencies, we want to process a task
        # only after all its dependencies are processed.

        # in_degree[X] = len(dependencies[X]) conceptually means
        # we need to wait for that many tasks before X can run
        in_degree = {task: len(deps) for task, deps in self.dependencies.items()}

        # Start with tasks that have no dependencies
        queue = [task for task, deg in in_degree.items() if deg == 0]
        result: list[str] = []

        while queue:
            # Sort for deterministic output
            queue.sort()
            task = queue.pop(0)
            result.append(task)

            # For each task that depends on this one, reduce in-degree
            for dependent in self._reverse_deps.get(task, []):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        return result

    def get_ready_tasks(self, completed: set[str]) -> list[str]:
        """Get tasks that are ready to execute.

        A task is ready if:
        1. It has not been completed
        2. All of its dependencies have been completed

        Args:
            completed: Set of task IDs that have been completed.

        Returns:
            List of task IDs that are ready to execute.
        """
        ready: list[str] = []
        for task_id, deps in self.dependencies.items():
            if task_id in completed:
                continue
            # Check if all dependencies are completed
            if all(dep in completed or dep not in self.dependencies for dep in deps):
                ready.append(task_id)
        return sorted(ready)  # Sort for deterministic output
