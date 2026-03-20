"""Tests for DAG parser and dependency management (Task 2.0)."""

import pytest

from colonyos.dag import (
    TaskDAG,
    parse_task_file,
    CircularDependencyError,
)


class TestParseTaskFile:
    """Tests for parsing task files with dependency annotations."""

    def test_parse_simple_tasks(self) -> None:
        content = """
# Tasks

- [ ] 1.0 Add user model
  depends_on: []
- [ ] 2.0 Add authentication middleware
  depends_on: [1.0]
- [ ] 3.0 Add rate limiting
  depends_on: []
"""
        dependencies = parse_task_file(content)
        assert dependencies == {
            "1.0": [],
            "2.0": ["1.0"],
            "3.0": [],
        }

    def test_parse_multiple_dependencies(self) -> None:
        content = """
- [ ] 1.0 Task A
  depends_on: []
- [ ] 2.0 Task B
  depends_on: []
- [ ] 3.0 Task C
  depends_on: [1.0, 2.0]
"""
        dependencies = parse_task_file(content)
        assert dependencies == {
            "1.0": [],
            "2.0": [],
            "3.0": ["1.0", "2.0"],
        }

    def test_parse_no_dependencies_annotation(self) -> None:
        """Tasks without depends_on are treated as independent (empty list)."""
        content = """
- [ ] 1.0 Task A
- [ ] 2.0 Task B
"""
        dependencies = parse_task_file(content)
        assert dependencies == {
            "1.0": [],
            "2.0": [],
        }

    def test_parse_mixed_with_and_without_annotations(self) -> None:
        content = """
- [ ] 1.0 Task A
- [ ] 2.0 Task B
  depends_on: [1.0]
- [ ] 3.0 Task C
"""
        dependencies = parse_task_file(content)
        assert dependencies == {
            "1.0": [],
            "2.0": ["1.0"],
            "3.0": [],
        }

    def test_parse_complex_task_ids(self) -> None:
        content = """
- [ ] 1.0 Add config
  depends_on: []
- [ ] 2.0 Add DAG
  depends_on: []
- [ ] 6.0 Orchestration
  depends_on: [1.0, 2.0, 3.0, 4.0]
"""
        dependencies = parse_task_file(content)
        assert dependencies["6.0"] == ["1.0", "2.0", "3.0", "4.0"]

    def test_parse_already_completed_tasks(self) -> None:
        """Completed tasks (marked with [x]) should still be parsed."""
        content = """
- [x] 1.0 Completed task
  depends_on: []
- [ ] 2.0 Pending task
  depends_on: [1.0]
"""
        dependencies = parse_task_file(content)
        assert dependencies == {
            "1.0": [],
            "2.0": ["1.0"],
        }

    def test_parse_empty_content(self) -> None:
        dependencies = parse_task_file("")
        assert dependencies == {}

    def test_parse_whitespace_in_depends_on(self) -> None:
        content = """
- [ ] 1.0 Task A
  depends_on: [ 2.0 , 3.0 ]
"""
        dependencies = parse_task_file(content)
        assert dependencies["1.0"] == ["2.0", "3.0"]


class TestTaskDAGCycleDetection:
    """Tests for cycle detection in task dependencies."""

    def test_no_cycle_linear_chain(self) -> None:
        dag = TaskDAG({
            "1.0": [],
            "2.0": ["1.0"],
            "3.0": ["2.0"],
        })
        assert dag.detect_cycle() is None

    def test_no_cycle_diamond(self) -> None:
        """Diamond pattern: 1 -> 2 -> 4 and 1 -> 3 -> 4."""
        dag = TaskDAG({
            "1.0": [],
            "2.0": ["1.0"],
            "3.0": ["1.0"],
            "4.0": ["2.0", "3.0"],
        })
        assert dag.detect_cycle() is None

    def test_simple_cycle(self) -> None:
        dag = TaskDAG({
            "1.0": ["2.0"],
            "2.0": ["1.0"],
        })
        cycle = dag.detect_cycle()
        assert cycle is not None
        assert len(cycle) >= 2
        # Cycle should contain both nodes
        assert "1.0" in cycle and "2.0" in cycle

    def test_longer_cycle(self) -> None:
        dag = TaskDAG({
            "1.0": [],
            "2.0": ["1.0"],
            "3.0": ["2.0"],
            "4.0": ["3.0", "1.0"],  # 1 -> 2 -> 3 -> 4, 1 -> 4
        })
        # No cycle in this case
        assert dag.detect_cycle() is None

    def test_cycle_in_larger_graph(self) -> None:
        dag = TaskDAG({
            "1.0": [],
            "2.0": ["1.0"],
            "3.0": ["4.0"],  # 3 depends on 4
            "4.0": ["3.0"],  # 4 depends on 3 - cycle!
        })
        cycle = dag.detect_cycle()
        assert cycle is not None
        assert "3.0" in cycle and "4.0" in cycle

    def test_self_loop(self) -> None:
        dag = TaskDAG({
            "1.0": ["1.0"],  # Self-loop
        })
        cycle = dag.detect_cycle()
        assert cycle is not None
        assert "1.0" in cycle


