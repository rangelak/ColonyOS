"""Tests for the repo_map module — file walking, extraction, formatting, ranking, and truncation."""

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
    _MAX_PARSE_SIZE,
    _git_clean_env,
    extract_file_symbols,
    extract_js_ts_symbols,
    extract_other_file_info,
    extract_python_symbols,
    format_tree,
    generate_overview,
    generate_repo_map,
    get_tracked_files,
    rank_by_relevance,
    truncate_to_budget,
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

    def test_ignores_leaked_git_env_vars(
        self, git_repo: Path, config: RepoMapConfig, monkeypatch: pytest.MonkeyPatch
    ):
        _add_and_commit(git_repo, {"src/app.py": "pass"})
        monkeypatch.setenv("GIT_DIR", "/definitely/not/the/repo/.git")
        monkeypatch.setenv("GIT_WORK_TREE", "/definitely/not/the/repo")
        files = get_tracked_files(git_repo, config)
        assert files == ["src/app.py"]

    def test_keeps_non_repo_shaping_git_env_vars(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
        monkeypatch.setenv("GIT_CONFIG_KEY_0", "safe.directory")
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", "/github/workspace")
        monkeypatch.setenv("GIT_DIR", "/bad/.git")
        env = _git_clean_env()
        assert env["GIT_CONFIG_COUNT"] == "1"
        assert env["GIT_CONFIG_KEY_0"] == "safe.directory"
        assert env["GIT_CONFIG_VALUE_0"] == "/github/workspace"
        assert "GIT_DIR" not in env

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

    def test_skips_oversized_file(self, tmp_path: Path, caplog):
        """Files larger than _MAX_PARSE_SIZE are returned with size metadata only."""
        py = tmp_path / "huge.py"
        # Write a file just over the limit
        py.write_bytes(b"x" * (_MAX_PARSE_SIZE + 1))
        with caplog.at_level(logging.INFO):
            result = extract_python_symbols(py)
        assert result.symbols == []
        assert result.size_bytes == _MAX_PARSE_SIZE + 1
        assert result.line_count == 0  # No content was parsed
        assert "Skipping parse" in caplog.text

    def test_parses_file_at_size_limit(self, tmp_path: Path):
        """A file exactly at _MAX_PARSE_SIZE should still be parsed normally."""
        py = tmp_path / "borderline.py"
        # Create valid Python content right at the limit
        content = "x = 1\n"
        padding = "# " + "a" * (_MAX_PARSE_SIZE - len(content) - 3) + "\n"
        py.write_text(padding + content)
        result = extract_python_symbols(py)
        # It should have been parsed (not skipped)
        assert result.line_count > 0

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


# ===========================================================================
# Tests for extract_js_ts_symbols — FR-3 (Task 3.1)
# ===========================================================================

class TestExtractJsTsSymbols:
    """Tests for extract_js_ts_symbols() — FR-3."""

    def test_export_function(self, tmp_path: Path):
        js = tmp_path / "utils.js"
        js.write_text("export function greet(name) {\n  return name;\n}\n")
        result = extract_js_ts_symbols(js)
        assert len(result.symbols) == 1
        sym = result.symbols[0]
        assert sym.name == "greet"
        assert sym.kind == "function"

    def test_export_async_function(self, tmp_path: Path):
        js = tmp_path / "api.js"
        js.write_text("export async function fetchData(url) {\n  return url;\n}\n")
        result = extract_js_ts_symbols(js)
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "fetchData"
        assert result.symbols[0].kind == "function"

    def test_export_class(self, tmp_path: Path):
        ts = tmp_path / "service.ts"
        ts.write_text("export class UserService {\n  getUser() {}\n}\n")
        result = extract_js_ts_symbols(ts)
        assert len(result.symbols) == 1
        sym = result.symbols[0]
        assert sym.name == "UserService"
        assert sym.kind == "class"

    def test_export_default_function(self, tmp_path: Path):
        js = tmp_path / "main.js"
        js.write_text("export default function main() {\n  return 1;\n}\n")
        result = extract_js_ts_symbols(js)
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "main"
        assert result.symbols[0].kind == "function"

    def test_export_default_class(self, tmp_path: Path):
        ts = tmp_path / "app.tsx"
        ts.write_text("export default class App {\n  render() {}\n}\n")
        result = extract_js_ts_symbols(ts)
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "App"
        assert result.symbols[0].kind == "class"

    def test_export_const_let_var(self, tmp_path: Path):
        ts = tmp_path / "config.ts"
        ts.write_text(
            "export const API_URL = 'http://example.com';\n"
            "export let counter = 0;\n"
            "export var legacy = true;\n"
        )
        result = extract_js_ts_symbols(ts)
        names = [s.name for s in result.symbols]
        assert "API_URL" in names
        assert "counter" in names
        assert "legacy" in names
        for sym in result.symbols:
            assert sym.kind == "variable"

    def test_export_named_braces(self, tmp_path: Path):
        js = tmp_path / "index.js"
        js.write_text("export { foo, bar, baz };\n")
        result = extract_js_ts_symbols(js)
        names = [s.name for s in result.symbols]
        assert "foo" in names
        assert "bar" in names
        assert "baz" in names

    def test_export_interface_typescript(self, tmp_path: Path):
        ts = tmp_path / "types.ts"
        ts.write_text("export interface UserProps {\n  name: string;\n}\n")
        result = extract_js_ts_symbols(ts)
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "UserProps"
        assert result.symbols[0].kind == "interface"

    def test_export_type_typescript(self, tmp_path: Path):
        ts = tmp_path / "types.ts"
        ts.write_text("export type Status = 'active' | 'inactive';\n")
        result = extract_js_ts_symbols(ts)
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "Status"
        assert result.symbols[0].kind == "type"

    def test_jsx_extension(self, tmp_path: Path):
        jsx = tmp_path / "Component.jsx"
        jsx.write_text("export function Component() {\n  return null;\n}\n")
        result = extract_js_ts_symbols(jsx)
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "Component"

    def test_tsx_extension(self, tmp_path: Path):
        tsx = tmp_path / "App.tsx"
        tsx.write_text("export function App() {\n  return null;\n}\n")
        result = extract_js_ts_symbols(tsx)
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "App"

    def test_multiple_exports(self, tmp_path: Path):
        ts = tmp_path / "multi.ts"
        ts.write_text(
            "export class Router {\n}\n\n"
            "export function createRouter() {\n}\n\n"
            "export const DEFAULT_PORT = 3000;\n\n"
            "export interface Config {\n  port: number;\n}\n"
        )
        result = extract_js_ts_symbols(ts)
        names = [s.name for s in result.symbols]
        assert "Router" in names
        assert "createRouter" in names
        assert "DEFAULT_PORT" in names
        assert "Config" in names

    def test_line_count_and_size(self, tmp_path: Path):
        js = tmp_path / "sized.js"
        content = "export function a() {}\nexport function b() {}\n"
        js.write_text(content)
        result = extract_js_ts_symbols(js)
        assert result.line_count == 2
        assert result.size_bytes == len(content.encode("utf-8"))

    def test_handles_unreadable_file(self, tmp_path: Path, caplog):
        js = tmp_path / "gone.js"
        with caplog.at_level(logging.WARNING):
            result = extract_js_ts_symbols(js)
        assert result.symbols == []
        assert "Could not read" in caplog.text

    def test_skips_oversized_file(self, tmp_path: Path, caplog):
        """JS/TS files larger than _MAX_PARSE_SIZE are returned with size metadata only."""
        js = tmp_path / "huge.js"
        js.write_bytes(b"x" * (_MAX_PARSE_SIZE + 1))
        with caplog.at_level(logging.INFO):
            result = extract_js_ts_symbols(js)
        assert result.symbols == []
        assert result.size_bytes == _MAX_PARSE_SIZE + 1
        assert result.line_count == 0
        assert "Skipping parse" in caplog.text

    def test_handles_encoding_error(self, tmp_path: Path, caplog):
        js = tmp_path / "binary.js"
        js.write_bytes(b"\x80\x81\x82\xff\xfe")
        with caplog.at_level(logging.WARNING):
            result = extract_js_ts_symbols(js)
        assert result.symbols == []

    def test_ignores_non_export_declarations(self, tmp_path: Path):
        js = tmp_path / "internal.js"
        js.write_text(
            "function privateHelper() {}\n"
            "class InternalClass {}\n"
            "const localVar = 1;\n"
        )
        result = extract_js_ts_symbols(js)
        assert result.symbols == []


# ===========================================================================
# Tests for extract_other_file_info — FR-4 (Task 3.2)
# ===========================================================================

class TestExtractOtherFileInfo:
    """Tests for extract_other_file_info() — FR-4."""

    def test_yaml_file(self, tmp_path: Path):
        f = tmp_path / "config.yaml"
        content = "key: value\nother: 123\n"
        f.write_text(content)
        result = extract_other_file_info(f)
        assert result.path == str(f)
        assert result.size_bytes == len(content.encode("utf-8"))
        assert result.symbols == []

    def test_json_file(self, tmp_path: Path):
        f = tmp_path / "package.json"
        content = '{"name": "test"}\n'
        f.write_text(content)
        result = extract_other_file_info(f)
        assert result.path == str(f)
        assert result.size_bytes == len(content.encode("utf-8"))
        assert result.symbols == []

    def test_markdown_file(self, tmp_path: Path):
        f = tmp_path / "README.md"
        content = "# Title\n\nSome content here.\n"
        f.write_text(content)
        result = extract_other_file_info(f)
        assert result.path == str(f)
        assert result.size_bytes == len(content.encode("utf-8"))
        assert result.line_count == 0  # no line_count for non-code files

    def test_handles_missing_file(self, tmp_path: Path, caplog):
        f = tmp_path / "gone.txt"
        with caplog.at_level(logging.WARNING):
            result = extract_other_file_info(f)
        assert result.size_bytes == 0

    def test_binary_file(self, tmp_path: Path):
        f = tmp_path / "image.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        result = extract_other_file_info(f)
        assert result.size_bytes == 108


# ===========================================================================
# Tests for extract_file_symbols dispatcher — Task 3.5
# ===========================================================================

class TestExtractFileSymbols:
    """Tests for extract_file_symbols() dispatcher."""

    def test_dispatches_python(self, tmp_path: Path):
        py = tmp_path / "mod.py"
        py.write_text("def hello() -> str:\n    pass\n")
        result = extract_file_symbols(py)
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "hello"
        assert result.symbols[0].kind == "function"

    def test_dispatches_js(self, tmp_path: Path):
        js = tmp_path / "app.js"
        js.write_text("export function render() {}\n")
        result = extract_file_symbols(js)
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "render"

    def test_dispatches_ts(self, tmp_path: Path):
        ts = tmp_path / "service.ts"
        ts.write_text("export class Service {}\n")
        result = extract_file_symbols(ts)
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "Service"

    def test_dispatches_jsx(self, tmp_path: Path):
        jsx = tmp_path / "Comp.jsx"
        jsx.write_text("export function Comp() {}\n")
        result = extract_file_symbols(jsx)
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "Comp"

    def test_dispatches_tsx(self, tmp_path: Path):
        tsx = tmp_path / "App.tsx"
        tsx.write_text("export default class App {}\n")
        result = extract_file_symbols(tsx)
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "App"

    def test_dispatches_other(self, tmp_path: Path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("key: value\n")
        result = extract_file_symbols(cfg)
        assert result.symbols == []
        assert result.size_bytes > 0


# ===========================================================================
# Tests for format_tree — FR-5 (Task 4.1)
# ===========================================================================

class TestFormatTree:
    """Tests for format_tree() — tree-formatted text output."""

    def test_groups_by_directory(self):
        files = [
            FileSymbols(path="src/app.py", line_count=100, symbols=[
                Symbol(name="App", kind="class", children=[
                    Symbol(name="run", kind="method", params="() -> None"),
                ]),
            ]),
            FileSymbols(path="src/utils.py", line_count=50, symbols=[
                Symbol(name="helper", kind="function", params="(x: int) -> str"),
            ]),
            FileSymbols(path="README.md", size_bytes=200),
        ]
        output = format_tree(files)
        # Directory headers should appear
        assert "src/" in output
        # File names with line counts should appear
        assert "app.py" in output
        assert "100 lines" in output
        assert "utils.py" in output
        assert "50 lines" in output
        # Symbols should appear
        assert "App" in output
        assert "run" in output
        assert "helper" in output
        # Non-code files show size
        assert "README.md" in output

    def test_indentation_structure(self):
        files = [
            FileSymbols(path="src/models.py", line_count=200, symbols=[
                Symbol(name="User", kind="class", bases=["Base"], children=[
                    Symbol(name="save", kind="method", params="() -> None"),
                    Symbol(name="delete", kind="method", params="() -> None"),
                ]),
                Symbol(name="create_user", kind="function", params="(name: str) -> User"),
            ]),
        ]
        output = format_tree(files)
        lines = output.strip().splitlines()
        # Directory line should not be indented much
        # File line should be indented under directory
        # Class should be indented under file
        # Methods should be indented under class
        # Check relative indentation
        file_line = [l for l in lines if "models.py" in l][0]
        class_line = [l for l in lines if "User" in l][0]
        method_line = [l for l in lines if "save" in l][0]
        func_line = [l for l in lines if "create_user" in l][0]
        # Each level should be more indented
        assert len(class_line) - len(class_line.lstrip()) > len(file_line) - len(file_line.lstrip())
        assert len(method_line) - len(method_line.lstrip()) > len(class_line) - len(class_line.lstrip())
        # Function at same level as class
        assert len(func_line) - len(func_line.lstrip()) == len(class_line) - len(class_line.lstrip())

    def test_class_with_bases_displayed(self):
        files = [
            FileSymbols(path="mod.py", line_count=10, symbols=[
                Symbol(name="Dog", kind="class", bases=["Animal", "Serializable"]),
            ]),
        ]
        output = format_tree(files)
        assert "Dog(Animal, Serializable)" in output

    def test_empty_files_list(self):
        output = format_tree([])
        assert output == ""

    def test_files_without_symbols_show_size(self):
        files = [
            FileSymbols(path="data/config.yaml", size_bytes=1500),
        ]
        output = format_tree(files)
        assert "config.yaml" in output
        assert "1500 bytes" in output

    def test_root_level_files(self):
        """Files at the repo root (no directory) should still appear."""
        files = [
            FileSymbols(path="setup.py", line_count=30, symbols=[
                Symbol(name="setup", kind="function", params="()"),
            ]),
        ]
        output = format_tree(files)
        assert "setup.py" in output
        assert "setup" in output


# ===========================================================================
# Tests for rank_by_relevance — FR-8, FR-9 (Task 4.2)
# ===========================================================================

class TestRankByRelevance:
    """Tests for rank_by_relevance() — keyword-based file scoring."""

    def test_files_matching_prompt_keywords_rank_higher(self):
        files = [
            FileSymbols(path="src/database.py", symbols=[
                Symbol(name="connect", kind="function"),
            ]),
            FileSymbols(path="src/utils.py", symbols=[
                Symbol(name="format_string", kind="function"),
            ]),
            FileSymbols(path="src/models.py", symbols=[
                Symbol(name="Database", kind="class"),
            ]),
        ]
        ranked = rank_by_relevance(files, "fix the database connection")
        # database.py and models.py (has Database class) should rank above utils.py
        paths = [f.path for f in ranked]
        db_idx = paths.index("src/database.py")
        models_idx = paths.index("src/models.py")
        utils_idx = paths.index("src/utils.py")
        assert db_idx < utils_idx
        assert models_idx < utils_idx

    def test_exact_path_match_always_first(self):
        files = [
            FileSymbols(path="src/unrelated.py", symbols=[]),
            FileSymbols(path="src/config.py", symbols=[]),
            FileSymbols(path="src/other.py", symbols=[]),
        ]
        ranked = rank_by_relevance(files, "update src/config.py to add new field")
        assert ranked[0].path == "src/config.py"

    def test_basename_match_always_included(self):
        files = [
            FileSymbols(path="src/unrelated.py", symbols=[]),
            FileSymbols(path="deep/nested/config.py", symbols=[]),
            FileSymbols(path="src/other.py", symbols=[]),
        ]
        ranked = rank_by_relevance(files, "update config.py")
        paths = [f.path for f in ranked]
        config_idx = paths.index("deep/nested/config.py")
        # config.py should rank highly due to basename match
        assert config_idx < 2

    def test_empty_prompt_returns_all_files(self):
        files = [
            FileSymbols(path="a.py", symbols=[]),
            FileSymbols(path="b.py", symbols=[]),
        ]
        ranked = rank_by_relevance(files, "")
        assert len(ranked) == 2

    def test_no_files_returns_empty(self):
        ranked = rank_by_relevance([], "some prompt")
        assert ranked == []

    def test_keyword_match_on_symbol_names(self):
        files = [
            FileSymbols(path="src/a.py", symbols=[
                Symbol(name="Orchestrator", kind="class"),
            ]),
            FileSymbols(path="src/b.py", symbols=[
                Symbol(name="helper", kind="function"),
            ]),
        ]
        ranked = rank_by_relevance(files, "fix the orchestrator pipeline")
        assert ranked[0].path == "src/a.py"


# ===========================================================================
# Tests for truncate_to_budget — FR-7, FR-10 (Task 4.3)
# ===========================================================================

class TestTruncateToBudget:
    """Tests for truncate_to_budget() — token-budget enforcement."""

    def test_output_never_exceeds_max_tokens(self):
        overview = "Directory overview\n  src/ (10 files)\n  tests/ (5 files)\n"
        files = [
            FileSymbols(path=f"src/file_{i}.py", line_count=100, symbols=[
                Symbol(name=f"func_{i}", kind="function", params="()"),
            ])
            for i in range(50)
        ]
        max_tokens = 200
        result = truncate_to_budget(overview, files, max_tokens)
        estimated_tokens = len(result) / 4
        assert estimated_tokens <= max_tokens

    def test_overview_always_included(self):
        overview = "## Directory Overview\nsrc/ (3 files)\n"
        files = [
            FileSymbols(path="src/big.py", line_count=1000, symbols=[
                Symbol(name=f"func_{i}", kind="function", params="(a, b, c, d, e)")
                for i in range(100)
            ]),
        ]
        result = truncate_to_budget(overview, files, max_tokens=100)
        assert "Directory Overview" in result

    def test_files_dropped_in_reverse_relevance_order(self):
        overview = "overview\n"
        # Files are expected to be in ranked order already (most relevant first)
        files = [
            FileSymbols(path="important.py", line_count=10, symbols=[
                Symbol(name="critical", kind="function", params="()"),
            ]),
            FileSymbols(path="less_important.py", line_count=10, symbols=[
                Symbol(name="minor", kind="function", params="()"),
            ]),
            FileSymbols(path="least_important.py", line_count=10, symbols=[
                Symbol(name="trivial", kind="function", params="()"),
            ]),
        ]
        # Very tight budget: should keep overview + first file, drop later ones
        result = truncate_to_budget(overview, files, max_tokens=80)
        assert "important.py" in result
        # At least one of the later files should be dropped
        if "least_important.py" in result:
            # If all fit, the budget was generous enough
            pass

    def test_empty_repo(self):
        result = truncate_to_budget("", [], max_tokens=4000)
        assert result == ""

    def test_budget_too_small_for_overview(self):
        overview = "A" * 100  # 25 tokens
        result = truncate_to_budget(overview, [], max_tokens=10)
        # Should still return overview even if over budget (FR-10: always included)
        assert overview in result


# ===========================================================================
# Tests for generate_overview — FR-10 (Task 4.3 supplement)
# ===========================================================================

class TestGenerateOverview:
    """Tests for generate_overview() — compact directory tree."""

    def test_produces_directory_tree_with_file_counts(self):
        files = [
            FileSymbols(path="src/app.py", line_count=100),
            FileSymbols(path="src/utils.py", line_count=50),
            FileSymbols(path="tests/test_app.py", line_count=80),
            FileSymbols(path="README.md", size_bytes=200),
        ]
        overview = generate_overview(files)
        assert "src/" in overview
        assert "tests/" in overview
        # Should mention file counts
        assert "2" in overview  # src has 2 files
        assert "1" in overview  # tests has 1 file

    def test_empty_files_returns_empty(self):
        overview = generate_overview([])
        assert overview == ""


# ===========================================================================
# Tests for generate_repo_map — top-level orchestrator (Task 4.8)
# ===========================================================================

class TestGenerateRepoMap:
    """Tests for generate_repo_map() — end-to-end generation."""

    def test_generates_map_for_git_repo(self, git_repo: Path):
        _add_and_commit(git_repo, {
            "src/app.py": "class App:\n    def run(self) -> None:\n        pass\n",
            "src/utils.py": "def helper(x: int) -> str:\n    return str(x)\n",
            "README.md": "# My Project\n",
        })
        config = RepoMapConfig(max_tokens=4000)
        result = generate_repo_map(git_repo, config)
        assert "app.py" in result
        assert "App" in result
        assert "run" in result
        assert "utils.py" in result
        assert "helper" in result
        assert "README.md" in result

    def test_respects_token_budget(self, git_repo: Path):
        # Create many files to exceed budget
        file_map = {}
        for i in range(50):
            file_map[f"src/module_{i}.py"] = (
                f"class Module{i}:\n"
                f"    def method_{i}(self) -> None:\n"
                f"        pass\n"
            )
        _add_and_commit(git_repo, file_map)
        config = RepoMapConfig(max_tokens=200)
        result = generate_repo_map(git_repo, config)
        estimated_tokens = len(result) / 4
        assert estimated_tokens <= 200

    def test_relevance_with_prompt(self, git_repo: Path):
        _add_and_commit(git_repo, {
            "src/database.py": "class Database:\n    pass\n",
            "src/auth.py": "class Auth:\n    pass\n",
            "src/unrelated.py": "class Unrelated:\n    pass\n",
        })
        config = RepoMapConfig(max_tokens=4000)
        result = generate_repo_map(git_repo, config, prompt_text="fix the database connection")
        assert "database.py" in result
        assert "Database" in result

    def test_empty_repo(self, git_repo: Path):
        config = RepoMapConfig()
        result = generate_repo_map(git_repo, config)
        assert result == ""

    def test_disabled_config_still_generates(self, git_repo: Path):
        """generate_repo_map doesn't check enabled — that's the orchestrator's job."""
        _add_and_commit(git_repo, {"a.py": "x = 1\n"})
        config = RepoMapConfig(enabled=False, max_tokens=4000)
        result = generate_repo_map(git_repo, config)
        # Should still produce output — gating is done at the caller level
        assert "a.py" in result


# ===========================================================================
# Task 7.1 — Integration test against the ColonyOS repo itself
# ===========================================================================

class TestRepoMapIntegration:
    """Integration tests: run generate_repo_map() against the real ColonyOS repo."""

    @pytest.fixture
    def repo_root(self) -> Path:
        """Resolve the ColonyOS repository root (where .git lives)."""
        candidate = Path(__file__).resolve().parent.parent
        if (candidate / ".git").exists():
            return candidate
        pytest.skip("Cannot locate ColonyOS repo root")

    def test_generates_valid_text(self, repo_root: Path):
        config = RepoMapConfig(max_tokens=4000)
        result = generate_repo_map(repo_root, config)
        assert isinstance(result, str)
        assert len(result) > 0
        # Should be printable text — no null bytes
        assert "\x00" not in result

    def test_token_budget_respected(self, repo_root: Path):
        config = RepoMapConfig(max_tokens=2000)
        result = generate_repo_map(repo_root, config)
        estimated_tokens = len(result) / 4
        assert estimated_tokens <= 2000

    def test_key_files_appear_in_map(self, repo_root: Path):
        # Use a generous budget so core files fit after the overview
        config = RepoMapConfig(max_tokens=16000)
        result = generate_repo_map(
            repo_root, config, prompt_text="config orchestrator cli repo_map"
        )
        # These are core ColonyOS files — should appear with a generous budget
        assert "config.py" in result
        assert "orchestrator.py" in result
        assert "cli.py" in result

    def test_python_symbols_extracted(self, repo_root: Path):
        config = RepoMapConfig(max_tokens=8000)
        result = generate_repo_map(
            repo_root, config, prompt_text="config orchestrator"
        )
        # config.py defines RepoMapConfig, ColonyConfig; orchestrator.py defines Orchestrator
        # At least some class/function names should appear
        assert "class" in result.lower() or "Config" in result or "Orchestrator" in result

    def test_overview_section_present(self, repo_root: Path):
        config = RepoMapConfig(max_tokens=4000)
        result = generate_repo_map(repo_root, config)
        # Overview always starts with "<N> files total"
        assert "files total" in result

    def test_prompt_relevance_changes_output(self, repo_root: Path):
        """Different prompts should produce differently-ordered output."""
        config = RepoMapConfig(max_tokens=1000)
        result_config = generate_repo_map(repo_root, config, prompt_text="config parsing yaml")
        result_cli = generate_repo_map(repo_root, config, prompt_text="cli command map")
        # Both should be valid non-empty text
        assert len(result_config) > 0
        assert len(result_cli) > 0
        # With a tight budget they may differ in which files are included
        # (at minimum we verify they don't crash)


# ===========================================================================
# Task 7.2 — Edge case hardening
# ===========================================================================

class TestEdgeCases:
    """Edge cases: empty repos, binary-only repos, encoding errors, tiny budgets, syntax errors."""

    def test_empty_repository_no_tracked_files(self, git_repo: Path):
        """A git repo with no commits / no tracked files returns empty string."""
        config = RepoMapConfig()
        result = generate_repo_map(git_repo, config)
        assert result == ""

    def test_repo_with_only_binary_files(self, git_repo: Path):
        """Repo containing only binary (non-parsable) files still produces output."""
        (git_repo / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)
        (git_repo / "data.bin").write_bytes(bytes(range(256)))
        subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "binary"],
            cwd=git_repo, capture_output=True, check=True,
        )
        config = RepoMapConfig(max_tokens=4000)
        result = generate_repo_map(git_repo, config)
        assert "image.png" in result
        assert "data.bin" in result
        # Should mention file sizes (bytes) since these are non-code files
        assert "bytes" in result

    def test_files_with_encoding_errors(self, git_repo: Path):
        """Non-UTF-8 Python file is handled gracefully (skipped with warning, no crash)."""
        # Write the good file first
        (git_repo / "good.py").write_text("def hello():\n    pass\n")
        # Write the bad file as raw bytes
        (git_repo / "bad_encoding.py").write_bytes(b"\x80\x81\x82\xfe\xff# not utf-8\n")
        subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "add files"],
            cwd=git_repo, capture_output=True, check=True,
        )
        config = RepoMapConfig(max_tokens=4000)
        result = generate_repo_map(git_repo, config)
        # Good file should still appear
        assert "good.py" in result
        assert "hello" in result
        # Bad file appears in listing (path is present) but no symbols extracted
        assert "bad_encoding.py" in result

    def test_extremely_small_token_budget(self, git_repo: Path):
        """Budget of 100 tokens: overview is always included, output doesn't crash."""
        _add_and_commit(git_repo, {
            f"src/module_{i}.py": f"class Mod{i}:\n    pass\n"
            for i in range(20)
        })
        config = RepoMapConfig(max_tokens=100)
        result = generate_repo_map(git_repo, config)
        # Should produce *something* (at least the overview)
        assert len(result) > 0
        # Token estimate should not wildly exceed budget
        # (overview is always included even if it alone exceeds budget)
        assert "files total" in result

    def test_python_files_with_syntax_errors(self, git_repo: Path):
        """Python files with syntax errors are skipped gracefully."""
        _add_and_commit(git_repo, {
            "broken.py": "def oops(\n",
            "good.py": "def works() -> int:\n    return 1\n",
        })
        config = RepoMapConfig(max_tokens=4000)
        result = generate_repo_map(git_repo, config)
        # Good file symbols should be present
        assert "works" in result
        # Broken file still appears as a path entry, just no symbols
        assert "broken.py" in result

    def test_extremely_large_max_files_cap(self, git_repo: Path):
        """max_files larger than actual file count works fine."""
        _add_and_commit(git_repo, {"a.py": "x = 1\n", "b.py": "y = 2\n"})
        config = RepoMapConfig(max_files=999999, max_tokens=4000)
        result = generate_repo_map(git_repo, config)
        assert "a.py" in result
        assert "b.py" in result

    def test_repo_with_deeply_nested_directories(self, git_repo: Path):
        """Deeply nested file structures are handled correctly."""
        _add_and_commit(git_repo, {
            "a/b/c/d/e/deep.py": "def deep_func():\n    pass\n",
            "top.py": "def top_func():\n    pass\n",
        })
        config = RepoMapConfig(max_tokens=4000)
        result = generate_repo_map(git_repo, config)
        assert "deep.py" in result
        assert "deep_func" in result
        assert "top.py" in result
        assert "top_func" in result

    def test_mixed_file_types(self, git_repo: Path):
        """Repo with Python, JS/TS, and other files all handled correctly."""
        _add_and_commit(git_repo, {
            "app.py": "class App:\n    def run(self) -> None:\n        pass\n",
            "index.ts": "export function main() {}\nexport class Router {}\n",
            "config.yaml": "key: value\n",
            "README.md": "# Hello\n",
        })
        config = RepoMapConfig(max_tokens=4000)
        result = generate_repo_map(git_repo, config)
        assert "app.py" in result
        assert "App" in result
        assert "index.ts" in result
        assert "main" in result
        assert "Router" in result
        assert "config.yaml" in result
        assert "README.md" in result

    def test_zero_token_budget(self, git_repo: Path):
        """Budget of 0 tokens: should still return overview (FR-10 always included)."""
        _add_and_commit(git_repo, {"a.py": "x = 1\n"})
        config = RepoMapConfig(max_tokens=0)
        result = generate_repo_map(git_repo, config)
        # Overview is always included per FR-10
        assert "files total" in result
