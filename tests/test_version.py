"""Tests for single-source versioning via setuptools-scm."""

import re

import colonyos


class TestVersionConsistency:
    """Verify __version__ is valid and accessible."""

    def test_version_attribute_exists(self):
        """colonyos.__version__ must be defined."""
        assert hasattr(colonyos, "__version__")

    def test_version_is_string(self):
        """__version__ must be a string."""
        assert isinstance(colonyos.__version__, str)

    def test_version_not_empty(self):
        """__version__ must not be empty."""
        assert colonyos.__version__ != ""

    def test_version_is_valid_semver_prefix(self):
        """__version__ must start with a valid major.minor.patch pattern."""
        pattern = r"^\d+\.\d+\.\d+"
        assert re.match(pattern, colonyos.__version__), (
            f"Version '{colonyos.__version__}' does not match semver pattern"
        )

    def test_version_matches_importlib_metadata(self):
        """__version__ must match importlib.metadata if package is installed."""
        from importlib.metadata import PackageNotFoundError, version

        try:
            meta_version = version("colonyos")
            assert colonyos.__version__ == meta_version, (
                f"__version__={colonyos.__version__!r} != "
                f"metadata={meta_version!r}"
            )
        except PackageNotFoundError:
            # In editable installs without metadata, skip this check
            pass
