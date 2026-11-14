import io
import json
import time
import zipfile
import pytest
from fastapi.testclient import TestClient
from atoms.main import app
from atoms.db import transaction,one,execute,all_rows
from atoms.worker import claim,commit,recover_expired,LeaseLost,fail,read_context
from conftest import create_project,submit

ARTIFACT={"schema_version":"1","title":"计数器","summary":"支持计数和保存","files":{"index.html":"<button>计数</button>","styles.css":"body{color:green}","app.js":"void 0;"}}
VALIDATION={"ok":True,"compiled":{"body_html":"<button>计数</button>","css_base64":"","js_base64":"dm9pZCAwOw==","digest":"test-digest","compiler_version":"1","sdk_version":"1"},"report":{"ready":True,"acceptance":"smoke"}}


def complete(client,project,prompt="创建计数器",request_key="request-test-key"):
    response=submit(client,project["id"],prompt,project["revision"],project["current_version_id"],request_key)
    assert response.status_code==202,response.text
    run=claim("test-leader")
    commit(run,ARTIFACT,VALIDATION)
    return client.get("/api/v1/projects/"+project["id"]).json(),run


def test_slide_template_is_persisted_and_used_for_first_build(client):
    request={"client_key":"project-template-key","title":"发布简报","kind":"slides","slide_template_id":"product-launch"}
    invalid=client.post("/api/v1/projects",json={**request,"slide_template_id":"missing"})
    assert invalid.status_code==422
    assert client.post("/api/v1/projects",json={**request,"kind":"game"}).status_code==422
    created=client.post("/api/v1/projects",json=request)
    assert created.status_code==201
    project=created.json()
    assert client.get("/api/v1/projects/"+project["id"]).json()["slide_template_id"]=="product-launch"
    assert client.post("/api/v1/projects",json={**request,"slide_template_id":"quarterly-review"}).status_code==409

    assert submit(client,project["id"],"使用我自己的主题").status_code==202
    run=claim("test-leader")
    context=read_context(run)
    assert context["request"]=="使用我自己的主题"
    template=context["slide_template"]
    assert template["palette"]["accent"]=="#ff9861"
    assert [page["layout"] for page in template["layout_sequence"]]==["cover","features","features","timeline"]
    assert "fields" not in template and "slides" not in template

    commit(run,ARTIFACT,VALIDATION)
    current=client.get("/api/v1/projects/"+project["id"]).json()
    assert submit(client,project["id"],"修改封面",current["revision"],current["current_version_id"],"template-edit-key").status_code==202
    edit=read_context(claim("test-leader"))
    assert edit["base_artifact"]==ARTIFACT
    assert "slide_template" not in edit


def test_owner_and_csrf(client):
    p=create_project(client)
    with TestClient(app,base_url="http://localhost:8080") as other:
        session=other.post("/api/v1/session",json={},headers={"Origin":"http://localhost:8080","X-App-Request":"atoms"})
        assert session.status_code==200
        assert other.get("/api/v1/projects/"+p["id"]).status_code==404
        assert other.get("/api/v1/projects/"+p["id"]+"/app-state").status_code==404
    assert client.post("/api/v1/projects",json={"client_key":"another-key"},headers={"Origin":"null"}).status_code==403
    assert client.post("/api/v1/projects",json={"client_key":"another-key"},headers={"X-CSRF-Token":"wrong"}).status_code==403


def test_idempotency_without_charging_before_a_model_call(client):
    p=create_project(client)
    r=submit(client,p["id"])
    assert r.status_code==202
    repeated=submit(client,p["id"])
    assert repeated.json()["id"]==r.json()["id"]
    assert submit(client,p["id"],"不同内容").status_code==409
    assert submit(client,p["id"],request_key="different-key").status_code==409
    with transaction() as conn:
        assert one(conn,"SELECT COUNT(*) n FROM messages")["n"]==1
        assert one(conn,"SELECT COUNT(*) n FROM quota_windows")["n"]==0
        assert one(conn,"SELECT COUNT(*) n FROM credit_ledger WHERE kind='welcome'")["n"]==1
        assert one(conn,"SELECT balance_units FROM credit_wallets")["balance_units"]==500_000_000


def test_completed_request_replays_before_stale_revision_check(client):
    p=create_project(client)
    current,run=complete(client,p)
    with transaction(True) as conn:
        execute(conn,"UPDATE credit_wallets SET balance_units=0")
    result=submit(client,p["id"])
    assert result.status_code==202 and result.json()["id"]==run["id"]
    assert result.json()["status"]=="succeeded"
    assert current["revision"]==1


