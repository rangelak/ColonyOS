from __future__ import annotations

import fcntl
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from colonyos.cancellation import register_cancel_callback, unregister_cancel_callback
from colonyos.daemon_state import atomic_write_json

logger = logging.getLogger(__name__)

_RUNTIME_LOCK_FILE = ".colonyos/runtime.lock"
_RUNTIME_REGISTRY_FILE = ".colonyos/runtime_processes.json"


@dataclass
class RuntimeProcessRecord:
    pid: int
    mode: str
    cwd: str
    started_at: str
    command: str
    pgid: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "mode": self.mode,
            "cwd": self.cwd,
            "started_at": self.started_at,
            "command": self.command,
            "pgid": self.pgid,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeProcessRecord | None:
        raw_pid = data.get("pid")
        if raw_pid is None:
            return None
        try:
            pid = int(raw_pid)
        except (TypeError, ValueError):
            return None
        mode = str(data.get("mode") or "unknown")
        cwd = str(data.get("cwd") or "")
        started_at = str(data.get("started_at") or "")
        command = str(data.get("command") or "")
        raw_pgid = data.get("pgid")
        try:
            pgid = int(raw_pgid) if raw_pgid is not None else None
        except (TypeError, ValueError):
            pgid = None
        return cls(
            pid=pid,
            mode=mode,
            cwd=cwd,
            started_at=started_at,
            command=command,
            pgid=pgid,
        )


class RuntimeBusyError(RuntimeError):
    """Raised when another ColonyOS runtime already owns this repo."""

    def __init__(self, repo_root: Path, record: RuntimeProcessRecord | None = None) -> None:
        self.repo_root = repo_root
        self.record = record
        lock_path = repo_root / _RUNTIME_LOCK_FILE
        if record is None:
            message = (
                f"Another ColonyOS runtime is already active for this repo "
                f"(lock file: {lock_path})."
            )
        else:
            message = (
                "Another ColonyOS runtime is already active for this repo "
                f"(mode={record.mode}, pid={record.pid}, cwd={record.cwd}, "
                f"started_at={record.started_at}, lock file: {lock_path})."
            )
        super().__init__(message)


class RepoRuntimeGuard:
    """Cross-process repo lock plus best-effort runtime cleanup hooks."""

    def __init__(self, repo_root: Path, mode: str) -> None:
        self.repo_root = repo_root
        self.mode = mode
        self._fd: int | None = None
        self._cancel_token: str | None = None
        self._cancelled = False
        self.record = RuntimeProcessRecord(
            pid=os.getpid(),
            mode=mode,
            cwd=str(Path.cwd()),
            started_at=datetime.now(timezone.utc).isoformat(),
            command=" ".join(sys.argv),
            pgid=_safe_getpgid(os.getpid()),
        )

    def acquire(self) -> RepoRuntimeGuard:
        lock_path = self.repo_root / _RUNTIME_LOCK_FILE
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            raise RuntimeBusyError(self.repo_root, _read_lock_record(lock_path)) from exc

        self._fd = fd
        self._write_lock_record()
        _upsert_registry_record(self.repo_root, self.record)
        self._cancel_token = register_cancel_callback(self._handle_cancel)
        return self

    def release(self) -> None:
        if self._cancel_token is not None:
            unregister_cancel_callback(self._cancel_token)
            self._cancel_token = None
        _remove_registry_record(self.repo_root, self.record.pid)
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def _write_lock_record(self) -> None:
        if self._fd is None:
            return
        payload = json.dumps(self.record.to_dict(), indent=2).encode("utf-8")
        os.ftruncate(self._fd, 0)
        os.lseek(self._fd, 0, os.SEEK_SET)
        os.write(self._fd, payload)
        os.fsync(self._fd)

    def _handle_cancel(self, reason: str) -> None:
        if self._cancelled:
            return
        self._cancelled = True
        logger.info(
            "Runtime cancellation requested for %s (pid=%s): %s",
            self.mode,
            self.record.pid,
            reason,
        )
        terminate_related_runtime_processes(
            self.repo_root,
            current_pid=self.record.pid,
        )

    def __enter__(self) -> RepoRuntimeGuard:
        return self.acquire()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.release()


