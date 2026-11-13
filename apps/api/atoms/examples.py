"""Published, immutable snapshots, independent of visitors and projects."""

import json
from functools import lru_cache
from pathlib import Path

from .service import error

GAME_EXAMPLES = frozenset({"jungle-assault", "meadow-journey", "neon-coast", "warehouse-breakout"})
WEBSITE_EXAMPLES = frozenset({"jinheng-finance", "independent-studio", "shiguang-amber"})
SLIDE_EXAMPLES = frozenset({"shenzhen-travel", "annual-review", "customer-q2-review"})
EXAMPLES = GAME_EXAMPLES | WEBSITE_EXAMPLES | SLIDE_EXAMPLES
ROOT = Path(__file__).resolve().parents[3] / "shared"


@lru_cache(maxsize=len(EXAMPLES))
def compiled_example(example_id: str):
    if example_id not in EXAMPLES:
        error(404, "example_not_found", "作品示例不存在")
    directory = "game-examples" if example_id in GAME_EXAMPLES else "published-examples"
    return json.loads((ROOT / directory / (example_id + ".json")).read_text("utf-8"))["compiled"]
