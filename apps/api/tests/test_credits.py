import asyncio
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from alembic import command
from alembic.config import Config
from conftest import create_project, submit
from fastapi.testclient import TestClient

from atoms import ops
from atoms.billing.credits import CreditError, finish_unbilled, reserve_call, settle_call, start_call
from atoms.core.config import settings
from atoms.core.db import execute, one, transaction
from atoms.main import app
from atoms.runtime.model import ModelError
from atoms.runtime.worker import acquire_leader, claim, paid_generate, recover_expired
from atoms.skills import skill_for


def running(client, project=None, key="credits-request-key"):
    p = project or create_project(client)
    response = submit(client, p["id"], request_key=key)
    assert response.status_code == 202, response.text
    return claim("test-leader")


def test_welcome_only_once_and_identity(client):
    first = client.get("/api/v1/wallet").json()
    for _ in range(3):
        session = client.post("/api/v1/session", json={}).json()
        assert session["visitor_id"] == first["visitor_id"]
    second = client.get("/api/v1/wallet").json()
    assert first == second and first["balance"] == "50" and first["welcome_credits"] == 50
    ledger = client.get("/api/v1/wallet/transactions").json()["items"]
    assert len(ledger) == 1 and ledger[0]["kind"] == "welcome"
    with TestClient(app, base_url="http://localhost:8080") as other:
        other.post("/api/v1/session", json={}, headers={"Origin": "http://localhost:8080", "X-App-Request": "atoms"})
        assert other.get("/api/v1/wallet").json()["visitor_id"] != first["visitor_id"]
        assert other.get("/api/v1/wallet/transactions").json()["items"][0]["id"] != ledger[0]["id"]


def test_exact_prices_and_idempotent_settlement(client):
    run = running(client)
    call = reserve_call(run, 1, 200_000, 200_000)
    start_call(call)
    assert settle_call(call, 200_000, 200_000) == "20"
    assert settle_call(call, 200_000, 200_000) == "20"
    result = client.get("/api/v1/wallet").json()
    assert result["balance"] == "30" and result["spent"] == "20" and result["held"] == "0"
    # Sub-1 credit usage rounds up to 1 credit (进一法)
    call2 = reserve_call(run, 2, 10, 10)
    start_call(call2)
    assert settle_call(call2, 1, 1) == "1"
    assert client.get("/api/v1/wallet").json()["balance"] == "29"
    # Fractional > 1 credit (1.000080 credits) rounds up to 2 credits
    call3 = reserve_call(run, 3, 50_000, 100)
    start_call(call3)
    assert settle_call(call3, 50_000, 1) == "2"
    assert client.get("/api/v1/wallet").json()["balance"] == "27"
    # Zero token usage charges 0 credits
    call4 = reserve_call(run, 4, 10, 10)
    start_call(call4)
    assert settle_call(call4, 0, 0) == "0"
    assert client.get("/api/v1/wallet").json()["balance"] == "27"
    with pytest.raises(CreditError):
        settle_call(call2, 2, 1)


def test_native_limit_and_low_balance_only_cap(client):
    run = running(client)
    call = reserve_call(run, 1, 2000, 393216)
    assert call["output_limit"] == 393216
    assert call["reserved_units"] == 32_000_000
    finish_unbilled(call, "TEST_REJECTED")
    with transaction(True) as conn:
        execute(conn, "UPDATE credit_wallets SET balance_units=2000000 WHERE visitor_id=:id", id=run["owner_id"])
    low = reserve_call(run, 2, 500, 393216)
    assert low["output_limit"] == 24875
    assert low["reserved_units"] == 2_000_000
    finish_unbilled(low, "TEST_REJECTED")
    with transaction(True) as conn:
        execute(conn, "UPDATE credit_wallets SET balance_units=500000 WHERE visitor_id=:id", id=run["owner_id"])
    with pytest.raises(CreditError):
        reserve_call(run, 3, 500, 393216)
    p2 = client.post("/api/v1/projects", json={"client_key": "second-empty-project", "title": "只读保留"}).json()
    assert submit(client, p2["id"], request_key="no-credits-request").status_code == 402


