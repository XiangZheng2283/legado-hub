"""Load Legado source JSON files into raw dicts.

Supports both single-object files and multi-object list files.
Each object becomes an independent source record.
"""

import json
from pathlib import Path


def load_source_file(path: Path) -> list[dict]:
    """Load a Legado source JSON file and return a list of source objects.

    Returns a list even for single-object files for uniform handling.
    """
    text = path.read_text(encoding="utf-8-sig")
    data = json.loads(text)
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    raise ValueError(f"Unexpected source format in {path}: {type(data).__name__}")


def get_required_fields() -> list[str]:
    return [
        "bookSourceName",
        "bookSourceUrl",
        "searchUrl",
        "ruleSearch",
        "ruleBookInfo",
        "ruleToc",
        "ruleContent",
    ]


def has_required_fields(source: dict) -> bool:
    return all(field in source for field in get_required_fields())


def make_source_id(file_stem: str, index: int, source_name: str = "", is_multi: bool = False) -> str:
    """Create a stable, collision-safe source ID.

    For single-object files: <site-slug>
    For multi-object files: <site-slug>#<index> or <site-slug>#<name-slug>
    """
    if not is_multi and index == 0:
        return file_stem
    if source_name:
        name_slug = _slugify(source_name)
        return f"{file_stem}#{name_slug}"
    return f"{file_stem}#{index}"


def _slugify(name: str) -> str:
    """Convert a source name to a URL-safe slug."""
    import re
    slug = re.sub(r"[^\w\u4e00-\u9fff-]", "-", name)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:40] or "source"
