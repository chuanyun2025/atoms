import asyncio
import json

import httpx
import pytest

from atoms.config import settings
from atoms.game_benchmarks import match_genre
from atoms.game_profiles import game_profile
from atoms.orchestration import PLAN_FILE, TaskPlan, TaskReview, enforce_plan, parse_decision, requests_fps
from atoms import worker
from atoms.worker import agent_decision as real_agent_decision
from conftest import create_project, submit


def plan():
    return TaskPlan(experience="other_game",rendering="canvas2d",
        requirements=["可点击目标","显示分数"],visual_direction="有主次的布局",
        specialist_brief="实现射击游戏",acceptance=["启动","操作"])


def test_fps_expectations_survive_a_planner_downgrade():
    context={"project_kind":"game","request":"生成一个3D视角的fps游戏，类似CS","base_artifact":None}
    assert requests_fps(context)
    resolved=enforce_plan(plan(),context)
    assert resolved.experience=="first_person_3d" and resolved.rendering=="threejs"
    assert requests_fps({**context,"request":"生成一个FPS枪战游戏"})
    assert resolved.game_genre=="fps"
    assert resolved.requirements==plan().requirements
    assert not requests_fps({**context,"project_kind":"web","request":"做个FPS游戏介绍网站"})
    assert not requests_fps({**context,"request":"做一个平台跳跃游戏"})
    assert requests_fps({**context,"request":"做一个类似CS2的游戏"})
    assert not requests_fps({**context,"request":"制作60FPS的竞速游戏"})


def test_racing_defaults_to_2d_and_respects_explicit_3d():
    context={"project_kind":"game","request":"生成一个赛车游戏","base_artifact":None}
    proposed=plan().model_copy(update={"experience":"track_racing","rendering":"threejs"})
    racing=enforce_plan(proposed,context)
    assert racing.experience=="other_game" and racing.rendering=="canvas2d"
    assert racing.game_genre=="racing"
    assert racing.requirements==plan().requirements
    explicit=enforce_plan(racing,{**context,"request":"做一个3D赛车游戏，不要道具"})
    assert explicit.experience=="track_racing" and explicit.rendering=="threejs"
    top_down=enforce_plan(explicit,{**context,"request":"做一个2D俯视赛车游戏"})
    assert top_down.experience=="other_game" and top_down.rendering=="canvas2d"


@pytest.mark.parametrize(("request_text", "rendering", "has_existing_scene", "expected"), [
    ("用 Three.js 做一个飞行游戏", "canvas2d", False, True),
    ("制作一个俯视的 3D 塔防游戏", "threejs", False, True),
    ("制作一个二维消除游戏", "threejs", False, False),
    ("制作一个二维 FPS 游戏", "threejs", False, False),
    ("做一个第一人称射击游戏", "dom", False, True),
    ("Make a first-person shooter", "dom", False, True),
    ("制作60FPS的竞速游戏", "threejs", False, False),
    ("做一个赛车游戏，带 FPS 计数器", "threejs", False, False),
    ("做一个射击游戏，不要做 FPS", "threejs", False, False),
    ("做一个塔防游戏", "threejs", False, False),
    ("做一个小游戏，不需要用3D", "threejs", False, False),
    ("做一个3D解谜游戏", "dom", False, True),
    ("制作俄罗斯方块", "threejs", False, False),
    ("制作一个3D游戏，不要2D", "dom", False, True),
    ("把 3D 改成 2D", "threejs", True, False),
    ("给现有游戏加音效", "dom", True, True),
    ("把现有游戏改成 2D 横版", "threejs", True, False),
    ("改成不使用3D的游戏", "threejs", True, False),
])
def test_threejs_skill_routing(request_text, rendering, has_existing_scene, expected):
    context = {"project_kind":"game", "request":request_text}
    if has_existing_scene:
        context["base_artifact"] = {"files":{"src/game/scene.ts":'import * as THREE from "three";'}}
    resolved = enforce_plan(plan().model_copy(update={"rendering":rendering}), context)
    assert (resolved.rendering == "threejs") is expected


def test_structured_planning_fields_preserve_their_content():
    value=plan().model_dump()
    value.update(requirements={"视角":"第一人称","输入":["WASD","鼠标拖动"]},
                 visual_direction={"场景":"港口仓库","光照":"清晰日光"})
    result=parse_decision("planner",value)
    assert result.requirements[0]=="视角 第一人称"
    assert "WASD" in result.requirements[1]
    assert "清晰日光" in result.visual_direction


