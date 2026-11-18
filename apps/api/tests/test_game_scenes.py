from json import loads

import pytest

from atoms.core.db import compact
from atoms.domains.game_design import DESIGN_FILE, validate_game_design
from atoms.domains.game_scenes import check_scene, scene_direction, scene_geometry
from atoms.runtime.orchestration import game_reference


@pytest.mark.parametrize(
    "genre,reference,path,changes",
    [
        ("racing", "track-racing", "src/game/track.ts", [("[29, 91]", "[12, 105]"), ("[82, 106]", "[52, 90]")]),
        (
            "fps",
            "first-person",
            "src/game/fps.ts",
            [("this.addBox(-6, 1.2, 0", "this.addBox(-7, 1.2, 4"), ("this.addBox(6, 1.3, -2", "this.addBox(7, 1.3, 5")],
        ),
    ],
)
def test_new_game_rejects_cosmetic_map_changes_and_recent_geometry(genre, reference, path, changes):
    original = game_reference(reference)["files"]
    cosmetic = {**original, path: original[path] + "\n// new setting", "src/styles.css": "body{background:orange}"}
    with pytest.raises(ValueError, match="地图几何"):
        check_scene(cosmetic, original, genre, [])
    adapted = dict(original)
    for old, new in changes:
        adapted[path] = adapted[path].replace(old, new)
    check_scene(adapted, original, genre, [])
    with pytest.raises(ValueError, match="地图几何"):
        check_scene(adapted, original, genre, [scene_geometry(adapted, genre)])
    first = scene_direction("project-a", genre, [])
    assert first and scene_direction("project-a", genre, [first]) != first


def test_game_can_declare_a_held_screen_control():
    files = dict(game_reference("track-racing")["files"])
    design = loads(files[DESIGN_FILE])
    design["playtest"]["checks"] = [
        {"label": "按住右侧按钮", "control": "right", "signal": "screen-x", "change": "increase"},
        {"label": "按住左键", "key": "ArrowLeft", "hold_ms": 300, "signal": "screen-x", "change": "decrease"},
        {"label": "使用补给", "control": "use", "hold_ms": 300, "signal": "energy", "change": "decrease"},
    ]
    files[DESIGN_FILE] = compact(design)
    first, second, third = validate_game_design(files).playtest.checks
    assert (first.hold_ms, first.fresh_start) == (320, True)
    assert (second.hold_ms, second.fresh_start) == (300, True)
    assert (third.hold_ms, third.fresh_start) == (300, False)
