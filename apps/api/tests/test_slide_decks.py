import pytest

from atoms.prompts import messages_for
from atoms.skills import skill_for
from atoms.slide_decks import render_slide_deck
from atoms.slide_templates import slide_template_reference


def test_template_artifact_contains_platform_navigation_and_escaped_content():
    template = slide_template_reference("quarterly-review")
    deck = render_slide_deck({
        "title": "季度复盘",
        "summary": "四项材料待补充",
        "slides": [
            {"title": "客户运营 Q2", "description": "<待补充>", "items": []},
            {"title": "目标与结果", "description": "", "items": [{"label": "指标", "detail": "待补充"}]},
            {"title": "主要变化", "description": "", "items": []},
            {"title": "下一步", "description": "", "items": []},
        ],
    }, template)
    html = deck["files"]["index.html"]
    assert html.count("data-deck-slide") == 4
    assert 'class="deck-slide deck-metrics" data-deck-slide hidden' in html
    assert "&lt;待补充&gt;" in html
    assert "<待补充>" not in html
    assert "--deck-accent:#325dd8" in deck["files"]["styles.css"]
    assert "ArrowRight" in deck["files"]["app.js"]


def test_legacy_outline_is_repaired_as_content_without_resending_fake_code():
    template = slide_template_reference("quarterly-review")
    outline = {"files": {"app.js": "翻页状态；仅描述实现方案"}}
    with pytest.raises(ValueError, match=r"slides \(missing\)"):
        render_slide_deck(outline, template)
    messages = messages_for({"slide_template": template, "request": "季度复盘"}, {
        "candidate": '{"files":{"app.js":"翻页状态；仅描述实现方案"}}',
        "diagnostics": "幻灯片内容字段不符合约定",
    }, skill=skill_for("slides"))
    assert "逐页内容" in messages[0]["content"]
    assert "幻灯片内容字段不符合约定" in messages[2]["content"]
    assert "仅描述实现方案" not in messages[2]["content"]
