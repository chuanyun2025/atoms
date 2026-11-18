"""Select and load editable React starters for common website intents."""

import base64
import re
from dataclasses import dataclass
from functools import cache

from atoms import PACKAGE_ROOT, REPO_ROOT
from atoms.core.db import compact

_ROOT = PACKAGE_ROOT
_PUBLIC = REPO_ROOT / "apps" / "web" / "public"
MEDIA_FILE = "src/assets/starter-media.json"
COPY_SLOT = re.compile(r"\[\[copy:([a-z0-9_.-]+)\]\]")


@dataclass(frozen=True)
class WebsiteStarter:
    slug: str
    intent: str
    media: tuple[tuple[str, str], ...] = ()

    def matches(self, request: str) -> bool:
        return bool(re.search(self.intent, request, re.I))

    def media_for(self, request: str) -> str | None:
        if not self.media:
            return None
        keeps_media = re.search(
            r"(?:^|[，。；,;\n]\s*)(?:请\s*|please\s+)?(?:(?:保留|沿用)模板(?:的)?(?:原图|配图|图片)|keep (?:the )?template (?:images|photos)\b)",
            request.strip(),
            re.I,
        )
        return self.media_json() if keeps_media else "{}"

    def reference(self) -> dict:
        folder = _ROOT / "website_templates" / self.slug
        return {
            "id": self.slug,
            "files": {
                path.relative_to(folder).as_posix(): path.read_text("utf-8")
                for path in sorted(folder.rglob("*"))
                if path.is_file()
            },
        }

    def media_json(self) -> str:
        return _encode_starter_media(self.media)


@cache
def _encode_starter_media(media: tuple[tuple[str, str], ...]) -> str:
    return compact(
        {
            name: "data:image/webp;base64," + base64.b64encode((_PUBLIC / path).read_bytes()).decode("ascii")
            for name, path in media
        }
    )


STARTERS = (
    WebsiteStarter(
        "editorial",
        r"(?:财经|金融|经济|商业)?(?:新闻|资讯)(?:网站|站点|门户|站)|新闻门户|\b(?:financial |finance |economic )?news (?:website|site|portal)\b",
    ),
    WebsiteStarter(
        "portfolio",
        r"(?:设计师|摄影师|设计|摄影|个人)?作品集(?:网站|站点|网页)?|\b(?:personal |designer |photography )?portfolio(?: (?:website|site))?\b",
        (("ceramics", "examples/ceramics.webp"), ("coast", "examples/coast.webp"), ("future", "examples/future.webp")),
    ),
    WebsiteStarter(
        "landing",
        r"(?:产品|新品|SaaS|应用)?落地页|(?:产品|新品)发布(?:页|网站)|\b(?:product |saas )?landing page\b",
        (("hero", "templates/launch-speaker.webp"),),
    ),
)


def match_website_starter(request: str) -> WebsiteStarter | None:
    # Ambiguous requests and explicit template opt-outs go through open generation.
    if re.search(r"(?:不用|不要|不使用|不套用|别用).{0,8}模板|\b(?:no|without) (?:a )?template\b", request, re.I):
        return None
    matches = [starter for starter in STARTERS if starter.matches(request)]
    return matches[0] if len(matches) == 1 else None
