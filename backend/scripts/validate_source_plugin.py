"""Validate a LegadoHub source plugin directory."""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import yaml

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.source_plugins.models import PluginMetadata
from app.source_plugins.smoke import load_smoke_spec, _smoke_dir


FORBIDDEN_SOURCE_STRINGS = [
    "requests.",
    "httpx.",
    "threading",
    "asyncio.create_task",
    "engine-jvm",
    "app.legado_engine",
    "app.engine",
    "demo_",
]


def validate_plugin(plugin_dir: Path) -> list[str]:
    errors: list[str] = []
    metadata_path = plugin_dir / "metadata.yaml"
    source_path = plugin_dir / "source.py"
    readme_path = plugin_dir / "README.md"

    for path in (metadata_path, source_path, readme_path):
        if not path.exists():
            errors.append(f"missing required file: {path.name if path.parent == plugin_dir else path.relative_to(plugin_dir)}")
    if errors:
        return errors

    metadata_data = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
    if not isinstance(metadata_data, dict):
        errors.append("metadata.yaml must be a mapping")
        return errors
    metadata = PluginMetadata.from_dict(metadata_data)
    errors.extend(metadata.validate())
    if metadata.id != plugin_dir.name:
        errors.append(f"metadata id must match directory name: {plugin_dir.name}")
    if metadata.id.startswith("demo_"):
        errors.append("metadata id must not start with demo_")
    if not re.match(r"^[a-z0-9][a-z0-9_]*$", metadata.id):
        errors.append("metadata id must match ^[a-z0-9][a-z0-9_]*$")

    source_text = source_path.read_text(encoding="utf-8")
    for forbidden in FORBIDDEN_SOURCE_STRINGS:
        if forbidden in source_text:
            errors.append(f"source.py contains forbidden string: {forbidden}")

    source_obj = _load_source(source_path)
    source_id = getattr(source_obj, "id", "")
    if source_id != metadata.id:
        errors.append(f"Source.id must match metadata id: {metadata.id}")
    for cap in metadata.capabilities:
        method_name = cap if cap != "auth" else "auth_status"
        method = getattr(source_obj, method_name, None)
        if not callable(method):
            errors.append(f"Source missing method for capability: {cap}")

    try:
        smoke_dir = _smoke_dir(plugin_dir)
        smoke_path = smoke_dir / "smoke.yaml"
        if smoke_path.exists():
            spec = load_smoke_spec(plugin_dir)
            fixtures = spec.get("fixtures") or {}
            required_stages = ["detail", "toc", "chapter"]
            if "search" in metadata.capabilities:
                required_stages.insert(0, "search")
            for stage in required_stages:
                fixture = fixtures.get(stage)
                if not isinstance(fixture, dict):
                    errors.append(f"smoke fixture missing stage: {stage}")
                    continue
                if not fixture.get("url") or not fixture.get("file"):
                    errors.append(f"smoke fixture {stage} must include url and file")
                fixture_file = smoke_dir / "fixtures" / str(fixture.get("file", ""))
                if not fixture_file.exists():
                    errors.append(f"smoke fixture file missing: {fixture_file.relative_to(plugin_dir)}")
    except Exception as exc:
        errors.append(f"invalid smoke.yaml: {exc}")

    return errors


def _load_source(source_path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(f"validate_source_{source_path.parent.name}", source_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot import source.py: {source_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source_cls = getattr(module, "Source", None)
    if source_cls is None:
        raise ValueError("source.py must export Source")
    return source_cls()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a LegadoHub source plugin")
    parser.add_argument("--plugin", required=True)
    args = parser.parse_args()
    errors = validate_plugin(Path(args.plugin).resolve())
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
