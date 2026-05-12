"""Unit tests for the reveille.init scaffolding module.

Tests cover: successful write, content contract, idempotent overwrite
via --force, conflict guard when force=False, and missing parent directory.
"""

from __future__ import annotations

import pytest

from reveille.exceptions import ConfigurationError, OutputPathError
from reveille.init import _DEFAULT_CONFIG_TEMPLATE, write_init_config


class TestWriteInitConfig:
    """Tests for write_init_config."""

    def test_creates_file_at_output_path(self, tmp_path):
        """The function writes a file to the specified path."""
        dest = tmp_path / "reveille.toml"
        result = write_init_config(dest)
        assert dest.exists()
        assert result == dest.resolve()

    def test_returns_resolved_absolute_path(self, tmp_path):
        """The returned path is absolute regardless of the input form."""
        dest = tmp_path / "reveille.toml"
        result = write_init_config(dest)
        assert result.is_absolute()

    def test_written_content_matches_template(self, tmp_path):
        """The file content is byte-for-byte the default template."""
        dest = tmp_path / "reveille.toml"
        write_init_config(dest)
        assert dest.read_text(encoding="utf-8") == _DEFAULT_CONFIG_TEMPLATE

    def test_content_contains_all_section_headers(self, tmp_path):
        """The template contains all three TOML section headers."""
        dest = tmp_path / "reveille.toml"
        write_init_config(dest)
        content = dest.read_text(encoding="utf-8")
        assert "[report]" in content
        assert "[filters]" in content
        assert "[ranking]" in content

    def test_content_contains_all_expected_keys(self, tmp_path):
        """Each documented configuration key appears in the template."""
        dest = tmp_path / "reveille.toml"
        write_init_config(dest)
        content = dest.read_text(encoding="utf-8")
        expected_keys = [
            "title",
            "output",
            "branch",
            "since",
            "until",
            "min_commits",
            "exclude_authors",
            "enabled",
            "weights",
        ]
        for key in expected_keys:
            assert key in content, f"Expected key '{key}' not found in template"

    def test_all_keys_are_commented_out(self, tmp_path):
        """No active (uncommented) key assignments exist in the template.

        The template must not alter any tool behaviour when loaded as-is.
        Every key must be preceded by a comment marker.
        """
        dest = tmp_path / "reveille.toml"
        write_init_config(dest)
        for line in dest.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            # Skip blank lines, pure comment lines, and section headers.
            if not stripped or stripped.startswith("#") or stripped.startswith("["):
                continue
            pytest.fail(f"Unexpected active assignment in generated config: {line!r}")

    def test_raises_configuration_error_when_file_exists_without_force(self, tmp_path):
        """ConfigurationError is raised if the file exists and force=False."""
        dest = tmp_path / "reveille.toml"
        dest.write_text("existing content", encoding="utf-8")
        with pytest.raises(ConfigurationError, match="already exists"):
            write_init_config(dest, force=False)

    def test_does_not_modify_existing_file_on_conflict(self, tmp_path):
        """The existing file is left untouched when the conflict guard fires."""
        dest = tmp_path / "reveille.toml"
        original = "existing content"
        dest.write_text(original, encoding="utf-8")
        with pytest.raises(ConfigurationError):
            write_init_config(dest, force=False)
        assert dest.read_text(encoding="utf-8") == original

    def test_force_overwrites_existing_file(self, tmp_path):
        """force=True replaces the existing file with the default template."""
        dest = tmp_path / "reveille.toml"
        dest.write_text("stale content", encoding="utf-8")
        write_init_config(dest, force=True)
        assert dest.read_text(encoding="utf-8") == _DEFAULT_CONFIG_TEMPLATE

    def test_raises_output_path_error_when_parent_does_not_exist(self, tmp_path):
        """OutputPathError is raised if the parent directory is absent."""
        dest = tmp_path / "nonexistent_dir" / "reveille.toml"
        with pytest.raises(OutputPathError, match="does not exist"):
            write_init_config(dest)

    def test_custom_output_path(self, tmp_path):
        """The function honours a non-default output path."""
        dest = tmp_path / "custom_config.toml"
        result = write_init_config(dest)
        assert dest.exists()
        assert result == dest.resolve()

    def test_utf8_encoding(self, tmp_path):
        """The written file is valid UTF-8."""
        dest = tmp_path / "reveille.toml"
        write_init_config(dest)
        # read_text with explicit encoding raises on invalid UTF-8
        dest.read_text(encoding="utf-8")