def test_concurrent_authorizations_cannot_overdraw(client):
    first = running(client)
    p2 = client.post("/api/v1/projects", json={"client_key": "parallel-project", "title": "并发预算"}).json()
    second = running(client, p2, "parallel-request-key")

    def reserve(run):
        try:
            return reserve_call(run, 1, 1000, 10_000_000)
        except CreditError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        calls = list(executor.map(reserve, [first, second]))
    assert sum(call is not None for call in calls) == 1
    wallet = client.get("/api/v1/wallet").json()
    assert 0 <= wallet["held_units"] <= wallet["balance_units"]


def test_crash_holds_then_reconciliation(client):
    run = running(client)
    call = reserve_call(run, 1, 2000, 393216)
    start_call(call)
    with transaction(True) as conn:
        execute(conn, "UPDATE runs SET lease_until=:now WHERE id=:id", id=run["id"], now=time.time() - 1)
    recover_expired()
    with transaction() as conn:
        assert one(conn, "SELECT status FROM model_calls WHERE id=:id", id=call["id"])["status"] == "uncertain"
    assert client.get("/api/v1/wallet").json()["held_units"] == call["reserved_units"]
    settle_call(call, 1200, 400, operator=True)
    assert client.get("/api/v1/wallet").json()["held"] == "0"
    assert client.get("/api/v1/wallet").json()["spent"] == "1"


def test_excess_usage_stays_pending_without_negative_wallet(client):
    run = running(client)
    call = reserve_call(run, 1, 100, 100)
    start_call(call)
    with pytest.raises(CreditError):
        settle_call(call, 1000, 1000)
    wallet = client.get("/api/v1/wallet").json()
    assert wallet["balance"] == "50" and wallet["held_units"] == call["reserved_units"]
    finish_unbilled(call, "OPERATOR_CONFIRMED_NO_CHARGE", operator=True)
    finish_unbilled(call, "OPERATOR_CONFIRMED_NO_CHARGE", operator=True)
    assert client.get("/api/v1/wallet").json()["available"] == "50"


@pytest.mark.parametrize(
    "scenario",
    ["success", "length", "protocol_with_usage", "network_with_usage", "missing", "timeout", "connect", "rejected"],
)
def test_worker_usage_failure_and_holds(client, monkeypatch, scenario):
    run = running(client)
    original = httpx.AsyncClient
    config = settings()
    monkeypatch.setattr(config, "test_fixture", False)

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"max_output_tokens": 393216})
        assert json.loads(request.content)["max_output_tokens"] == 393216
        if scenario == "timeout":
            raise httpx.ReadTimeout("test", request=request)
        if scenario == "connect":
            raise httpx.ConnectError("test", request=request)
        if scenario == "rejected":
            return httpx.Response(
                401, json={"error": {"code": "MODEL_AUTH", "message": "authentication failed", "uncertain": False}}
            )
        usage = {"input_tokens": 1200, "output_tokens": 400}
        if scenario == "length":
            return httpx.Response(
                502, json={"error": {"code": "MODEL_TRUNCATED", "message": "output truncated", "usage": usage}}
            )
        if scenario == "protocol_with_usage":
            return httpx.Response(
                502,
                json={
                    "error": {
                        "code": "MODEL_PROTOCOL",
                        "message": "malformed provider response",
                        "usage": usage,
                        "uncertain": False,
                    }
                },
            )
        if scenario == "network_with_usage":
            return httpx.Response(
                502,
                json={
                    "error": {
                        "code": "MODEL_NETWORK",
                        "message": "stream interrupted after usage",
                        "usage": usage,
                        "uncertain": False,
                    }
                },
            )
        result = {"content": "{}"}
        if scenario != "missing":
            result["usage"] = usage
        return httpx.Response(200, json=result)

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(**{**kwargs, "transport": httpx.MockTransport(handler)})
    )
    generation = paid_generate(run, {"request": "计数器"}, None, skill=skill_for("web"))
    if scenario == "success":
        assert asyncio.run(generation) == "{}"
    else:
        with pytest.raises(ModelError):
            asyncio.run(generation)
    wallet = client.get("/api/v1/wallet").json()
    if scenario in {"success", "length", "protocol_with_usage", "network_with_usage"}:
        assert wallet["spent"] == "1" and wallet["held"] == "0"
    elif scenario in {"timeout", "missing"}:
        assert wallet["spent"] == "0" and wallet["held_units"] > 0
    else:
        assert wallet["balance"] == "50" and wallet["held"] == "0"


