import asyncio
from datetime import UTC, datetime
import json
from xml.etree import ElementTree

import httpx
import pytest

from atoms import worker
from atoms.db import compact, one, transaction
from atoms.editorial_feed import NEWS_FILE, _FEEDS, parse_article
from atoms.model_fixture import adapted_website
from atoms.website_starters import MEDIA_FILE, match_website_starter
from conftest import create_project, submit
from test_workflow import VALIDATION


@pytest.mark.parametrize("request_text,slug", [
    ("生成一个财经新闻网站", "editorial"),
    ("帮我做一个个人作品集", "portfolio"),
    ("Create a product landing page.", "landing"),
    ("做一个猫摄影作品集，用黑白色，支持按场景分类", "portfolio"),
    ("做一个租金和水电分摊计算器", None),
    ("创建新闻网站，不用模板", None),
    ("做一个作品集和一个产品发布页", None),
])
def test_intent_keeps_custom_requests_and_ambiguous_cases(request_text, slug):
    match = match_website_starter(request_text)
    assert (match.slug if match else None) == slug


def test_news_preserves_real_publication_and_rejects_stale_or_foreign_entries():
    now = datetime(2026, 11, 12, 10, tzinfo=UTC)
    item = ElementTree.fromstring('''<item><title>月度发布</title>
    <link>https://www.stats.gov.cn/sj/zxfb/example.html</link><pubDate>2026-11-09 09:30:02</pubDate></item>''')
    assert parse_article(item, _FEEDS[0], now)["published_at"] == "2026-11-09T01:30:02+00:00"
    item.find("pubDate").text = "2024-06-03 09:30:00"
    assert parse_article(item, _FEEDS[0], now) is None
    item.find("pubDate").text = "2026-11-09 09:30:02"
    item.find("link").text = "https://example.com/report"
    assert parse_article(item, _FEEDS[0], now) is None


def test_custom_themes_reuse_images_only_when_explicitly_requested():
    starter = match_website_starter("做一个产品发布页")
    assert json.loads(starter.media_for("做一个产品发布页")) == {}
    assert json.loads(starter.media_for("做一个产品发布页，主题改为茶具，不保留模板原图")) == {}
    assert "hero" in json.loads(starter.media_for("做一个产品发布页，保留模板配图"))


@pytest.mark.parametrize("request_text,expected", [
    ("生成一个财经新闻网站", "editorial"),
    ("做一个个人作品集", "portfolio"),
    ("搭建一个产品发布页", "landing"),
])
def test_short_requests_use_templates_as_generation_context(client, monkeypatch, request_text, expected):
    project = create_project(client)
    assert submit(client, project["id"], request_text).status_code == 202
    run = worker.claim("test-leader")
    snapshot = {"status":"available", "collected_at":"2026-11-12T10:00:00+00:00", "items":[]}

    calls = []

    async def generated(run, context, repair, **kwargs):
        reference = context["website_starter"]
        assert reference["id"] == expected
        assert context["request"] == request_text
        assert repair is None
        calls.append(reference["id"])
        files = json.loads(adapted_website(reference))["files"]
        files["src/App.tsx"] = "export default function App(){return <main>重新设计后的首稿</main>}"
        return compact({"schema_version":"2", "title":"新主题", "summary":"新首稿", "files":files})

    async def feed():
        return snapshot

    def validate(request):
        artifact = json.loads(request.content)["artifact"]
        assert artifact["schema_version"] == "2"
        assert "重新设计后的首稿" in artifact["files"]["src/App.tsx"]
        if expected == "editorial":
            assert json.loads(artifact["files"][NEWS_FILE]) == snapshot
        else:
            assert json.loads(artifact["files"][MEDIA_FILE]) == {}
        return httpx.Response(200, json=VALIDATION)

    original = httpx.AsyncClient
    monkeypatch.setattr(worker, "paid_generate", generated)
    monkeypatch.setattr(worker, "editorial_snapshot", feed)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(validate)))
    asyncio.run(worker.execute_run(run))
    assert calls == [expected]
    with transaction() as conn:
        artifact = one(conn, "SELECT validation_json FROM artifacts")
    assert json.loads(artifact["validation_json"])["website_starter"] == expected


@pytest.mark.parametrize("request_text,matched", [
    ("做一个个人作品集，首页写摄影师林枫，改成深蓝色", True),
    ("做一个租金和水电分摊计算器", False),
])
def test_model_gets_editable_template_sources_only_when_matched(client, monkeypatch, request_text, matched):
    project = create_project(client)
    assert submit(client, project["id"], request_text).status_code == 202
    run = worker.claim("test-leader")

    async def generated(run, context, repair, **kwargs):
        assert ("website_starter" in context) is matched
        assert context["request"] == request_text
        if matched:
            files = context["website_starter"]["files"]
            assert "src/data/projects.json" in files and MEDIA_FILE not in files
            assert context["starter_media_keys"] == []
        return compact({"schema_version":"2", "title":"测试", "summary":"定制首稿", "files":{
            "src/App.tsx":"export default function App(){return <main/>}",
            "src/styles.css":"body{margin:0}", "src/data/config.json":"{}",
            MEDIA_FILE:'{"hero":"model-supplied"}',
        }})

    def validate(request):
        files = json.loads(request.content)["artifact"]["files"]
        if matched:
            assert json.loads(files[MEDIA_FILE]) == {}
        else:
            assert MEDIA_FILE not in files
        return httpx.Response(200, json=VALIDATION)

    original = httpx.AsyncClient
    monkeypatch.setattr(worker, "paid_generate", generated)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(validate)))
    asyncio.run(worker.execute_run(run))
