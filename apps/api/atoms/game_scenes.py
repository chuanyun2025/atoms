"""Give new games scene direction without replacing the player's creative brief."""

import re
from hashlib import sha256


_DIRECTIONS = {
    "fps": (
        "高山缆车站，玻璃候车区和弧形站台，冷日光与红色导向牌",
        "沙岩水利遗址，错位石柱和双向水渠，暖日光与青铜反光",
        "海上风电维护站，环形甲板和设备廊，雨幕与琥珀色工作灯",
        "失重温室，交错花坛和中央储水塔，绿色植被与紫色天光",
        "冰原科研站，狭长观测廊和侧向补给区，冰蓝反光与橙色设备",
        "夜间货运码头，斜向装卸通道和分岔堆场，青白探照灯与湿地反射",
    ),
    "racing": (
        "红岩峡谷，贴崖长直道接紧凑发卡弯，石拱和路肩碎岩",
        "极地补给公路，宽缓冰川弯接连续折返，冰塔和灯标",
        "雨夜高架，城区连续 S 弯接开阔直道，高架桥和发光导向线",
        "火山台地，长弧外圈接急收窄内圈，玄武岩柱和发光岩缝",
        "高山风场，双回头弯接快速下坡感的开阔段，风机和草坡",
        "湖畔公路，缓弯接错位窄弯，林带和短桥",
    ),
}


def scene_direction(project_id: str, genre: str | None, recent: list[str]) -> str | None:
    choices=_DIRECTIONS.get(genre)
    if not choices:
        return None
    index=int.from_bytes(sha256(project_id.encode()).digest()[:4],"big") % len(choices)
    ordered=choices[index:]+choices[:index]
    return next((choice for choice in ordered if choice not in recent),
                next(choice for choice in ordered if choice not in recent[:1]))


_PAIR=re.compile(r"\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]")
_BOX=re.compile(r"\.addBox\(\s*((?:-?\d+(?:\.\d+)?\s*,\s*){6})")


def scene_geometry(files: dict, genre: str) -> tuple:
    """Compare the actual level geometry in source that uses the reference API."""
    if genre=="racing":
        points=re.search(r"\bpoints\s*:\s*\[((?:\s*\[[^\]]+\]\s*,?)+)\]",files.get("src/game/track.ts", ""))
        if not points:
            return ()
        pairs=[tuple(map(float,pair)) for pair in _PAIR.findall(points[1])]
        if len(pairs)<4:
            return ()
        x,z=pairs[0]
        return tuple((px-x,pz-z) for px,pz in pairs)
    source=files.get("src/game/fps.ts", "")
    arena=source.partition("private buildArena()")[2].partition("private buildGun()")[0]
    boxes=[tuple(map(float,match.rsplit(",",1)[0].split(","))) for match in _BOX.findall(arena)]
    return tuple(sorted(box for box in boxes if max(box[3],box[5])<15))


def _same_layout(current: tuple, other: tuple, genre: str) -> bool:
    if not current or len(current)!=len(other):
        return False
    if genre=="racing":
        changed=sum((ax-bx)**2+(az-bz)**2>=8**2 for (ax,az),(bx,bz) in zip(current,other))
        return changed<2
    return len(set(current)-set(other))<2


def check_scene(files: dict, reference: dict, genre: str, previous: list[tuple]):
    geometry=scene_geometry(files,genre)
    if any(_same_layout(geometry,other,genre) for other in [scene_geometry(reference,genre),*previous]):
        change="更换赛道中心线、弯道结构和沿途地标" if genre=="racing" else "重排关卡路线、掩体位置和环境地标"
        raise ValueError(f"新游戏沿用了参考或近期项目的地图几何。请{change}，保留真实操作和核心玩法")
