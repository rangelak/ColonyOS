"""Tests for the repo_map module — file walking and Python AST extraction."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from colonyos.config import RepoMapConfig
from colonyos.repo_map import (
    FileSymbols,
    Symbol,
    SENSITIVE_PATTERNS,
    extract_python_symbols,
    get_tracked_files,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config() -> RepoMapConfig:
    """Default config for tests."""
    return RepoMapConfig()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repository for integration-style tests."""
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    return tmp_path


def _add_and_commit(repo: Path, files: dict[str, str]) -> None:
    """Helper: write files, git add, and commit."""
    for rel_path, content in files.items():
        full = repo / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "test"],
        cwd=repo, capture_output=True, check=True,
    )


# ===========================================================================
# Tests for get_tracked_files
# ===========================================================================

class TestGetTrackedFiles:
    """Tests for get_tracked_files() — FR-1, FR-6, FR-11."""

    def test_returns_tracked_files(self, git_repo: Path, config: RepoMapConfig):
        _add_and_commit(git_repo, {
            "src/app.py": "pass",
            "src/utils.py": "pass",
            "README.md": "# hello",
        })
        files = get_tracked_files(git_repo, config)
        assert sorted(files) == ["README.md", "src/app.py", "src/utils.py"]

    def test_filters_sensitive_env_files(self, git_repo: Path, config: RepoMapConfig):
        _add_and_commit(git_repo, {
            "app.py": "pass",
            ".env": "SECRET=x",
            ".env.local": "SECRET=x",
            ".env.production": "SECRET=x",
        })
        files = get_tracked_files(git_repo, config)
        assert files == ["app.py"]

    def test_filters_sensitive_credential_files(self, git_repo: Path, config: RepoMapConfig):
        _add_and_commit(git_repo, {
            "app.py": "pass",
            "credentials.json": "{}",
            "db_credentials.yaml": "{}",
        })
        files = get_tracked_files(git_repo, config)
        assert files == ["app.py"]

    def test_filters_sensitive_secret_files(self, git_repo: Path, config: RepoMapConfig):
        _add_and_commit(git_repo, {
            "app.py": "pass",
            "secrets.yaml": "{}",
            "my_secret.txt": "shh",
        })
        files = get_tracked_files(git_repo, config)
        assert files == ["app.py"]

    def test_filters_sensitive_key_and_pem_files(self, git_repo: Path, config: RepoMapConfig):
        _add_and_commit(git_repo, {
            "app.py": "pass",
            "server.pem": "cert",
            "private.key": "key",
        })
        files = get_tracked_files(git_repo, config)
        assert files == ["app.py"]

    def test_include_patterns_whitelist(self, git_repo: Path):
        _add_and_commit(git_repo, {
            "src/app.py": "pass",
            "src/utils.py": "pass",
            "docs/guide.md": "# hi",
            "tests/test_app.py": "pass",
        })
        config = RepoMapConfig(include_patterns=["*.py"])
        files = get_tracked_files(git_repo, config)
        assert all(f.endswith(".py") for f in files)
        assert "docs/guide.md" not in files

    def test_exclude_patterns_blacklist(self, git_repo: Path):
        _add_and_commit(git_repo, {
            "src/app.py": "pass",
            "src/utils.py": "pass",
            "docs/guide.md": "# hi",
        })
        config = RepoMapConfig(exclude_patterns=["*.md"])
        files = get_tracked_files(git_repo, config)
        assert "docs/guide.md" not in files
        assert "src/app.py" in files

    def test_file_count_cap(self, git_repo: Path, caplog):
        # Create more files than the cap
        file_map = {f"file_{i}.py": "pass" for i in range(10)}
        _add_and_commit(git_repo, file_map)

        config = RepoMapConfig(max_files=5)
        with caplog.at_level(logging.WARNING):
            files = get_tracked_files(git_repo, config)

        assert len(files) == 5
        assert "capping at 5" in caplog.text

    def test_no_warning_when_under_cap(self, git_repo: Path, caplog):
        _add_and_commit(git_repo, {"a.py": "pass", "b.py": "pass"})
        config = RepoMapConfig(max_files=100)
        with caplog.at_level(logging.WARNING):
            files = get_tracked_files(git_repo, config)
        assert len(files) == 2
        assert "capping" not in caplog.text

    def test_returns_empty_on_non_git_dir(self, tmp_path: Path, config: RepoMapConfig):
        files = get_tracked_files(tmp_path, config)
        assert files == []

    def test_returns_empty_on_timeout(self, git_repo: Path, config: RepoMapConfig):
        with patch("colonyos.repo_map.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30)):
            files = get_tracked_files(git_repo, config)
        assert files == []

    def test_returns_empty_on_os_error(self, git_repo: Path, config: RepoMapConfig):
        with patch("colonyos.repo_map.subprocess.run", side_effect=OSError("no git")):
            files = get_tracked_files(git_repo, config)
        assert files == []


# ===========================================================================
# Tests for extract_python_symbols
# ===========================================================================

class TestExtractPythonSymbols:
    """Tests for extract_python_symbols() — FR-2."""

    def test_extracts_module_docstring(self, tmp_path: Path):
        py = tmp_path / "mod.py"
        py.write_text('"""This is the module docstring.\n\nMore details here."""\n\nx = 1\n')
        result = extract_python_symbols(py)
        assert result.docstring == "This is the module docstring."

    def test_extracts_class_with_bases(self, tmp_path: Path):
        py = tmp_path / "models.py"
        py.write_text("class Dog(Animal, Serializable):\n    pass\n")
        result = extract_python_symbols(py)
        assert len(result.symbols) == 1
        cls = result.symbols[0]
        assert cls.name == "Dog"
        assert cls.kind == "class"
        assert cls.bases == ["Animal", "Serializable"]

    def test_extracts_class_methods(self, tmp_path: Path):
        py = tmp_path / "svc.py"
        py.write_text(
            "class Service:\n"
            "    def start(self, port: int) -> None:\n"
            "        pass\n"
            "    def stop(self):\n"
            "        pass\n"
        )
        result = extract_python_symbols(py)
        cls = result.symbols[0]
        assert cls.kind == "class"
        assert len(cls.children) == 2
        start = cls.children[0]
        assert start.name == "start"
        assert start.kind == "method"
        assert "port: int" in start.params
        assert "-> None" in start.params

    def test_extracts_top_level_functions(self, tmp_path: Path):
        py = tmp_path / "utils.py"
        py.write_text(
            "def add(a: int, b: int) -> int:\n"
            "    return a + b\n\n"
            "def greet(name: str) -> str:\n"
            "    return f'Hello {name}'\n"
        )
        result = extract_python_symbols(py)
        assert len(result.symbols) == 2
        assert result.symbols[0].name == "add"
        assert result.symbols[0].kind == "function"
        assert "a: int, b: int" in result.symbols[0].params
        assert "-> int" in result.symbols[0].params
        assert result.symbols[1].name == "greet"

    def test_extracts_async_functions(self, tmp_path: Path):
        py = tmp_path / "async_mod.py"
        py.write_text(
            "async def fetch(url: str) -> bytes:\n"
            "    pass\n"
        )
        result = extract_python_symbols(py)
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "fetch"
        assert result.symbols[0].kind == "function"

    def test_skips_self_and_cls_in_params(self, tmp_path: Path):
        py = tmp_path / "cls.py"
        py.write_text(
            "class Foo:\n"
            "    def bar(self, x: int) -> None:\n"
            "        pass\n"
            "    @classmethod\n"
            "    def create(cls, name: str) -> 'Foo':\n"
            "        pass\n"
        )
        result = extract_python_symbols(py)
        bar = result.symbols[0].children[0]
        assert "self" not in bar.params
        assert "x: int" in bar.params
        create = result.symbols[0].children[1]
        assert "cls" not in create.params
        assert "name: str" in create.params

    def test_handles_syntax_error_gracefully(self, tmp_path: Path, caplog):
        py = tmp_path / "bad.py"
        py.write_text("def broken(\n")
        with caplog.at_level(logging.WARNING):
            result = extract_python_symbols(py)
        assert result.symbols == []
        assert "Syntax error" in caplog.text

    def test_handles_empty_file(self, tmp_path: Path):
        py = tmp_path / "empty.py"
        py.write_text("")
        result = extract_python_symbols(py)
        assert result.symbols == []
        assert result.line_count == 0
        assert result.docstring == ""

    def test_line_count_and_size(self, tmp_path: Path):
        py = tmp_path / "counted.py"
        content = "x = 1\ny = 2\nz = 3\n"
        py.write_text(content)
        result = extract_python_symbols(py)
        assert result.line_count == 3
        assert result.size_bytes == len(content.encode("utf-8"))

    def test_handles_unreadable_file(self, tmp_path: Path, caplog):
        py = tmp_path / "gone.py"
        # File doesn't exist
        with caplog.at_level(logging.WARNING):
            result = extract_python_symbols(py)
        assert result.symbols == []
        assert "Could not read" in caplog.text

    def test_handles_encoding_error(self, tmp_path: Path, caplog):
        py = tmp_path / "binary.py"
        py.write_bytes(b"\x80\x81\x82\xff\xfe")
        with caplog.at_level(logging.WARNING):
            result = extract_python_symbols(py)
        assert result.symbols == []

    def test_varargs_and_kwargs(self, tmp_path: Path):
        py = tmp_path / "varargs.py"
        py.write_text(
            "def process(*args: str, **kwargs: int) -> None:\n"
            "    pass\n"
        )
        result = extract_python_symbols(py)
        func = result.symbols[0]
        assert "*args: str" in func.params
        assert "**kwargs: int" in func.params

    def test_class_no_bases(self, tmp_path: Path):
        py = tmp_path / "plain.py"
        py.write_text("class Plain:\n    pass\n")
        result = extract_python_symbols(py)
        cls = result.symbols[0]
        assert cls.name == "Plain"
        assert cls.bases == []

    def test_mixed_classes_and_functions(self, tmp_path: Path):
        py = tmp_path / "mixed.py"
        py.write_text(
            '"""Module doc."""\n\n'
            "class Config:\n"
            "    def load(self) -> dict:\n"
            "        pass\n\n"
            "def helper() -> None:\n"
            "    pass\n\n"
            "class Runner(Config):\n"
            "    def run(self) -> int:\n"
            "        pass\n"
        )
        result = extract_python_symbols(py)
        assert result.docstring == "Module doc."
        names = [s.name for s in result.symbols]
        assert names == ["Config", "helper", "Runner"]
        assert result.symbols[0].kind == "class"
        assert result.symbols[1].kind == "function"
        assert result.symbols[2].kind == "class"
        assert result.symbols[2].bases == ["Config"]
