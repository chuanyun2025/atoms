"""Tests for daily public budget circuit breaker and visitor passcodes (FR-025 / FR-026 / NFR-011)."""

import asyncio
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from conftest import create_project, submit
from fastapi.testclient import TestClient
from test_retry import validator
from test_workflow import VALIDATION

from atoms import ops
from atoms.billing.credits import CreditError, reserve_call, settle_call, start_call
from atoms.billing.passcodes import hash_passcode
from atoms.core.config import settings
from atoms.core.db import execute, one, transaction
from atoms.main import app
from atoms.runtime import worker


def _enable_worker():
    now = time.time()
    with transaction(True) as conn:
        execute(
            conn,
            """UPDATE worker_status SET heartbeat_at=:now, lease_until=:until,
            model_configured=1, video_configured=1, text_model='deepseek-flash' WHERE id=1""",
            now=now,
            until=now + 60,
        )


def test_public_daily_budget_atomic_concurrency_and_graceful_degradation(client, monkeypatch):
    """AT-021 & NFR-011: Concurrent reservations never breach public daily cap; read/export remain usable."""
    cfg = settings()
    _enable_worker()
    validator(monkeypatch, [VALIDATION])

    # Deliver an existing project version first (fixture consumes 1 call -> 1 credit = 1,000,000 units).
    proj_existing = create_project(client)
    res_ok = submit(client, proj_existing["id"], "做个极简计数器", request_key="init-ok-key")
    assert res_ok.status_code == 202
    run_ok = worker.claim("test-leader")
    asyncio.run(worker.execute_run(run_ok))

    # Now enable public daily budget at 2 credits (2,000,000 units) -> remaining today is 1 credit (1,000,000 units)!
    monkeypatch.setattr(cfg, "public_budget_enabled", True)
    monkeypatch.setattr(cfg, "public_daily_budget_credits", Decimal("2"))

    # Spawn 6 concurrent runs and attempt to reserve 1 credit each in parallel threads -> at most 1 can succeed!
    runs = []
    for idx in range(6):
        p = client.post("/api/v1/projects", json={"client_key": f"conc-proj-{idx:02d}", "title": f"并发{idx}"}).json()
        r = submit(client, p["id"], "并发测试", request_key=f"conc-req-key-{idx}")
        assert r.status_code == 202
        with transaction(True) as conn:
            now = time.time()
            execute(
                conn,
                "UPDATE runs SET status='running', lease_token='tok', lease_until=:u WHERE id=:id",
                u=now + 60,
                id=r.json()["id"],
            )
            runs.append(one(conn, "SELECT * FROM runs WHERE id=:id", id=r.json()["id"]))

    def attempt_reserve(run_row):
        try:
            # Minimum required = 1 credit (1,000,000 units) -> only 1 of 6 can succeed!
            return reserve_call(run_row, 1, 1200, 300)
        except CreditError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(attempt_reserve, runs))

    reserved = [item for item in outcomes if isinstance(item, dict)]
    rejected = [item for item in outcomes if item == "PUBLIC_DAILY_BUDGET_REACHED"]
    assert len(reserved) == 1
    assert len(rejected) == 5
    # Settled (1,000,000) + held (reserved[0]['reserved_units']) never breaches 2,000,000 units!
    assert 1_000_000 + reserved[0]["reserved_units"] <= 2_000_000

    # New anonymous run submission immediately gets 429 PUBLIC_DAILY_BUDGET_REACHED without creating a dangling run.
    blocked_proj = client.post("/api/v1/projects", json={"client_key": "blocked-proj-01", "title": "被熔断"}).json()
    blocked_res = submit(client, blocked_proj["id"], "新请求", request_key="blocked-req-key-01")
    assert blocked_res.status_code == 429
    assert blocked_res.json()["detail"]["code"] == "PUBLIC_DAILY_BUDGET_REACHED"
    with transaction() as conn:
        assert one(conn, "SELECT COUNT(*) AS n FROM runs WHERE project_id=:pid", pid=blocked_proj["id"])["n"] == 0

    # Non-paid features remain 100% functional during meltdown: capabilities, gallery ticket, local source edit & ZIP export!
    cap = client.get("/api/v1/capabilities").json()
    assert cap["guardrails"]["daily_budget_reached"] is True
    assert client.get("/api/v1/examples/jinheng-finance/preview-ticket").status_code == 200
    proj_state = client.get(f"/api/v1/projects/{proj_existing['id']}").json()
    vid = proj_state["current_version_id"]
    assert vid is not None
    export_res = client.get(f"/api/v1/projects/{proj_existing['id']}/versions/{vid}/export")
    assert export_res.status_code == 200
    assert export_res.headers["content-type"] == "application/zip"


