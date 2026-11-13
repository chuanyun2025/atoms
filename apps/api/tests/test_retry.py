import asyncio
import json
import uuid
import httpx
import pytest
from atoms import worker
from atoms.db import transaction,one,execute,compact
from atoms.model import ModelError,ModelResult,Usage
from atoms.worker import claim,fail,keep_candidate,execute_run,LeaseLost
from conftest import create_project,submit
from test_workflow import ARTIFACT,VALIDATION,complete


def failed_candidate(client,p,raw=None):
    result=submit(client,p["id"])
    assert result.status_code==202
    run=claim("test-leader")
    if raw is not None:
        keep_candidate(run,raw,"不支持的 HTML 属性：list",1)
    fail(run,"VALIDATION_FAILED","代码未通过校验：不支持的 HTML 属性：list")
    return run


def retry(client,p,source,prompt=None):
    return client.post("/api/v1/projects/"+p["id"]+"/runs",
        json={"prompt":prompt or source["prompt"],"expected_revision":p["revision"],
              "base_version_id":p["current_version_id"],"retry_of_run_id":source["id"]},
        headers={"Idempotency-Key":uuid.uuid4().hex})


def validator(monkeypatch,results):
    original=httpx.AsyncClient
    responses=iter(results)
    def handle(request):
        assert request.url.path=="/internal/validate"
        return httpx.Response(200,json=next(responses))
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs:original(transport=httpx.MockTransport(handle)))


def test_retained_candidate_can_deliver_without_model_or_credits(client,monkeypatch):
    p=create_project(client)
    source=failed_candidate(client,p,compact(ARTIFACT))
    with transaction(True) as conn:
        execute(conn,"UPDATE credit_wallets SET balance_units=0")
    result=retry(client,p,source)
    assert result.status_code==202,result.text
    run=claim("test-leader")
    async def no_model(*args,**kwargs):
        pytest.fail("Retained valid candidate must not invoke or charge the model")
    monkeypatch.setattr(worker,"paid_generate",no_model)
    validator(monkeypatch,[VALIDATION])
    asyncio.run(execute_run(run))
    result=client.get("/api/v1/runs/"+run["id"]).json()
    assert result["status"]=="succeeded" and result["model_calls"]==0
    with transaction() as conn:
        assert one(conn,"SELECT balance_units FROM credit_wallets")["balance_units"]==0
        assert not one(conn,"SELECT run_id FROM run_candidates WHERE run_id=:id",id=run["id"])
        assert one(conn,"SELECT run_id FROM run_candidates WHERE run_id=:id",id=source["id"])


def test_failed_work_is_saved_and_next_repair_uses_it(client,monkeypatch):
    monkeypatch.setattr(worker,"MAX_REPAIR_ROUNDS",1)
    p=create_project(client);assert submit(client,p["id"]).status_code==202
    run=claim("test-leader")
    react_artifact={**ARTIFACT,"schema_version":"2","files":{
        "src/App.tsx":"export default function App(){return <main>测试</main>}",
        "src/styles.css":"body{margin:0}",
        "src/components/Label.tsx":"export function Label(){return <span>测试</span>}",
    }}
    outputs=iter(['{"bad":"first"}','{"bad":"last"}',compact(react_artifact)])
    prompts=[]
    async def generated(prepared,output_limit,**kwargs):
        prompts.append(prepared.messages)
        return ModelResult(next(outputs),Usage(1200,400,"test-call-"+str(len(prompts))))
    monkeypatch.setattr(worker,"generate",generated)
    validator(monkeypatch,[{"ok":False,"error":"first invalid"},{"ok":False,"error":"last invalid"},
                           {"ok":False,"error":"still invalid"},VALIDATION])
    with pytest.raises(ModelError) as caught:
        asyncio.run(execute_run(run))
    fail(run,caught.value.code,str(caught.value))
    with transaction() as conn:
        saved=one(conn,"SELECT * FROM run_candidates WHERE run_id=:id",id=run["id"])
        assert saved["raw_content"]=='{"bad":"last"}' and saved["diagnostics"]=="last invalid"
        assert one(conn,"SELECT model_calls FROM runs WHERE id=:id",id=run["id"])["model_calls"]==2
    message=client.get("/api/v1/projects/"+p["id"]+"/messages").json()["items"][-1]
    assert message["has_candidate"] and message["run_prompt"]==run["prompt"]
    result=retry(client,p,run);assert result.status_code==202
    continued=claim("test-leader")
    asyncio.run(execute_run(continued))
    assert client.get("/api/v1/runs/"+continued["id"]).json()["model_calls"]==1
    feedback=json.loads(prompts[-1][-1]["content"].split("\n",1)[1])
    assert feedback["candidate"]=='{"bad":"last"}' and feedback["diagnostics"]=="still invalid"
    with transaction() as conn:
        assert one(conn,"SELECT COUNT(*) n FROM model_calls WHERE run_id=:id",id=continued["id"])["n"]==1
        assert one(conn,"SELECT current_version_id FROM projects WHERE id=:id",id=p["id"])["current_version_id"]


def test_legacy_failure_has_action_and_diagnostic_context(client,monkeypatch):
    p=create_project(client);source=failed_candidate(client,p)
    message=client.get("/api/v1/projects/"+p["id"]+"/messages").json()["items"][-1]
    assert not message["has_candidate"]
    assert retry(client,p,source).status_code==202
    run=claim("test-leader")
    context=worker.read_context(run)
    assert context["_resume"]["candidate"] is None
    assert "list" in context["_resume"]["diagnostics"]