def terminate_related_runtime_processes(
    repo_root: Path,
    *,
    current_pid: int,
    grace_seconds: float = 2.0,
) -> None:
    """Best-effort shutdown for other registered runtimes and our descendants."""
    registry_records = _load_registry_records(repo_root)

    target_pids: set[int] = set(_list_descendant_pids(current_pid))
    for record in registry_records:
        if record.pid == current_pid:
            continue
        target_pids.add(record.pid)
        target_pids.update(_list_descendant_pids(record.pid))

    if not target_pids:
        return

    _signal_pids(target_pids, signal.SIGTERM)
    survivors = _wait_for_exit(target_pids, timeout_seconds=grace_seconds)
    if survivors:
        _signal_pids(survivors, signal.SIGKILL)
        _wait_for_exit(survivors, timeout_seconds=1.0)


def _registry_path(repo_root: Path) -> Path:
    return repo_root / _RUNTIME_REGISTRY_FILE


def _lock_path(repo_root: Path) -> Path:
    return repo_root / _RUNTIME_LOCK_FILE


def _read_lock_record(lock_path: Path) -> RuntimeProcessRecord | None:
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return RuntimeProcessRecord.from_dict(data)


def _load_registry_records(repo_root: Path) -> list[RuntimeProcessRecord]:
    path = _registry_path(repo_root)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    raw_records = data.get("processes", [])
    if not isinstance(raw_records, list):
        return []

    live_records: list[RuntimeProcessRecord] = []
    changed = False
    for raw_record in raw_records:
        if not isinstance(raw_record, dict):
            changed = True
            continue
        record = RuntimeProcessRecord.from_dict(raw_record)
        if record is None or not _process_exists(record.pid):
            changed = True
            continue
        live_records.append(record)

    if changed:
        _write_registry_records(repo_root, live_records)
    return live_records


def _write_registry_records(repo_root: Path, records: list[RuntimeProcessRecord]) -> None:
    path = _registry_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        path,
        {"processes": [record.to_dict() for record in records]},
    )


def _upsert_registry_record(repo_root: Path, record: RuntimeProcessRecord) -> None:
    records = [existing for existing in _load_registry_records(repo_root) if existing.pid != record.pid]
    records.append(record)
    _write_registry_records(repo_root, records)


def _remove_registry_record(repo_root: Path, pid: int) -> None:
    path = _registry_path(repo_root)
    if not path.exists():
        return
    records = [record for record in _load_registry_records(repo_root) if record.pid != pid]
    _write_registry_records(repo_root, records)


def _list_descendant_pids(root_pid: int) -> list[int]:
    if root_pid <= 0 or not _process_exists(root_pid):
        return []
    try:
        result = os.popen("ps -axo pid=,ppid=").read()
    except OSError:
        return []

    parent_map: dict[int, list[int]] = {}
    for line in result.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        parent_map.setdefault(ppid, []).append(pid)

    descendants: list[int] = []
    stack = list(parent_map.get(root_pid, []))
    seen: set[int] = set()
    while stack:
        pid = stack.pop()
        if pid in seen or pid == root_pid:
            continue
        seen.add(pid)
        descendants.append(pid)
        stack.extend(parent_map.get(pid, []))
    return descendants


def _signal_pids(pids: set[int], sig: signal.Signals) -> None:
    for pid in sorted(pids):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            continue
        except OSError:
            logger.debug("Failed to signal pid %s with %s", pid, sig, exc_info=True)


def _wait_for_exit(pids: set[int], *, timeout_seconds: float) -> set[int]:
    deadline = time.monotonic() + timeout_seconds
    remaining = {pid for pid in pids if _process_exists(pid)}
    while remaining and time.monotonic() < deadline:
        time.sleep(0.1)
        remaining = {pid for pid in remaining if _process_exists(pid)}
    return remaining


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _safe_getpgid(pid: int) -> int | None:
    try:
        return os.getpgid(pid)
    except OSError:
        return None