def test_restore_branch_export_and_state(client):
    p=create_project(client)
    p,first=complete(client,p)
    v1=p["current_version_id"]
    patched=client.patch("/api/v1/projects/"+p["id"]+"/app-state",json={"expected_revision":0,"set":{"count":4}})
    assert patched.status_code==200
    assert client.patch("/api/v1/projects/"+p["id"]+"/app-state",json={"expected_revision":0,"set":{"count":99}}).status_code==409
    p,second=complete(client,p,"加筛选","second-request-key")
    v2=p["current_version_id"]
    result=client.post("/api/v1/projects/"+p["id"]+"/versions/"+v1+"/restore",json={"expected_revision":p["revision"]})
    assert result.status_code==200
    p=result.json()
    assert p["current_version_id"]==v1
    assert client.patch("/api/v1/projects/"+p["id"]+"/app-state",json={"expected_revision":1,"version_id":v2,"set":{"count":99}}).status_code==409
    assert client.get("/api/v1/projects/"+p["id"]+"/app-state").json()["values"]=={"count":4}
    # Replaying a completed restore is harmless even with the earlier revision.
    assert client.post("/api/v1/projects/"+p["id"]+"/versions/"+v1+"/restore",json={"expected_revision":p["revision"]-1}).status_code==200
    p,third=complete(client,p,"再修改","third-request-key")
    versions=client.get("/api/v1/projects/"+p["id"]+"/versions").json()["items"]
    assert len(versions)==3 and versions[0]["number"]==3 and versions[0]["parent_version_id"]==v1
    exported=client.get("/api/v1/projects/"+p["id"]+"/versions/"+v2+"/export")
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert set(archive.namelist())=={"index.html","styles.css","app.js","atoms-runtime.js","source/index.html","artifact.json","README.md"}
        assert archive.read("app.js").decode()==ARTIFACT["files"]["app.js"]
        assert b"SESSION_SECRET" not in archive.read("artifact.json")
    stream=client.get("/api/v1/runs/"+first["id"]+"/events",headers={"Last-Event-ID":"1"})
    assert "event: completed" in stream.text and "id: 1\n" not in stream.text


def test_expired_run_and_fencing(client):
    p=create_project(client)
    assert submit(client,p["id"]).status_code==202
    run=claim("test-leader")
    with transaction(True) as conn:
        execute(conn,"UPDATE runs SET lease_until=:until WHERE id=:id",until=time.time()-1,id=run["id"])
    recover_expired()
    with pytest.raises(LeaseLost):
        commit(run,ARTIFACT,VALIDATION)
    restored=client.get("/api/v1/projects/"+p["id"]).json()
    assert restored["active_run_id"] is None and restored["revision"]==0
    assert client.get("/api/v1/runs/"+run["id"]).json()["status"]=="interrupted"
    with transaction() as conn:
        assert one(conn,"SELECT COUNT(*) n FROM artifacts")["n"]==0


def test_worker_renews_each_live_run_without_reviving_expired_or_stale_leases(client):
    from atoms.worker import heartbeat

    runs = []
    for index in range(4):
        project = client.post("/api/v1/projects", json={"client_key":f"lease-project-{index}"}).json()
        assert submit(client, project["id"], request_key=f"lease-run-{index}").status_code == 202
        runs.append(claim("test-leader"))

    now = time.time()
    with transaction(True) as conn:
        execute(conn,"UPDATE runs SET lease_until=:until",until=now+10)
        execute(conn,"UPDATE runs SET lease_until=:until WHERE id=:id",until=now-1,id=runs[1]["id"])
    leases = [(run["id"], run["lease_token"]) for run in runs]
    leases[2] = (runs[2]["id"], "stale-lease-token")
    heartbeat("test-leader", leases)

    with transaction() as conn:
        expiry = [one(conn,"SELECT lease_until FROM runs WHERE id=:id",id=run["id"])["lease_until"] for run in runs]
    assert expiry[0] == expiry[3] and expiry[0] > now+10
    assert expiry[1] == now-1 and expiry[2] == now+10


