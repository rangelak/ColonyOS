"""Repo map module: generates a condensed structural summary of the target repository.

The repo map gives every pipeline phase a "table of contents" of the codebase —
file paths, class names, function signatures — so the agent can orient itself
without spending tool calls on initial exploration.
"""

from __future__ import annotations

import ast
import logging
import os
import re
import subprocess
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

from colonyos.config import RepoMapConfig

logger = logging.getLogger(__name__)

# Maximum file size (in bytes) to read for symbol extraction.  Files larger
# than this threshold are recorded with size metadata only — no AST/regex
# parsing — to avoid OOM on generated or vendored megafiles.
_MAX_PARSE_SIZE: int = 1_000_000  # 1 MB

# Hardcoded sensitive file patterns that are always excluded (FR-6).
SENSITIVE_PATTERNS: tuple[str, ...] = (
    ".env",
    ".env.*",
    ".env*",
    "*credential*",
    "*secret*",
    "*.pem",
    "*.key",
)


@dataclass
class Symbol:
    """A single extracted symbol (class, function, or method)."""

    name: str
    kind: str  # "class", "function", or "method"
    params: str = ""
    bases: list[str] = field(default_factory=list)
    children: list[Symbol] = field(default_factory=list)


@dataclass
class FileSymbols:
    """Extracted symbols for a single file."""

    path: str
    symbols: list[Symbol] = field(default_factory=list)
    line_count: int = 0
    size_bytes: int = 0
    docstring: str = ""


@dataclass
class RepoMap:
    """Complete repo map result."""

    files: list[FileSymbols] = field(default_factory=list)
    overview: str = ""


def _matches_any(filename: str, patterns: tuple[str, ...] | list[str]) -> bool:
    """Check if a filename matches any of the given glob patterns."""
    name = Path(filename).name
    for pattern in patterns:
        if fnmatch(name, pattern) or fnmatch(filename, pattern):
            return True
    return False


def _git_clean_env() -> dict[str, str]:
    """Return a git subprocess environment with repo-shaping vars removed."""
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