def test_passcode_cli_redemption_video_unlock_and_revocation(client, monkeypatch, capsys):
    """AT-022 & FR-026: Passcode unlocks melted-down public budget and video; exhaustion or revocation blocks immediately."""
    cfg = settings()
    monkeypatch.setattr(cfg, "public_budget_enabled", True)
    monkeypatch.setattr(cfg, "public_daily_budget_credits", Decimal("0"))  # Public pool melted down
    monkeypatch.setattr(cfg, "public_video_enabled", False)  # Public video disabled
    _enable_worker()

    # Create passcode via CLI `ops.main`
    monkeypatch.setattr(
        sys,
        "argv",
        ["ops", "passcode-create", "--label", "面试官体验码", "--credits", "150.01", "--max-visitors", "1"],
    )
    ops.main()
    created = json.loads(capsys.readouterr().out.strip())
    assert created["budget"] == "150.01" and created["budget_units"] == 150_010_000
    raw_code = created["code"]
    passcode_id = created["id"]

    # Plaintext code is never stored in SQLite
    with transaction() as conn:
        row = one(conn, "SELECT * FROM passcodes WHERE id=:id", id=passcode_id)
        assert row["code_hash"] == hash_passcode(raw_code)
        assert raw_code not in json.dumps(dict(row))

    # Public video submission is blocked before redeeming passcode
    vproj = client.post(
        "/api/v1/projects", json={"client_key": "vid-guard-01", "title": "视频", "kind": "video"}
    ).json()
    blocked_vid = client.post(
        f"/api/v1/projects/{vproj['id']}/runs",
        json={
            "prompt": "海浪",
            "expected_revision": 0,
            "base_version_id": None,
            "video": {"duration": 4, "audio": True},
        },
        headers={"Idempotency-Key": "vid-blocked-key-1"},
    )
    assert blocked_vid.status_code == 403
    assert blocked_vid.json()["detail"]["code"] == "PUBLIC_VIDEO_DISABLED"

    # Redeem passcode on primary client
    redeem_res = client.post("/api/v1/wallet/passcode", json={"code": raw_code.lower()})
    assert redeem_res.status_code == 200
    guard = redeem_res.json()["guardrails"]
    assert guard["daily_budget_reached"] is False
    assert guard["video_unlocked"] is True
    assert guard["passcode"]["label"] == "面试官体验码"
    assert guard["passcode"]["remaining"] == "150.01"
    assert redeem_res.json()["available"] == "150.01"

    # Second visitor cannot exceed max_visitors=1
    with TestClient(app, base_url="http://localhost:8080") as second:
        auth2 = second.post(
            "/api/v1/session", json={}, headers={"Origin": "http://localhost:8080", "X-App-Request": "atoms"}
        ).json()
        second.headers.update(
            {"Origin": "http://localhost:8080", "X-App-Request": "atoms", "X-CSRF-Token": auth2["csrf_token"]}
        )
        denied = second.post("/api/v1/wallet/passcode", json={"code": raw_code})
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "passcode_visitor_limit"

    # Primary visitor can now submit both web and video runs despite public meltdown!
    wproj = create_project(client)
    assert submit(client, wproj["id"], "生成应用", request_key="passcode-web-key-1").status_code == 202
    wrun = worker.claim("test-leader")
    call = reserve_call(wrun, 1, 1000, 200)
    assert call["passcode_id"] == passcode_id
    start_call(call)
    settle_call(call, 1000, 100, "req-passcode")

    assert (
        client.post(
            f"/api/v1/projects/{vproj['id']}/runs",
            json={
                "prompt": "海浪",
                "expected_revision": 0,
                "base_version_id": None,
                "video": {"duration": 4, "audio": True},
            },
            headers={"Idempotency-Key": "vid-allowed-key-2"},
        ).status_code
        == 202
    )

    # List passcodes via CLI and verify spent + held are tracked
    monkeypatch.setattr(sys, "argv", ["ops", "passcode-list"])
    ops.main()
    listed = json.loads(capsys.readouterr().out)["items"]
    assert listed[0]["id"] == passcode_id
    assert listed[0]["budget"] == "150.01"
    assert Decimal(listed[0]["spent"]) > 0
    assert Decimal(listed[0]["held"]) == 100

    # Revoke passcode via CLI -> next run submission is immediately blocked!
    monkeypatch.setattr(sys, "argv", ["ops", "passcode-revoke", passcode_id])
    ops.main()
    capsys.readouterr()

    wproj2 = client.post("/api/v1/projects", json={"client_key": "web-after-revoke", "title": "吊销后"}).json()
    after_revoke = submit(client, wproj2["id"], "再试一次", request_key="passcode-after-revoke-1")
    assert after_revoke.status_code == 403
    assert after_revoke.json()["detail"]["code"] == "PASSCODE_REVOKED"

    # Detaching revoked passcode returns visitor to public pool (which is at 0 budget -> 429 PUBLIC_DAILY_BUDGET_REACHED)
    detached = client.post("/api/v1/wallet/passcode/detach", json={})
    assert detached.status_code == 200
    assert detached.json()["guardrails"]["passcode"] is None
    after_detach = submit(client, wproj2["id"], "再试一次", request_key="passcode-after-detach-1")
    assert after_detach.status_code == 429
    assert after_detach.json()["detail"]["code"] == "PUBLIC_DAILY_BUDGET_REACHED"


