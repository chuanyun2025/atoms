"""Published, immutable snapshots, independent of visitors and projects."""

import json
from functools import lru_cache

from atoms import SHARED_ROOT
from atoms.core.security import error

GAME_EXAMPLES = frozenset({"jungle-assault", "meadow-journey", "neon-coast", "warehouse-breakout"})
WEBSITE_EXAMPLES = frozenset({"jinheng-finance", "independent-studio", "shiguang-amber"})
SLIDE_EXAMPLES = frozenset({"shenzhen-travel", "annual-review", "customer-q2-review"})
EXAMPLES = GAME_EXAMPLES | WEBSITE_EXAMPLES | SLIDE_EXAMPLES
ROOT = SHARED_ROOT


@lru_cache(maxsize=len(EXAMPLES))
def _load_example(example_id: str) -> dict:
    if example_id not in EXAMPLES:
        error(404, "example_not_found", "作品示例不存在")
    directory = "game-examples" if example_id in GAME_EXAMPLES else "published-examples"
    return json.loads((ROOT / directory / (example_id + ".json")).read_text("utf-8"))


def compiled_example(example_id: str):
    return _load_example(example_id)["compiled"]


@lru_cache(maxsize=len(EXAMPLES))
def example_source(example_id: str) -> dict:
    loaded = _load_example(example_id)
    artifact = loaded.get("artifact") or {}
    raw_files = artifact.get("files") if isinstance(artifact.get("files"), dict) else {}
    files = {
        str(path): str(content)
        for path, content in raw_files.items()
        if isinstance(path, str) and isinstance(content, str)
    }
    return {
        "example_id": example_id,
        "schema_version": str(artifact.get("schema_version") or "2"),
        "title": str(artifact.get("title") or example_id),
        "summary": str(artifact.get("summary") or ""),
        "files": files,
        "build_story": loaded.get("build_story") if isinstance(loaded.get("build_story"), dict) else None,
    }