def test_migration_gifts_existing_visitors_once(tmp_path, monkeypatch):
    # Build the historical schema in isolation; never downgrade a live ledger.
    from sqlalchemy import create_engine, event

    from atoms.core import db

    historical = create_engine("sqlite:///" + str(tmp_path / "historical.db").replace("\\", "/"))
    event.listen(historical, "connect", db.setup_connection)
    event.listen(historical, "begin", db.begin_connection)
    monkeypatch.setattr(db, "engine", historical)
    command.upgrade(Config("alembic.ini"), "0001")
    try:
        with transaction(True) as conn:
            execute(
                conn,
                "INSERT INTO visitors(id,token_hash,created_at,expires_at) VALUES('existing-user','hash',1,9999999999)",
            )
        command.upgrade(Config("alembic.ini"), "head")
        command.upgrade(Config("alembic.ini"), "head")
        with transaction() as conn:
            assert (
                one(conn, "SELECT balance_units FROM credit_wallets WHERE visitor_id='existing-user'")["balance_units"]
                == 500_000_000
            )
            assert one(conn, "SELECT COUNT(*) n FROM credit_ledger WHERE visitor_id='existing-user'")["n"] == 1
    finally:
        historical.dispose()


def test_upgrade_reconciles_legacy_model_holds_and_reports_exact_debits(tmp_path, monkeypatch):
    from atoms.core import db

    historical = db.make_engine("sqlite:///" + (tmp_path / "legacy-holds.db").as_posix())
    monkeypatch.setattr(db, "engine", historical)
    migration = Config("alembic.ini")
    command.upgrade(migration, ops.PASSCODE_SCHEMA)
    try:
        acquire_leader("test-leader")
        headers = {"Origin": "http://localhost:8080", "X-App-Request": "atoms"}
        with TestClient(app, base_url="http://localhost:8080", headers=headers) as client:
            auth = client.post("/api/v1/session", json={}).raise_for_status().json()
            client.headers["X-CSRF-Token"] = auth["csrf_token"]
            run = running(client)
            with transaction(True) as conn:
                for attempt in (1, 2):
                    execute(
                        conn,
                        """INSERT INTO model_calls(id,visitor_id,run_id,attempt,lease_token,status,reserved_units,
                        input_ceiling,output_limit,created_at)
                        VALUES(:id,:owner,:run,:attempt,:lease,'uncertain',56000,1200,400,:now)""",
                        id=f"legacy-{attempt}",
                        owner=run["owner_id"],
                        run=run["id"],
                        attempt=attempt,
                        lease=run["lease_token"],
                        now=time.time(),
                    )
                execute(conn, "UPDATE credit_wallets SET held_units=112000 WHERE visitor_id=:id", id=run["owner_id"])

            command.upgrade(migration, "head")
            ledger_url = "/api/v1/wallet/transactions"
            pending = client.get(ledger_url).json()["pending"]
            assert [item["reserved"] for item in pending] == ["0.056", "0.056"]
            for item in pending:
                monkeypatch.setattr(
                    sys,
                    "argv",
                    ["ops", "credits-reconcile", item["id"], "--input-tokens", "1200", "--output-tokens", "400"],
                )
                ops.main()
                assert settle_call(item, 1200, 400, operator=True) == "0.056"

            wallet = client.get("/api/v1/wallet").json()
            assert (wallet["balance"], wallet["available"], wallet["spent"], wallet["held"]) == (
                "49.888",
                "49.888",
                "0.112",
                "0",
            )
            ledger = client.get(ledger_url).json()
            assert ledger["pending"] == []
            assert [item["amount"] for item in ledger["items"] if item["kind"] == "consumption"] == ["-0.056", "-0.056"]
            billing = client.get(f"/api/v1/runs/{run['id']}/inspector").json()["billing"]
            assert [call["settled_credits"] for call in billing["calls"]] == ["0.056", "0.056"]
            assert billing["total_settled_credits"] == "0.112"
    finally:
        historical.dispose()