class TestTaskDAGTopologicalSort:
    """Tests for topological sort producing valid execution order."""

    def test_simple_linear_order(self) -> None:
        dag = TaskDAG({
            "1.0": [],
            "2.0": ["1.0"],
            "3.0": ["2.0"],
        })
        order = dag.topological_sort()
        assert order.index("1.0") < order.index("2.0")
        assert order.index("2.0") < order.index("3.0")

    def test_diamond_order(self) -> None:
        dag = TaskDAG({
            "1.0": [],
            "2.0": ["1.0"],
            "3.0": ["1.0"],
            "4.0": ["2.0", "3.0"],
        })
        order = dag.topological_sort()
        assert order.index("1.0") < order.index("2.0")
        assert order.index("1.0") < order.index("3.0")
        assert order.index("2.0") < order.index("4.0")
        assert order.index("3.0") < order.index("4.0")

    def test_independent_tasks_all_present(self) -> None:
        dag = TaskDAG({
            "1.0": [],
            "2.0": [],
            "3.0": [],
        })
        order = dag.topological_sort()
        assert set(order) == {"1.0", "2.0", "3.0"}

    def test_raises_on_cycle(self) -> None:
        dag = TaskDAG({
            "1.0": ["2.0"],
            "2.0": ["1.0"],
        })
        with pytest.raises(CircularDependencyError):
            dag.topological_sort()


class TestTaskDAGGetReadyTasks:
    """Tests for getting tasks ready to execute."""

    def test_initial_ready_tasks(self) -> None:
        dag = TaskDAG({
            "1.0": [],
            "2.0": ["1.0"],
            "3.0": [],
        })
        ready = dag.get_ready_tasks(completed=set())
        assert set(ready) == {"1.0", "3.0"}

    def test_ready_after_completion(self) -> None:
        dag = TaskDAG({
            "1.0": [],
            "2.0": ["1.0"],
            "3.0": ["1.0"],
        })
        ready = dag.get_ready_tasks(completed={"1.0"})
        assert set(ready) == {"2.0", "3.0"}

    def test_ready_with_multiple_dependencies(self) -> None:
        dag = TaskDAG({
            "1.0": [],
            "2.0": [],
            "3.0": ["1.0", "2.0"],
        })
        # Task 3 not ready until both 1 and 2 complete
        ready = dag.get_ready_tasks(completed={"1.0"})
        assert "3.0" not in ready

        ready = dag.get_ready_tasks(completed={"1.0", "2.0"})
        assert "3.0" in ready

    def test_ready_excludes_completed(self) -> None:
        dag = TaskDAG({
            "1.0": [],
            "2.0": [],
        })
        ready = dag.get_ready_tasks(completed={"1.0"})
        assert "1.0" not in ready
        assert "2.0" in ready

    def test_all_completed_returns_empty(self) -> None:
        dag = TaskDAG({
            "1.0": [],
            "2.0": ["1.0"],
        })
        ready = dag.get_ready_tasks(completed={"1.0", "2.0"})
        assert ready == []


class TestTaskDAGTaskCount:
    """Tests for task count and iteration."""

    def test_task_count(self) -> None:
        dag = TaskDAG({
            "1.0": [],
            "2.0": ["1.0"],
            "3.0": [],
        })
        assert dag.task_count == 3

    def test_get_all_tasks(self) -> None:
        dag = TaskDAG({
            "1.0": [],
            "2.0": ["1.0"],
            "3.0": [],
        })
        assert set(dag.get_all_tasks()) == {"1.0", "2.0", "3.0"}


class TestCircularDependencyError:
    """Tests for CircularDependencyError exception."""

    def test_error_message_contains_cycle_path(self) -> None:
        err = CircularDependencyError(["3.0", "4.0", "3.0"])
        assert "3.0" in str(err)
        assert "4.0" in str(err)
        assert "Circular dependency" in str(err)