def test_optional_planner_ideas_do_not_become_blocking_fps_requirements():
    proposed=plan().model_copy(update={"enhancements":["重生系统"]})
    resolved=enforce_plan(proposed,{"project_kind":"game","request":"生成一个FPS枪战游戏"})
    assert "重生系统" in resolved.enhancements
    assert "重生系统" not in resolved.requirements
    review=parse_decision("reviewer",{
        "accepted":True,"findings":[],"suggestions":["可以增加右键瞄准"],
    })
    assert review.accepted and not review.findings


def test_default_2d_game_repairs_a_candidate_using_threejs(client, monkeypatch):
    from atoms import model_fixture
    from test_retry import validator
    from test_workflow import GAME_VALIDATION

    project = client.post("/api/v1/projects", json={
        "client_key": "racing-test-key", "title": "赛车", "kind": "game",
    }).json()
    assert submit(client, project["id"], "生成一个赛车游戏").status_code == 202
    run = worker.claim("test-leader")

    async def search(genre):
        return {"status": "static", "genre": genre, "games": []}

    async def generate(run, context, repair, **kwargs):
        assert context["task_plan"]["rendering"] in {"dom", "canvas2d"}
        candidate = model_fixture.test_artifact(context, repair)
        if repair:
            assert "本次游戏需要 2D 渲染" in repair["diagnostics"]
            return candidate
        artifact = json.loads(candidate)
        artifact["files"]["src/App.tsx"] = 'import * as THREE from "three";\n' + artifact["files"]["src/App.tsx"]
        return json.dumps(artifact)

    monkeypatch.setattr(worker, "find_game_references", search)
    monkeypatch.setattr(worker, "paid_generate", generate)
    validator(monkeypatch, [GAME_VALIDATION])
    asyncio.run(worker.execute_run(run))
    assert client.get("/api/v1/runs/" + run["id"]).json()["status"] == "succeeded"


def test_game_profiles_cover_genre_families_and_fallback():
    assert game_profile("arcade_platformer")!=game_profile("platformer")
    assert game_profile("racing")!=game_profile("sports")
    assert game_profile("match3")!=game_profile("puzzle")
    assert game_profile("tower_defense")!=game_profile("strategy")
    assert game_profile("puzzle")==game_profile("rhythm")
    assert game_profile("card")==game_profile("simulation")
    assert game_profile("other")["name"]=="通用游戏"


@pytest.mark.parametrize(("request_text","genre"),[
    ("生成一个雪人兄弟游戏","arcade_platformer"),
    ("做一个 Snow Bros. 风格的横版平台跳跃游戏","arcade_platformer"),
    ("做一个像马里奥的横版跳跃游戏","platformer"),
    ("做一个用连锁消除过关的三消解谜游戏","match3"),
    ("做个像植物大战僵尸的策略游戏","tower_defense"),
    ("做一个结合三消和塔防的游戏",None),
])
def test_specific_mechanics_route_before_broad_genre(request_text,genre):
    assert match_genre(request_text)==genre


@pytest.mark.parametrize(("request_text","genre","reference"),[
    ("做一个类似马里奥的平台跳跃游戏","platformer",None),
    ("生成一个雪人兄弟游戏","arcade_platformer","snowball-arcade"),
    ("做一个固定屏平台清场游戏","arcade_platformer",None),
    ("做一个宝石三消游戏","match3","match-three"),
    ("做一个花园塔防游戏","tower_defense","tower-defense"),
])
def test_game_research_and_template_reach_the_generation_pipeline(client, monkeypatch, request_text, genre, reference):
    from atoms import model_fixture
    from test_retry import validator
    from test_workflow import GAME_VALIDATION

    project = client.post("/api/v1/projects", json={
        "client_key": "platformer-test-key", "title": "平台跳跃", "kind": "game",
    }).json()
    assert submit(client, project["id"], request_text).status_code == 202
    run = worker.claim("test-leader")
    calls = []
    research = {"status": "live", "genre": genre, "games": [{"title": "Example Platformer"}]}

    async def search(requested_genre):
        assert requested_genre == genre
        calls.append("research")
        return research

    async def decision(run, role, context):
        if role=="reviewer":
            assert context["task_plan"]["game_genre"] == genre
            assert context["game_profile"] == game_profile(genre)
            return TaskReview(accepted=True,findings=[])
        assert role=="planner"
        assert calls == ["research"]
        assert context["game_dimension"] == "2d"
        assert context["game_research"] == research
        assert context["game_benchmarks"][genre]["sources"]
        assert context["game_profile"] == game_profile(genre)
        return plan()

    async def generate(run, context, repair, **kwargs):
        assert context["task_plan"]["game_genre"] == genre
        assert context["task_plan"]["rendering"] == "canvas2d"
        assert "web-artifacts-builder" in kwargs["skill"].instructions
        assert context["game_research"] == research
        assert context["game_profile"] == game_profile(genre)
        assert not context["fps_required"]
        if reference:
            assert context["game_reference"]["id"] == reference
            assert context["game_reference"]["files"]
        else:
            assert "game_reference" not in context
        return model_fixture.test_artifact(context, repair)

    monkeypatch.setattr(worker, "agent_decision", decision)
    monkeypatch.setattr(worker, "paid_generate", generate)
    monkeypatch.setattr(worker, "find_game_references", search)
    validator(monkeypatch, [GAME_VALIDATION])
    asyncio.run(worker.execute_run(run))
    assert client.get("/api/v1/runs/" + run["id"]).json()["status"] == "succeeded"


