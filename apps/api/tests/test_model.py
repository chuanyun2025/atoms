import asyncio
import pytest
import httpx
from atoms.config import settings
from atoms.artifacts import strict_json
from atoms.model import generate,ModelError,Prepared
from atoms.prompts import messages_for
from atoms.skills import skill_for


def test_strict_duplicate_and_fences():
    assert strict_json('{"a":1}')=={"a":1}
    with pytest.raises(ValueError):strict_json('{"a":1,"a":2}')
    with pytest.raises(ValueError):strict_json('{"a":NaN}')


@pytest.mark.parametrize("kind,heading",[
    ("web","# 可交互网站"), ("slides","# 网页幻灯片"),
    ("game","# 浏览器游戏"), ("video","# 网页分镜样片"),
])
def test_project_kind_selects_single_skill(kind,heading):
    skill=skill_for(kind)
    messages=messages_for({"request":"只修改背景色"},None,skill=skill)
    assert heading in messages[0]["content"]
    assert "只修改背景色" not in messages[0]["content"]
    assert "只修改背景色" in messages[1]["content"]
    assert "data-deck-next" not in messages[0]["content"]
    assert ("web-artifacts-builder" in messages[0]["content"]) == (kind=="game")
    assert ("`pptx` Skill" in messages[0]["content"]) == (kind=="slides")
    assert ("# Frontend Design" in messages[0]["content"]) == (kind=="web")
    assert len(skill.revision)==12
    assert skill_for(kind) is skill


def test_frontend_design_applies_to_website_repairs_with_platform_contract():
    messages = messages_for(
        {"project_kind": "web", "site_format": "react", "request": "为一家旧书店做网站"},
        {"diagnostics": "窄屏出现横向滚动"},
        skill=skill_for("web"),
    )
    system, request, repair = messages
    assert '"schema_version":"2"' in system["content"]
    assert "平台的输出格式、运行边界及用户明确要求优先" in system["content"]
    assert "# Frontend Design" in system["content"]
    assert "事件来源与调用对象" in system["content"] and "自定义组件属性" in system["content"]
    assert "实际接收者" in repair["content"]
    assert "旧书店" in request["content"] and "横向滚动" in repair["content"]


def test_threejs_generation_and_repair_include_the_game_guidance():
    context = {"project_kind":"game", "site_format":"react", "request":"用 Three.js 制作飞行游戏"}
    skill = skill_for("game", threejs=True)
    for repair in (None, {"diagnostics":"重开时场景未清理"}):
        messages = messages_for(context, repair, skill=skill)
        assert "# Three.js 游戏制作指导" in messages[0]["content"]
        assert "CanvasTexture" in messages[0]["content"]
        assert "web-artifacts-builder" not in messages[0]["content"]
    assert skill.revision != skill_for("game").revision
    assert "# Three.js 游戏制作指导" not in skill_for("game").instructions
    assert skill_for("web", threejs=True) is skill_for("web")


def test_legacy_slide_revision_keeps_guidance_without_navigation_contract():
    messages=messages_for({"project_kind":"slides"},{"diagnostics":"原始修复反馈"},
                          skill=skill_for("slides"))
    assert "# 网页幻灯片" in messages[0]["content"]
    assert "data-deck-next" not in messages[0]["content"]
    assert "原始修复反馈" in messages[2]["content"]
    assert skill_for("unrecognized").kind=="web"


def test_provider_protocol_and_sanitized_errors(monkeypatch):
    config=settings()
    monkeypatch.setattr(config,"test_fixture",False)
    monkeypatch.setattr(config,"provider_gateway_token","internal-test-token")
    original=httpx.AsyncClient
    def handler(request):
        assert str(request.url)=="http://provider-gateway:8100/internal/v1/text/generate"
        assert request.headers["authorization"]=="Bearer internal-test-token"
        body=__import__("json").loads(request.content)
        assert "model" not in body and body["max_output_tokens"]==393216
        assert body["response_schema"]["name"]=="artifact"
        return httpx.Response(401,json={"error":{"code":"MODEL_AUTH","message":"模型服务认证失败"}})
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs:original(**{**kwargs, 'transport':httpx.MockTransport(handler)}))
    with pytest.raises(ModelError) as caught:
        asyncio.run(generate(Prepared([{"role":"user","content":"测试"}],2000,393216),393216))
    assert caught.value.code=="MODEL_AUTH" and "secret" not in str(caught.value)
