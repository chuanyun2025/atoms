import asyncio

from conftest import create_project, submit
from fastapi.testclient import TestClient

from atoms.main import app
from atoms.runtime import worker


def _valid_validation():
    return {
        "ok": True,
        "compiled": {
            "body_html": '<div id="root"></div>',
            "css_base64": "YmxvY2t7fQ==",
            "js_base64": "Y29uc29sZS5sb2coMSk=",
            "digest": "digest-inspector-test",
            "compiler_version": "2",
            "sdk_version": "1",
        },
        "report": {
            "ready": True,
            "acceptance": "startup",
            "sandbox_enabled": True,
        },
    }


def test_published_example_source_is_zero_cost_and_sessionless():
    with TestClient(app, base_url="http://localhost:8080") as anon:
        web_res = anon.get("/api/v1/examples/jinheng-finance/source")
        assert web_res.status_code == 200, web_res.text
        web_body = web_res.json()
        assert web_body["example_id"] == "jinheng-finance"
        assert web_body["schema_version"] == "2"
        assert "src/App.tsx" in web_body["files"]
        assert "src/styles.css" in web_body["files"]

        game_res = anon.get("/api/v1/game-examples/jungle-assault/source")
        assert game_res.status_code == 200, game_res.text
        game_body = game_res.json()
        assert game_body["example_id"] == "jungle-assault"
        assert "src/game/engine.ts" in game_body["files"]

        missing = anon.get("/api/v1/examples/non-existent-demo/source")
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "example_not_found"


def test_run_inspector_exposes_sanitized_plan_repair_validation_and_exact_ledger_totals(client, monkeypatch):
    calls = []

    async def fake_validate(artifact, run_id, preview_kind="web", lightweight_3d=False):
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            return {
                "ok": False,
                "error": "Type error in src/App.tsx",
                "diagnostic": {
                    "code": "COMPILE_ERROR",
                    "file": "src/App.tsx",
                    "line": 12,
                    "column": 5,
                    "subject": "Cannot find name 'missingValue'.",
                },
            }
        return _valid_validation()

    monkeypatch.setattr(worker, "validate_artifact", fake_validate)

    proj = create_project(client)
    run_resp = submit(client, proj["id"], prompt="创建一个带筛选的项目进度看板", request_key="inspector-run-key-1")
    assert run_resp.status_code == 202, run_resp.text
    rid = run_resp.json()["id"]

    claimed = worker.claim("test-leader")
    assert claimed and claimed["id"] == rid
    asyncio.run(worker.execute_run(claimed))

    inspector_resp = client.get(f"/api/v1/runs/{rid}/inspector")
    assert inspector_resp.status_code == 200, inspector_resp.text
    data = inspector_resp.json()

    assert data["run_id"] == rid
    assert data["status"] == "succeeded"
    assert data["version_number"] == 1
    assert data["task_plan"] is not None
    assert data["task_plan"]["experience"] == "website"
    assert data["task_plan"]["rendering"] == "dom"
    assert "specialist_brief" not in data["task_plan"]

    assert data["validation"]["ready"] is True
    assert data["validation"]["acceptance"] == "startup"
    assert data["validation"]["compiler_version"] == "2"
    assert data["validation"]["file_count"] >= 3

    assert len(data["repairs"]) == 1
    repair = data["repairs"][0]
    assert repair["round"] == 1
    assert repair["diagnostic"]["code"] == "COMPILE_ERROR"
    assert repair["diagnostic"]["file"] == "src/App.tsx"
    assert repair["diagnostic"]["line"] == 12
    assert "修正" in repair["strategy"]

    wallet = client.get("/api/v1/wallet").json()
    txs = client.get("/api/v1/wallet/transactions").json()["items"]
    ledger_spent = sum(-item["amount_units"] for item in txs if item["kind"] == "consumption")
    assert data["billing"]["total_settled_units"] == ledger_spent
    assert data["billing"]["total_settled_credits"] == wallet["spent"]
    assert len(data["billing"]["calls"]) == 2

    with TestClient(app, base_url="http://localhost:8080") as stranger:
        auth = stranger.post(
            "/api/v1/session", json={}, headers={"Origin": "http://localhost:8080", "X-App-Request": "atoms"}
        ).json()
        stranger.headers.update(
            {"Origin": "http://localhost:8080", "X-App-Request": "atoms", "X-CSRF-Token": auth["csrf_token"]}
        )
        denied = stranger.get(f"/api/v1/runs/{rid}/inspector")
        assert denied.status_code == 404
        assert denied.json()["detail"]["code"] == "run_not_found"


def test_run_inspector_reports_settled_video_media_consumption_credits(client, funded_video_wallet):
    from atoms.billing import media_credits
    from atoms.core.db import execute, one, transaction

    with transaction(True) as conn:
        execute(
            conn,
            "UPDATE worker_status SET heartbeat_at=:now, lease_until=:u, video_configured=1 WHERE id=1",
            now=1999999999,
            u=1999999999,
        )
    vproj = client.post(
        "/api/v1/projects", json={"client_key": "vid-inspector-01", "title": "海浪视频", "kind": "video"}
    ).json()
    res = client.post(
        f"/api/v1/projects/{vproj['id']}/runs",
        json={
            "prompt": "清晨海浪",
            "expected_revision": 0,
            "base_version_id": None,
            "video": {"duration": 5, "audio": True},
        },
        headers={"Idempotency-Key": "vid-inspector-req-1"},
    )
    assert res.status_code == 202, res.text
    rid = res.json()["id"]

    with transaction(True) as conn:
        call_row = one(conn, "SELECT id, estimated_provider_credits FROM media_calls WHERE run_id=:id", id=rid)
        media_credits.settle(conn, call_row["id"], int(call_row["estimated_provider_credits"]))

    wallet = client.get("/api/v1/wallet").json()
    inspector = client.get(f"/api/v1/runs/{rid}/inspector").json()
    assert len(inspector["billing"]["media_calls"]) == 1
    assert inspector["billing"]["media_calls"][0]["settled_units"] == 100_000_000
    assert inspector["billing"]["total_settled_credits"] == wallet["spent"] == "100"