def test_atomic_commit_rollback(client):
    p=create_project(client)
    assert submit(client,p["id"]).status_code==202
    run=claim("test-leader")
    with transaction(True) as conn:
        execute(conn,"CREATE TRIGGER reject_summary BEFORE INSERT ON messages WHEN NEW.role='assistant' BEGIN SELECT RAISE(ABORT,'test fault'); END")
    try:
        with pytest.raises(Exception):
            commit(run,ARTIFACT,VALIDATION)
        with transaction() as conn:
            assert one(conn,"SELECT COUNT(*) n FROM versions")["n"]==0
            assert one(conn,"SELECT COUNT(*) n FROM artifacts")["n"]==0
            assert one(conn,"SELECT revision FROM projects WHERE id=:id",id=p["id"])["revision"]==0
    finally:
        with transaction(True) as conn:
            execute(conn,"DROP TRIGGER reject_summary")
    fail(run,"TEST_FAILURE","测试注入失败")
    assert client.get("/api/v1/projects/"+p["id"]).json()["active_run_id"] is None


def test_preview_ticket_and_prototype_keys(client):
    p=create_project(client);p,run=complete(client,p)
    vid=p["current_version_id"]
    ticket=client.post("/api/v1/projects/"+p["id"]+"/versions/"+vid+"/preview-ticket",json={}).json()
    assert client.get(ticket["url"]).status_code==403
    response=client.get(ticket["url"],headers={"Sec-Fetch-Dest":"iframe","Sec-Fetch-Site":"same-origin"})
    assert response.status_code==200
    assert "sandbox allow-scripts" in response.headers["content-security-policy"]
    assert ticket["instance_id"] not in response.text # config is Base64, not raw executable text
    assert "{{CONFIG" not in response.text
    assert client.get(ticket["url"]+"tampered",headers={"Sec-Fetch-Dest":"iframe","Sec-Fetch-Site":"same-origin"}).status_code==403
    assert client.patch("/api/v1/projects/"+p["id"]+"/app-state",json={"expected_revision":0,"set":{"__proto__":{"bad":1}}}).status_code==422

def test_manual_source_save_keeps_invalid_files_out_of_version_history(client, monkeypatch):
    import httpx

    p,_=complete(client,create_project(client))
    path=f"/api/v1/projects/{p['id']}/versions/{p['current_version_id']}/source"
    headers={"Idempotency-Key":"manual-source-1"}
    original=httpx.AsyncClient
    candidates=[]

    def validate(request):
        payload=json.loads(request.content)
        assert payload["preview_kind"]=="web"
        files=payload["artifact"]["files"]
        candidates.append(files)
        if files["app.js"]=="const a =":
            return httpx.Response(200,json={"ok":False,"error":"app.js:1:10 Unexpected end of input"})
        return httpx.Response(200,json=VALIDATION)

    monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs:original(transport=httpx.MockTransport(validate)))
    invalid={"expected_revision":p["revision"],"files":{"app.js":"const a ="}}
    failed=client.post(path,json=invalid,headers=headers)
    assert failed.status_code==422
    assert "app.js:1:10" in failed.json()["detail"]["message"]
    versions=f"/api/v1/projects/{p['id']}/versions"
    assert len(client.get(versions).json()["items"])==1

    valid={**invalid,"files":{"app.js":"const a = 2;","styles.css":""}}
    saved=client.post(path,json=valid,headers=headers)
    assert saved.status_code==200,saved.text
    result=saved.json()
    assert result["number"]==2 and result["parent_version_id"]==p["current_version_id"]
    assert result["artifact"]["files"]=={**ARTIFACT["files"],**valid["files"]}
    assert client.get(versions+"/"+p["current_version_id"]).json()["artifact"]==ARTIFACT
    assert client.post(path,json=valid,headers=headers).json()["id"]==result["id"]
    assert client.post(path,json=valid,headers={"Idempotency-Key":"manual-source-2"}).status_code==409
    assert len(candidates)==2
    with transaction() as conn:
        assert one(conn,"SELECT COUNT(*) n FROM model_calls")["n"]==0


def test_manual_source_commit_rechecks_revision_after_compilation(client, monkeypatch):
    import httpx

    p,_=complete(client,create_project(client))
    path=f"/api/v1/projects/{p['id']}/versions/{p['current_version_id']}/source"
    original=httpx.AsyncClient

    def validate(request):
        with transaction(True) as conn:
            execute(conn,"UPDATE projects SET revision=revision+1 WHERE id=:id",id=p["id"])
        return httpx.Response(200,json=VALIDATION)

    monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs:original(transport=httpx.MockTransport(validate)))
    result=client.post(path,json={"expected_revision":p["revision"],"files":{"app.js":"void 1;"}},
                       headers={"Idempotency-Key":"manual-source-3"})
    assert result.status_code==409
    assert result.json()["detail"]["code"]=="revision_conflict"
    assert len(client.get(f"/api/v1/projects/{p['id']}/versions").json()["items"])==1
