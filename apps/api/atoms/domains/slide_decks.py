"""Render a template-backed slide artifact from validated presentation content."""

from functools import cache
from html import escape
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from atoms import PACKAGE_ROOT

_ASSETS = PACKAGE_ROOT / "deck_assets"
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class DeckItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    label: NonBlank
    detail: NonBlank


class DeckPage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: NonBlank
    description: str
    items: list[DeckItem]


class DeckContent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: Annotated[NonBlank, Field(max_length=80)]
    summary: Annotated[NonBlank, Field(max_length=600)]
    slides: list[DeckPage] = Field(min_length=1)


@cache
def _asset(name: str) -> str:
    return (_ASSETS / name).read_text(encoding="utf-8")


def _page_layout(layouts: list[dict], index: int, total: int) -> str:
    if index == 0:
        return "cover"
    if index == total - 1:
        return layouts[-1]["layout"]
    return layouts[min(index, len(layouts) - 2)]["layout"]


def _render_page(page: DeckPage, layout: str, index: int) -> str:
    items = "".join(
        f"<li><strong>{escape(item.label)}</strong><span>{escape(item.detail)}</span></li>" for item in page.items
    )
    visibility = " hidden" if index else ""
    title = f"<h2>{escape(page.title)}</h2>" if index else f"<h1>{escape(page.title)}</h1>"
    description = f"<p>{escape(page.description)}</p>" if page.description.strip() else ""
    content = f'<ul class="deck-items">{items}</ul>' if items else ""
    artwork = '<div class="deck-cover-art" aria-hidden="true"><i></i><i></i><i></i></div>' if layout == "cover" else ""
    return (
        f'<section class="deck-slide deck-{layout}" data-deck-slide{visibility}>'
        f'<div class="deck-copy">{title}{description}</div>{artwork}{content}</section>'
    )


def render_slide_deck(value: dict, template: dict) -> dict:
    try:
        deck = DeckContent.model_validate(value)
    except ValidationError as exc:
        fields = [
            f"{'.'.join(map(str, error['loc'])) or '根对象'} ({error['type']})"
            for error in exc.errors(include_url=False, include_context=False, include_input=False)[:8]
        ]
        raise ValueError("幻灯片内容字段不符合约定：" + "；".join(fields)) from None

    total = len(deck.slides)
    pages = "".join(
        _render_page(page, _page_layout(template["layout_sequence"], index, total), index)
        for index, page in enumerate(deck.slides)
    )
    palette = template["palette"]
    colors = ":root{" + "".join(f"--deck-{name}:{value};" for name, value in palette.items()) + "}"
    html = (
        f'<main class="deck-shell deck-theme-{template["theme"]}">{pages}'
        '<nav class="deck-nav" aria-label="幻灯片导航">'
        '<button type="button" data-deck-prev disabled>上一页</button>'
        f'<output data-deck-position aria-live="polite">1 / {total}</output>'
        f'<button type="button" data-deck-next{" disabled" if total == 1 else ""}>下一页</button>'
        "</nav></main>"
    )
    return {
        "schema_version": "1",
        "title": deck.title,
        "summary": deck.summary,
        "files": {
            "index.html": html,
            "styles.css": colors + "\n" + _asset("slides.css"),
            "app.js": _asset("slides.js"),
        },
    }