def test_saved_plan_survives_recheck_failure_and_runtime_repair(client,monkeypatch):
    from atoms.db import compact, one, all_rows, transaction
    from atoms.model import ModelResult, Usage
    from test_retry import failed_candidate, retry, validator
    from test_workflow import GAME_VALIDATION

    saved_plan=plan().model_copy(update={"experience":"website","rendering":"dom"})
    artifact={"schema_version":"2","title":"测试","summary":"已完成","files":{
        "src/App.tsx":"export default function App(){return <main>计数器</main>}",
        "src/styles.css":"body{margin:0}",
        PLAN_FILE:compact(saved_plan.model_dump()),
    }}
    project=create_project(client)
    source=failed_candidate(client,project,compact(artifact))
    assert retry(client,project,source).status_code==202
    run=worker.claim("test-leader")
    async def generated(prepared,output_limit,**kwargs):
        assert prepared.decision_role is None
        context=json.loads(prepared.messages[1]["content"])
        assert context["task_plan"]["experience"]=="website"
        return ModelResult(compact(artifact),Usage(1200,400,"test-recovery"))

    monkeypatch.setattr(worker,"agent_decision",real_agent_decision)
    monkeypatch.setattr(worker,"generate",generated)
    validator(monkeypatch,[{"ok":False,"error":"需要修复"},GAME_VALIDATION])
    asyncio.run(worker.execute_run(run))
    assert client.get("/api/v1/runs/"+run["id"]).json()["status"]=="succeeded"
    with transaction() as conn:
        calls=all_rows(conn,"SELECT attempt,status FROM model_calls WHERE run_id=:id ORDER BY attempt",id=run["id"])
        assert [call["attempt"] for call in calls]==[1]
        assert all(call["status"]=="settled" for call in calls)
        assert one(conn,"SELECT held_units FROM credit_wallets")["held_units"]==0


def test_planner_and_review_calls_are_separately_accounted(client,monkeypatch):
    project=create_project(client)
    assert submit(client,project["id"]).status_code==202
    run=worker.claim("test-leader")
    config=settings()
    monkeypatch.setattr(config,"test_fixture",False)
    monkeypatch.setattr(worker,"agent_decision",real_agent_decision)
    original=httpx.AsyncClient
    results=iter([plan().model_dump(),{"accepted":False,"findings":[{"path":"src/App.tsx","excerpt":"const camera = null","problem":"按方向键无法移动镜头"}]}])
    def handle(request):
        if request.method=="GET":
            return httpx.Response(200,json={"max_output_tokens":4096})
        content=json.dumps(next(results),ensure_ascii=False)
        return httpx.Response(200,json={"content":content,"usage":{"input_tokens":300,"output_tokens":120}})
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs:original(**{**kwargs, 'transport':httpx.MockTransport(handle)}))
    first=asyncio.run(real_agent_decision(run,"planner",{"request":"做一个游戏"}))
    last=asyncio.run(real_agent_decision(run,"reviewer",{"request":"做一个游戏","artifact":{}}))
    assert first.rendering=="canvas2d"
    assert not last.accepted
    assert client.get("/api/v1/runs/"+run["id"]).json()["model_calls"]==2
    wallet=client.get("/api/v1/wallet").json()
    assert wallet["held"]=="0.000000" and wallet["spent"]=="0.031200"
