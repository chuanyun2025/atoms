"""Generation skills shipped with the application and selected by project kind."""
from dataclasses import dataclass
from functools import cache
from hashlib import sha256
from pathlib import Path

_DIRECTORY = Path(__file__).resolve().parent
_KINDS = frozenset(("web", "slides", "game", "video"))
_FRONTEND_DESIGN_SCOPE = """以下 Frontend Design 仅用于网站的视觉设计。平台的输出格式、运行边界及用户明确要求优先。
在现有任务规划或内部思考中完成设计取舍，无需另行确认或输出额外方案。用可用的本地字体、配图及 CSS 实现，不加载外部资源。
迭代已有网站时，按本次要求修改，保留其他功能和视觉风格。"""


@dataclass(frozen=True)
class GenerationSkill:
    kind: str
    instructions: str
    revision: str


def skill_for(kind: str | None, *, threejs: bool = False) -> GenerationSkill:
    return _load_skill(kind if kind in _KINDS else "web", threejs=kind == "game" and threejs)


@cache
def _load_skill(kind: str, *, threejs: bool) -> GenerationSkill:
    text = (_DIRECTORY / f"{kind}.md").read_text(encoding="utf-8").strip()
    if kind == "web":
        upstream = (_DIRECTORY / "frontend-design" / "SKILL.md").read_text(encoding="utf-8")
        # The bundled Skill has YAML front matter for skill discovery, not generation.
        _, _, design = upstream.split("---\n", 2)
        text = "\n\n".join((text, _FRONTEND_DESIGN_SCOPE, design.strip()))
    if kind == "game":
        filename = "threejs-game.md" if threejs else "game-2d.md"
        guidance = (_DIRECTORY / filename).read_text(encoding="utf-8").strip()
        text = "\n\n".join((text, guidance))
    return GenerationSkill(
        kind=kind,
        instructions=text,
        revision=sha256(text.encode("utf-8")).hexdigest()[:12],
    )
