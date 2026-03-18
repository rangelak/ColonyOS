"""ColonyOS — autonomous agent loop that turns prompts into shipped PRs."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__: str = version("colonyos")
except PackageNotFoundError:
    # Fallback for editable installs or running from source without metadata
    __version__ = "0.0.0.dev0"
