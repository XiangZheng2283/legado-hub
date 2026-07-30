from pathlib import Path

import pytest

from scripts.validate_source_plugin import _load_metadata


def test_metadata_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    metadata = tmp_path / "metadata.yaml"
    metadata.write_text('id: example\nenabled: true\nenabled: false\n', encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate YAML key: enabled"):
        _load_metadata(metadata)