def get_tracked_files(repo_root: Path, config: RepoMapConfig) -> list[str]:
    """Return a list of tracked files from ``git ls-files``.

    Applies sensitive-file filtering, include/exclude patterns from config,
    and caps the result at ``config.max_files``.

    Parameters
    ----------
    repo_root:
        Root directory of the git repository.
    config:
        Repo map configuration with pattern and limit settings.

    Returns
    -------
    list[str]
        Relative file paths from the repository root.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files"],
            capture_output=True,
            text=True,
            env=_git_clean_env(),
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        logger.warning("git ls-files timed out after 30s")
        return []
    except OSError as exc:
        logger.warning("Failed to run git ls-files: %s", exc)
        return []

    if result.returncode != 0:
        logger.warning("git ls-files failed: %s", result.stderr.strip())
        return []

    raw_files = [f for f in result.stdout.splitlines() if f.strip()]

    # Filter out sensitive files (FR-6)
    files = [f for f in raw_files if not _matches_any(f, SENSITIVE_PATTERNS)]

    # Apply include patterns — if non-empty, only keep matching files
    if config.include_patterns:
        files = [f for f in files if _matches_any(f, config.include_patterns)]

    # Apply exclude patterns
    if config.exclude_patterns:
        files = [f for f in files if not _matches_any(f, config.exclude_patterns)]

    # Cap at max_files (FR-11)
    if config.max_files is not None and len(files) > config.max_files:
        logger.warning(
            "Repository has %d tracked files, capping at %d. "
            "Consider adjusting repo_map.max_files or repo_map.include_patterns.",
            len(files),
            config.max_files,
        )
        files = files[: config.max_files]

    return files


def extract_python_symbols(file_path: Path) -> FileSymbols:
    """Extract symbols from a Python file using ``ast.parse()``.

    Extracts module-level docstrings (first line), class names with base classes,
    method signatures within classes, and top-level function signatures.

    Handles ``SyntaxError`` and encoding errors gracefully by returning an
    empty result with a warning log.

    Parameters
    ----------
    file_path:
        Absolute or relative path to the ``.py`` file.

    Returns
    -------
    FileSymbols
        Extracted symbols for the file.
    """
    result = FileSymbols(path=str(file_path))

    # Guard against pathologically large files (e.g., generated code).
    try:
        file_size = file_path.stat().st_size
    except OSError:
        file_size = 0
    if file_size > _MAX_PARSE_SIZE:
        logger.info("Skipping parse of %s (%d bytes > %d limit)", file_path, file_size, _MAX_PARSE_SIZE)
        result.size_bytes = file_size
        return result

    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("Could not read %s: %s", file_path, exc)
        return result

    result.line_count = len(source.splitlines())
    result.size_bytes = len(source.encode("utf-8"))

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as exc:
        logger.warning("Syntax error in %s: %s", file_path, exc)
        return result

    # Module-level docstring (first line only)
    docstring = ast.get_docstring(tree)
    if docstring:
        result.docstring = docstring.split("\n")[0].strip()

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            class_symbol = _extract_class(node)
            result.symbols.append(class_symbol)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            func_symbol = _extract_function(node, kind="function")
            result.symbols.append(func_symbol)

    return result


def _extract_class(node: ast.ClassDef) -> Symbol:
    """Extract a class definition including its methods."""
    bases = []
    for base in node.bases:
        bases.append(_format_expr(base))

    class_symbol = Symbol(
        name=node.name,
        kind="class",
        bases=bases,
    )

    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            method = _extract_function(child, kind="method")
            class_symbol.children.append(method)

    return class_symbol


def _extract_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef, kind: str
) -> Symbol:
    """Extract a function or method signature."""
    params = _format_args(node.args)
    return_annotation = ""
    if node.returns:
        return_annotation = f" -> {_format_expr(node.returns)}"

    return Symbol(
        name=node.name,
        kind=kind,
        params=f"({params}){return_annotation}",
    )


def _format_args(args: ast.arguments) -> str:
    """Format function arguments to a signature string."""
    parts: list[str] = []

    # Regular args (skip 'self'/'cls' for readability in methods)
    for arg in args.args:
        name = arg.arg
        if name in ("self", "cls"):
            continue
        annotation = f": {_format_expr(arg.annotation)}" if arg.annotation else ""
        parts.append(f"{name}{annotation}")

    # *args
    if args.vararg:
        name = args.vararg.arg
        annotation = (
            f": {_format_expr(args.vararg.annotation)}"
            if args.vararg.annotation
            else ""
        )
        parts.append(f"*{name}{annotation}")

    # **kwargs
    if args.kwarg:
        name = args.kwarg.arg
        annotation = (
            f": {_format_expr(args.kwarg.annotation)}"
            if args.kwarg.annotation
            else ""
        )
        parts.append(f"**{name}{annotation}")

    return ", ".join(parts)


def _format_expr(node: ast.expr | None) -> str:
    """Best-effort formatting of an AST expression to source text."""
    if node is None:
        return ""
    # Python 3.8+ has ast.unparse
    try:
        return ast.unparse(node)
    except Exception:
        # Fallback for very unusual AST nodes
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{_format_expr(node.value)}.{node.attr}"
        if isinstance(node, ast.Constant):
            return repr(node.value)
        return "..."


# ---------------------------------------------------------------------------
# JS/TS regex patterns for top-level export extraction (FR-3)
# ---------------------------------------------------------------------------

# export function foo(...) / export async function foo(...)
_RE_EXPORT_FUNCTION = re.compile(
    r"^export\s+(?:default\s+)?(?:async\s+)?function\s+(\w+)", re.MULTILINE
)
# export class Foo
_RE_EXPORT_CLASS = re.compile(
    r"^export\s+(?:default\s+)?class\s+(\w+)", re.MULTILINE
)
# export const/let/var NAME
_RE_EXPORT_VARIABLE = re.compile(
    r"^export\s+(?:const|let|var)\s+(\w+)", re.MULTILINE
)
# export { foo, bar, baz }
_RE_EXPORT_NAMED = re.compile(
    r"^export\s+\{([^}]+)\}", re.MULTILINE
)
# export interface Foo (TypeScript)
_RE_EXPORT_INTERFACE = re.compile(
    r"^export\s+interface\s+(\w+)", re.MULTILINE
)
# export type Foo (TypeScript)
_RE_EXPORT_TYPE = re.compile(
    r"^export\s+type\s+(\w+)", re.MULTILINE
)

# File extensions recognized as JS/TS
JS_TS_EXTENSIONS: frozenset[str] = frozenset({".js", ".jsx", ".ts", ".tsx"})


def extract_js_ts_symbols(file_path: Path) -> FileSymbols:
    """Extract exported symbols from a JavaScript/TypeScript file using regex.

    Extracts top-level ``export`` declarations: functions, classes, variables,
    named exports, interfaces, and types. Does not parse nested class methods.

    Parameters
    ----------
    file_path:
        Path to the ``.js``, ``.jsx``, ``.ts``, or ``.tsx`` file.

    Returns
    -------
    FileSymbols
        Extracted symbols for the file.
    """
    result = FileSymbols(path=str(file_path))

    # Guard against pathologically large files (e.g., vendored bundles).
    try:
        file_size = file_path.stat().st_size
    except OSError:
        file_size = 0
    if file_size > _MAX_PARSE_SIZE:
        logger.info("Skipping parse of %s (%d bytes > %d limit)", file_path, file_size, _MAX_PARSE_SIZE)
        result.size_bytes = file_size
        return result

    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("Could not read %s: %s", file_path, exc)
        return result

    result.line_count = len(source.splitlines())
    result.size_bytes = len(source.encode("utf-8"))

    seen: set[str] = set()

    def _add(name: str, kind: str) -> None:
        if name not in seen:
            seen.add(name)
            result.symbols.append(Symbol(name=name, kind=kind))

    # Functions (including async and default)
    for m in _RE_EXPORT_FUNCTION.finditer(source):
        _add(m.group(1), "function")

    # Classes
    for m in _RE_EXPORT_CLASS.finditer(source):
        _add(m.group(1), "class")

    # Variables (const/let/var)
    for m in _RE_EXPORT_VARIABLE.finditer(source):
        _add(m.group(1), "variable")

    # Named exports: export { foo, bar }
    for m in _RE_EXPORT_NAMED.finditer(source):
        for name in m.group(1).split(","):
            name = name.strip().split(" as ")[0].strip()
            if name:
                _add(name, "export")

    # TypeScript interfaces
    for m in _RE_EXPORT_INTERFACE.finditer(source):
        _add(m.group(1), "interface")

    # TypeScript types
    for m in _RE_EXPORT_TYPE.finditer(source):
        _add(m.group(1), "type")

    return result


def extract_other_file_info(file_path: Path) -> FileSymbols:
    """Extract basic file info (path + size) for non-code files (FR-4).

    Parameters
    ----------
    file_path:
        Path to any file that is not Python or JS/TS.

    Returns
    -------
    FileSymbols
        Contains path and size_bytes; symbols list is empty.
    """
    result = FileSymbols(path=str(file_path))

    try:
        result.size_bytes = file_path.stat().st_size
    except OSError as exc:
        logger.warning("Could not stat %s: %s", file_path, exc)

    return result


def extract_file_symbols(file_path: Path) -> FileSymbols:
    """Dispatch to the appropriate extractor based on file extension.

    Routes ``.py`` files to :func:`extract_python_symbols`,
    ``.js/.jsx/.ts/.tsx`` files to :func:`extract_js_ts_symbols`,
    and everything else to :func:`extract_other_file_info`.

    Parameters
    ----------
    file_path:
        Path to the file to extract symbols from.

    Returns
    -------
    FileSymbols
        Extracted symbols (or just path + size for unknown file types).
    """
    suffix = file_path.suffix.lower()

    if suffix == ".py":
        return extract_python_symbols(file_path)
    elif suffix in JS_TS_EXTENSIONS:
        return extract_js_ts_symbols(file_path)
    else:
        return extract_other_file_info(file_path)


# ---------------------------------------------------------------------------
# Tree formatting (FR-5, Task 4.4)
# ---------------------------------------------------------------------------


def format_tree(files: list[FileSymbols]) -> str:
    """Format file symbols as an indented directory tree.

    Groups files by directory, shows line counts for code files and byte sizes
    for other files. Symbols are indented under their parent file/class.

    Parameters
    ----------
    files:
        List of extracted file symbols, already in desired order.

    Returns
    -------
    str
        Tree-formatted text.
    """
    if not files:
        return ""

    # Group files by their parent directory
    dir_groups: OrderedDict[str, list[FileSymbols]] = OrderedDict()
    for fs in files:
        parts = fs.path.rsplit("/", 1)
        directory = parts[0] + "/" if len(parts) > 1 else ""
        dir_groups.setdefault(directory, []).append(fs)

    lines: list[str] = []
    for directory, dir_files in dir_groups.items():
        if directory:
            lines.append(directory)
        for fs in dir_files:
            basename = fs.path.rsplit("/", 1)[-1]
            if fs.line_count > 0:
                file_label = f"{basename} ({fs.line_count} lines)"
            elif fs.size_bytes > 0:
                file_label = f"{basename} ({fs.size_bytes} bytes)"
            else:
                file_label = basename
            indent = "  " if directory else ""
            lines.append(f"{indent}{file_label}")
            _format_symbols(fs.symbols, indent + "  ", lines)

    return "\n".join(lines) + "\n"


def _format_symbols(symbols: list[Symbol], indent: str, lines: list[str]) -> None:
    """Recursively format symbols with indentation."""
    for sym in symbols:
        if sym.kind == "class":
            bases = f"({', '.join(sym.bases)})" if sym.bases else ""
            lines.append(f"{indent}class {sym.name}{bases}")
            _format_symbols(sym.children, indent + "  ", lines)
        elif sym.kind == "function":
            lines.append(f"{indent}{sym.name}{sym.params}")
        elif sym.kind == "method":
            lines.append(f"{indent}{sym.name}{sym.params}")
        else:
            # variable, export, interface, type
            lines.append(f"{indent}{sym.kind} {sym.name}")


# ---------------------------------------------------------------------------
# Relevance ranking (FR-8, FR-9, Task 4.5)
# ---------------------------------------------------------------------------


def rank_by_relevance(
    files: list[FileSymbols], prompt_text: str
) -> list[FileSymbols]:
    """Rank files by relevance to the given prompt text.

    Scoring uses keyword overlap: words >= 3 chars extracted from the prompt
    are matched against file paths and symbol names (case-insensitive).
    Files with exact path or basename matches in the prompt get maximum score.

    Parameters
    ----------
    files:
        Files to rank.
    prompt_text:
        Current task/prompt text used for keyword extraction.

    Returns
    -------
    list[FileSymbols]
        Files sorted by relevance (highest first). Original list is not mutated.
    """
    if not files:
        return []
    if not prompt_text.strip():
        return list(files)

    prompt_lower = prompt_text.lower()
    keywords = {w.lower() for w in prompt_text.split() if len(w) >= 3}

    def _score(fs: FileSymbols) -> float:
        score = 0.0
        path_lower = fs.path.lower()
        basename = fs.path.rsplit("/", 1)[-1].lower()

        # Exact path match in prompt → maximum score (FR-9)
        if path_lower in prompt_lower:
            score += 1000.0
        # Basename match in prompt (FR-9)
        if basename in prompt_lower:
            score += 500.0

        # Keyword overlap with path components
        path_parts = set(path_lower.replace("/", " ").replace(".", " ").replace("_", " ").split())
        path_overlap = len(keywords & path_parts)
        score += path_overlap * 10.0

        # Keyword overlap with symbol names
        symbol_words: set[str] = set()
        for sym in fs.symbols:
            for w in sym.name.lower().replace("_", " ").split():
                if len(w) >= 3:
                    symbol_words.add(w)
            for child in sym.children:
                for w in child.name.lower().replace("_", " ").split():
                    if len(w) >= 3:
                        symbol_words.add(w)
        sym_overlap = len(keywords & symbol_words)
        score += sym_overlap * 5.0

        return score

    scored = [(f, _score(f)) for f in files]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [f for f, _ in scored]


# ---------------------------------------------------------------------------
# Overview generation (FR-10, Task 4.6)
# ---------------------------------------------------------------------------


def generate_overview(files: list[FileSymbols]) -> str:
    """Generate a compact directory tree with file counts.

    Produces a lightweight overview (~500 tokens) showing the top-level
    directory structure and how many files each contains.

    Parameters
    ----------
    files:
        All files in the repo map.

    Returns
    -------
    str
        Compact directory overview text.
    """
    if not files:
        return ""

    dir_counts: Counter[str] = Counter()
    root_count = 0
    for fs in files:
        parts = fs.path.rsplit("/", 1)
        if len(parts) > 1:
            # Use the top-level directory
            top_dir = fs.path.split("/")[0]
            dir_counts[top_dir] += 1
        else:
            root_count += 1

    lines = [f"{len(files)} files total"]
    if root_count:
        lines.append(f"  ./ ({root_count} files)")
    for dirname, count in sorted(dir_counts.items()):
        lines.append(f"  {dirname}/ ({count} files)")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Token-budget truncation (FR-7, Task 4.7)
# ---------------------------------------------------------------------------


def truncate_to_budget(
    overview: str,
    ranked_files: list[FileSymbols],
    max_tokens: int,
) -> str:
    """Assemble final map text within a token budget.

    The overview is always included first (FR-10). Files are added greedily
    in ranked order until the chars/4 token estimate would exceed *max_tokens*.

    Parameters
    ----------
    overview:
        Compact directory overview (always included).
    ranked_files:
        Files sorted by relevance (most relevant first).
    max_tokens:
        Maximum token budget (estimated as chars / 4).

    Returns
    -------
    str
        Final repo map text within budget.
    """
    if not overview and not ranked_files:
        return ""

    max_chars = max_tokens * 4

    # Overview is always included (FR-10)
    parts: list[str] = []
    if overview:
        parts.append(overview)

    current_chars = sum(len(p) for p in parts)

    # Greedily add files until budget exhausted
    included_files: list[FileSymbols] = []
    for fs in ranked_files:
        file_block = format_tree([fs])
        block_chars = len(file_block)
        if current_chars + block_chars <= max_chars:
            included_files.append(fs)
            parts.append(file_block)
            current_chars += block_chars
        else:
            # If this is the first file and we haven't added any, try to fit it
            # to avoid returning only the overview
            break

    return "".join(parts)


# ---------------------------------------------------------------------------
# Top-level generator (Task 4.8)
# ---------------------------------------------------------------------------


def generate_repo_map(
    repo_root: Path,
    config: RepoMapConfig,
    prompt_text: str = "",
) -> str:
    """Generate a complete repo map for the given repository.

    Orchestrates the full pipeline: file walking → symbol extraction →
    relevance ranking → truncation to budget.

    Parameters
    ----------
    repo_root:
        Root directory of the git repository.
    config:
        Repo map configuration.
    prompt_text:
        Optional prompt/task text for relevance-based ranking.

    Returns
    -------
    str
        Formatted repo map text within the configured token budget.
    """
    tracked = get_tracked_files(repo_root, config)
    if not tracked:
        return ""

    # Extract symbols for each file
    all_files: list[FileSymbols] = []
    for rel_path in tracked:
        abs_path = repo_root / rel_path
        fs = extract_file_symbols(abs_path)
        # Ensure path is stored as relative
        fs.path = rel_path
        all_files.append(fs)

    # Generate overview
    overview = generate_overview(all_files)

    # Rank by relevance to prompt
    ranked = rank_by_relevance(all_files, prompt_text)

    # Truncate to budget
    return truncate_to_budget(overview, ranked, config.max_tokens)
