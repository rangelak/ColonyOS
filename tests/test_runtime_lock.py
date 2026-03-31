from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from colonyos.runtime_lock import (
    RepoRuntimeGuard,
    RuntimeBusyError,
    RuntimeProcessRecord,
    terminate_related_runtime_processes,
)


def test_repo_runtime_guard_writes_lock_and_registry(tmp_path: Path) -> None:
    with RepoRuntimeGuard(tmp_path, "run"):
        lock_path = tmp_path / ".colonyos" / "runtime.lock"
        registry_path = tmp_path / ".colonyos" / "runtime_processes.json"

        assert lock_path.exists()
        assert registry_path.exists()
        assert '"mode": "run"' in lock_path.read_text(encoding="utf-8")
        assert str(os.getpid()) in registry_path.read_text(encoding="utf-8")


def test_repo_runtime_guard_releases_registry_entry(tmp_path: Path) -> None:
    with RepoRuntimeGuard(tmp_path, "queue-start"):
        pass

    registry_path = tmp_path / ".colonyos" / "runtime_processes.json"
    assert registry_path.exists()
    assert '"processes": []' in registry_path.read_text(encoding="utf-8")


def test_repo_runtime_guard_blocks_other_process(tmp_path: Path) -> None:
    code = """
from pathlib import Path
import sys
import time
from colonyos.runtime_lock import RepoRuntimeGuard

guard = RepoRuntimeGuard(Path(sys.argv[1]), "child").acquire()
print("ready", flush=True)
time.sleep(30)
guard.release()
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(sys.path)
    proc = subprocess.Popen(
        [sys.executable, "-c", code, str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "ready"
        with pytest.raises(RuntimeBusyError, match="Another ColonyOS runtime"):
            RepoRuntimeGuard(tmp_path, "parent").acquire()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def test_terminate_related_runtime_processes_targets_descendants_and_other_runtimes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    current_record = RuntimeProcessRecord(
        pid=100,
        mode="run",
        cwd=str(tmp_path),
        started_at="now",
        command="colonyos run",
    )
    other_record = RuntimeProcessRecord(
        pid=200,
        mode="watch-slack",
        cwd=str(tmp_path),
        started_at="now",
        command="colonyos watch-slack",
    )
    sent: list[tuple[str, set[int]]] = []

    monkeypatch.setattr(
        "colonyos.runtime_lock._load_registry_records",
        lambda _repo_root: [current_record, other_record],
    )

    def _fake_descendants(pid: int) -> list[int]:
        return {
            100: [101, 102],
            200: [201],
        }.get(pid, [])

    monkeypatch.setattr("colonyos.runtime_lock._list_descendant_pids", _fake_descendants)
    monkeypatch.setattr(
        "colonyos.runtime_lock._signal_pids",
        lambda pids, sig: sent.append((sig.name, set(pids))),
    )

    waits = iter([{201}, set()])
    monkeypatch.setattr(
        "colonyos.runtime_lock._wait_for_exit",
        lambda pids, timeout_seconds: next(waits),
    )

    terminate_related_runtime_processes(tmp_path, current_pid=100)

    assert sent == [
        ("SIGTERM", {101, 102, 200, 201}),
        ("SIGKILL", {201}),
    ]