def test_retry_is_scoped_to_project_prompt_and_current_version(client):
    p=create_project(client);source=failed_candidate(client,p,compact(ARTIFACT))
    assert retry(client,p,source,prompt="不同需求").status_code==409
    other=client.post("/api/v1/projects",json={"client_key":"different-project-key","title":"另一个项目"}).json()
    assert retry(client,other,source).status_code==404
    current,successful=complete(client,p,request_key="fresh-request-key")
    assert retry(client,current,source).json()["detail"]["code"]=="retry_base_changed"
    assert retry(client,current,successful).json()["detail"]["code"]=="run_not_retryable"
    with pytest.raises(LeaseLost):
        keep_candidate(source,"late overwrite","stale",2)


def test_validator_outage_keeps_candidate_for_later(client,monkeypatch):
    p=create_project(client);assert submit(client,p["id"]).status_code==202
    run=claim("test-leader")
    original=httpx.AsyncClient
    def unavailable(request):
        return httpx.Response(503)
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs:original(transport=httpx.MockTransport(unavailable)))
    with pytest.raises(ModelError) as caught:
        asyncio.run(worker.validate_candidate(run,compact(ARTIFACT),1))
    assert caught.value.code=="VALIDATOR_UNAVAILABLE"
    with transaction() as conn:
        assert one(conn,"SELECT raw_content FROM run_candidates WHERE run_id=:id",id=run["id"])["raw_content"]==compact(ARTIFACT)


@pytest.mark.parametrize("temporary_response", [
    httpx.Response(429),
    httpx.Response(503,json={"ok":False,"error":"浏览器检查超时"}),
    httpx.Response(200,json={"ok":False,"error":"浏览器效果验收超时"}),
])
def test_temporary_validator_failure_rechecks_the_same_candidate(client,monkeypatch,temporary_response):
    project=create_project(client)
    assert submit(client,project["id"]).status_code==202
    run=claim("test-leader")
    original=httpx.AsyncClient
    received=[]

    def validate(request):
        received.append(json.loads(request.content)["artifact"])
        if len(received)==1:
            return temporary_response
        return httpx.Response(200,json=VALIDATION)

    monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs:original(transport=httpx.MockTransport(validate)))
    monkeypatch.setattr(worker,"VALIDATOR_RETRY_DELAYS",(0,))
    asyncio.run(worker.validate_with_retry(run,compact(ARTIFACT),1))
    assert received==[ARTIFACT,ARTIFACT]
    assert client.get("/api/v1/runs/"+run["id"]).json()["model_calls"]==0


def test_game_recovery_after_three_repairs_can_deliver_without_more_model_calls(client,monkeypatch):
    from atoms.model_fixture import game_artifact
    from atoms.orchestration import PLAN_FILE,TaskPlan

    project=client.post("/api/v1/projects",json={"client_key":"game-final-recheck","title":"游戏恢复","kind":"game"}).json()
    artifact=json.loads(game_artifact(broken=True,incomplete_replay=False))
    artifact["files"][PLAN_FILE]=compact(TaskPlan(experience="other_game",rendering="dom",
        requirements=["可进入游戏","能操作"],visual_direction="清晰可辨",
        specialist_brief="浏览器游戏",acceptance=["启动","运行"]).model_dump())
    assert submit(client,project["id"]).status_code==202
    source=claim("test-leader")
    keep_candidate(source,compact(artifact),"自动输入结果未确认",4)
    fail(source,"VALIDATION_FAILED","自动输入结果未确认")
    with transaction(True) as conn:
        execute(conn,"UPDATE credit_wallets SET balance_units=0")
    assert retry(client,project,source).status_code==202
    run=claim("test-leader")

    async def no_model(*args,**kwargs):
        pytest.fail("Saved final candidate should be rechecked without another model call")

    def validate(request):
        body=json.loads(request.content)
        assert "behavior_check" not in body
        assert "game_smoke" not in body
        return httpx.Response(200,json=VALIDATION)

    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs:original(transport=httpx.MockTransport(validate)))
    monkeypatch.setattr(worker,"agent_decision",no_model)
    monkeypatch.setattr(worker,"paid_generate",no_model)
    asyncio.run(execute_run(run))
    assert client.get("/api/v1/runs/"+run["id"]).json()["status"]=="succeeded"
    assert client.get("/api/v1/runs/"+run["id"]).json()["model_calls"]==0


@pytest.mark.parametrize("checked_base",[False,True])
def test_slide_edits_use_startup_even_when_base_used_navigation(client,monkeypatch,checked_base):
    created=client.post("/api/v1/projects",json={"client_key":"slides-test-key","title":"演示","kind":"slides"})
    assert created.status_code==201
    project,base_run=complete(client,created.json())
    if checked_base:
        report={"ready":True,"behavior_check":"slides-navigation-v1"}
        with transaction(True) as conn:
            execute(conn,"UPDATE artifacts SET validation_json=:report WHERE id=(SELECT artifact_id FROM versions WHERE source_run_id=:run)",
                    report=compact(report),run=base_run["id"])
    accepted=submit(client,project["id"],revision=project["revision"],base=project["current_version_id"],request_key="slide-edit-key")
    assert accepted.status_code==202
    run=claim("test-leader")

    async def generate_edit(run,context,repair,*,skill):
        assert skill.kind=="slides"
        assert "_base_behavior_check" not in context
        return compact(ARTIFACT)

    monkeypatch.setattr(worker,"paid_generate",generate_edit)
    validator(monkeypatch,[VALIDATION])
    asyncio.run(execute_run(run))
    with transaction() as conn:
        artifact=one(conn,"SELECT a.validation_json FROM artifacts a JOIN versions v ON v.artifact_id=a.id WHERE v.source_run_id=:run",run=run["id"])
    saved=json.loads(artifact["validation_json"])
    assert "behavior_check" not in saved
    assert saved["acceptance"]=="smoke"
    assert saved["generation_skill"]["kind"]=="slides"