def test_non_exempt_passcode_and_cross_day_holds_count_toward_public_budget(client):
    from atoms.billing.passcodes import create_passcode, day_window, public_daily_usage_units, redeem_passcode

    _enable_worker()
    now_ts = time.time()
    start_ts, _, _ = day_window(now_ts)

    with transaction(True) as conn:
        non_exempt = create_passcode(
            conn,
            label="共享公共池口令",
            credits=50,
            bypass_daily_budget=False,
            allow_video=False,
        )
        redeem_passcode(conn, client.get("/api/v1/wallet").json()["visitor_id"], non_exempt["code"], "127.0.0.1")

    proj = create_project(client)
    assert submit(client, proj["id"], "测试非豁免口令", request_key="non-exempt-key-1").status_code == 202
    run_row = worker.claim("test-leader")
    call = reserve_call(run_row, 1, 1000, 200)
    assert call["passcode_id"] == non_exempt["id"]

    with transaction() as conn:
        used_while_held, _, _ = public_daily_usage_units(conn, now_ts)
    assert used_while_held == call["reserved_units"]

    start_call(call)
    settle_call(call, 1000, 100, "req-non-exempt")
    expected_settled = 1_000_000
    with transaction() as conn:
        used_after_settle, _, _ = public_daily_usage_units(conn, now_ts)
    assert used_after_settle == expected_settled

    # Simulate an active hold created 30 seconds before today's midnight boundary -> must still count today!
    proj2 = client.post("/api/v1/projects", json={"client_key": "cross-day-proj", "title": "跨日冻结"}).json()
    with transaction(True) as conn:
        execute(conn, "UPDATE visitor_passcodes SET active=0")
    assert submit(client, proj2["id"], "跨日任务", request_key="cross-day-key-1").status_code == 202
    with transaction(True) as conn:
        rid2 = one(conn, "SELECT id FROM runs WHERE project_id=:pid", pid=proj2["id"])["id"]
        execute(
            conn,
            "UPDATE runs SET status='running', lease_token='cross', lease_until=:u WHERE id=:id",
            u=now_ts + 120,
            id=rid2,
        )
        run2 = one(conn, "SELECT * FROM runs WHERE id=:id", id=rid2)
    cross_call = reserve_call(run2, 1, 500, 100)
    with transaction(True) as conn:
        execute(
            conn, "UPDATE model_calls SET created_at=:before WHERE id=:id", before=start_ts - 30, id=cross_call["id"]
        )
        used_with_cross_day, _, _ = public_daily_usage_units(conn, start_ts + 10)
    assert used_with_cross_day >= cross_call["reserved_units"]


def test_invalid_passcode_attempts_persist_rate_limit_and_empty_env_preserves_test_video(client, monkeypatch):
    from atoms.core.config import Settings

    cfg = settings()
    monkeypatch.setattr(cfg, "rate_limit_enabled", True)

    for idx in range(10):
        res = client.post("/api/v1/wallet/passcode", json={"code": f"WRONG-CODE-{idx:02d}"})
        assert res.status_code == 404
        assert res.json()["detail"]["code"] == "passcode_not_found"

    eleventh = client.post("/api/v1/wallet/passcode", json={"code": "WRONG-CODE-11"})
    assert eleventh.status_code == 429
    assert eleventh.json()["detail"]["code"] == "rate_limited"

    e2e_settings = Settings(
        app_env="test",
        session_secret="s" * 32,
        service_token="t" * 24,
        public_video_enabled="",
        public_budget_enabled="",
        rate_limit_enabled="",
    )
    assert e2e_settings.allows_public_video() is True
    assert e2e_settings.should_enforce_public_budget() is False
    assert e2e_settings.should_rate_limit() is False

    dev_settings = Settings(
        app_env="development",
        session_secret="s" * 32,
        service_token="t" * 24,
        public_video_enabled="",
    )
    assert dev_settings.allows_public_video() is False
