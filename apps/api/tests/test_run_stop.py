import asyncio
import threading

import pytest
from conftest import create_project, submit
from fastapi.testclient import TestClient
from test_workflow import ARTIFACT, VALIDATION, complete

from atoms.billing.credits import CreditError, reserve_call, settle_call, start_call
from atoms.core.db import compact, one, transaction
from atoms.runtime import worker
from atoms.runtime.model import ModelResult, Prepared, Usage


def test_stop_pending_run_is_owner_only_and_idempotent(client):
    project = create_project(client)
    rid = submit(client, project["id"]).json()["id"]
    path = "/api/v1/runs/" + rid + "/stop"
    with TestClient(client.app, base_url="http://localhost:8080") as other:
        other.headers.update({"Origin": "http://localhost:8080", "X-App-Request": "atoms"})
        other.headers["X-CSRF-Token"] = other.post("/api/v1/session", json={}).json()["csrf_token"]
        assert other.post(path, json={}).status_code == 404
    assert client.post(path, json={}, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    stopped = client.post(path, json={}).json()
    assert stopped["status"] == "interrupted"
    assert stopped["error_code"] == "USER_STOPPED"
    assert stopped["model_calls"] == 0
    assert client.post(path, json={}).json() == stopped
    assert worker.claim("test-leader") is None
    assert client.get("/api/v1/projects/" + project["id"]).json()["active_run_id"] is None
    messages = client.get("/api/v1/projects/" + project["id"] + "/messages").json()["items"]
    assert [message["role"] for message in messages] == ["user", "assistant"]


def test_stop_running_run_preserves_draft_and_blocks_late_delivery(client):
    project, previous = complete(client, create_project(client))
    request = submit(
        client, project["id"], "调整计数器", project["revision"], project["current_version_id"], "edit-to-stop"
    )
    assert request.status_code == 202
    run = worker.claim("test-leader")
    worker.keep_candidate(run, compact(ARTIFACT), "核心操作尚未通过", 1)
    worker.publish_source(run, ARTIFACT)
    worker.publish_preview(run, VALIDATION["compiled"])
    call = reserve_call(run, 1, 2000, 3000)
    start_call(call)

    path = "/api/v1/runs/" + run["id"]
    assert client.post(path + "/stop", json={}).json()["error_code"] == "USER_STOPPED"
    assert worker.user_stopped_runs([run["id"], previous["id"]]) == {run["id"]}
    assert client.get(path + "/source").json()["files"] == ARTIFACT["files"]
    ticket = client.post(path + "/preview-ticket", json={}).json()
    assert (
        client.get(ticket["url"], headers={"Sec-Fetch-Dest": "iframe", "Sec-Fetch-Site": "same-origin"}).status_code
        == 200
    )
    with pytest.raises(worker.LeaseLost):
        worker.commit(run, ARTIFACT, VALIDATION)
    assert client.get("/api/v1/projects/" + project["id"]).json()["current_version_id"] == project["current_version_id"]
    assert client.post("/api/v1/runs/" + previous["id"] + "/stop", json={}).json()["status"] == "succeeded"
    with transaction() as conn:
        assert one(conn, "SELECT status FROM model_calls WHERE id=:id", id=call["id"])["status"] == "uncertain"
        assert one(conn, "SELECT run_id FROM run_candidates WHERE run_id=:id", id=run["id"])


@pytest.mark.parametrize("cancel_worker", [False, True])
def test_stop_between_reservation_and_dispatch_releases_hold(client, monkeypatch, cancel_worker):
    project = create_project(client)
    assert submit(client, project["id"]).status_code == 202
    run = worker.claim("test-leader")
    reserved = threading.Event()
    resume_worker = threading.Event()

    def pause_after_reservation(*args):
        call = reserve_call(*args)
        reserved.set()
        assert resume_worker.wait(5)
        return call

    async def provider_must_not_run(*args, **kwargs):
        pytest.fail("A task stopped before dispatch reached the provider")

    monkeypatch.setattr(worker, "reserve_call", pause_after_reservation)
    monkeypatch.setattr(worker, "generate", provider_must_not_run)

    async def check():
        task = asyncio.create_task(worker.paid_request(run, 1, Prepared([], 2000, 3000)))
        try:
            assert await asyncio.to_thread(reserved.wait, 5)
            stopped = client.post("/api/v1/runs/" + run["id"] + "/stop", json={}).json()
            assert stopped["status"] == "interrupted" and stopped["model_calls"] == 0
            if cancel_worker:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                resume_worker.set()
                with pytest.raises(CreditError) as error:
                    await task
                assert error.value.code == "CALL_LEASE_LOST"
        finally:
            resume_worker.set()

    asyncio.run(check())
    with transaction() as conn:
        assert one(conn, "SELECT status FROM model_calls WHERE run_id=:id", id=run["id"])["status"] == "released"
    wallet = client.get("/api/v1/wallet").json()
    assert wallet["held_units"] == 0 and wallet["spent"] == "0.000000"


def test_cancel_as_reservation_returns_skips_start_call_and_releases_hold(client, monkeypatch):
    project = create_project(client)
    assert submit(client, project["id"]).status_code == 202
    run = worker.claim("test-leader")
    start_calls = []
    provider_calls = []
    original_start_call = worker.start_call
    loop_holder = {}

    def cancel_on_reserve_return(*args):
        call = reserve_call(*args)
        loop_holder["loop"].call_soon_threadsafe(loop_holder["task"].cancel)
        return call

    def tracked_start_call(call):
        start_calls.append(call["id"])
        return original_start_call(call)

    async def provider_must_not_run(*args, **kwargs):
        provider_calls.append(1)
        pytest.fail("A cancelled pre-start call must not reach the provider")

    monkeypatch.setattr(worker, "reserve_call", cancel_on_reserve_return)
    monkeypatch.setattr(worker, "start_call", tracked_start_call)
    monkeypatch.setattr(worker, "generate", provider_must_not_run)

    async def check():
        loop_holder["loop"] = asyncio.get_running_loop()
        task = asyncio.create_task(worker.paid_request(run, 1, Prepared([], 2000, 3000)))
        loop_holder["task"] = task
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(check())
    assert start_calls == [] and provider_calls == []
    with transaction() as conn:
        call = one(conn, "SELECT status, dispatch_pending FROM model_calls WHERE run_id=:id", id=run["id"])
        assert call == {"status": "in_flight", "dispatch_pending": 1}

    stopped = client.post("/api/v1/runs/" + run["id"] + "/stop", json={}).json()
    assert stopped["status"] == "interrupted" and stopped["model_calls"] == 0
    with transaction() as conn:
        assert one(conn, "SELECT status FROM model_calls WHERE run_id=:id", id=run["id"])["status"] == "released"
    wallet = client.get("/api/v1/wallet").json()
    assert wallet["held_units"] == 0 and wallet["spent"] == "0.000000"


def test_cancel_immediately_after_sync_start_call_marks_interrupted(client, monkeypatch):
    project = create_project(client)
    assert submit(client, project["id"]).status_code == 202
    run = worker.claim("test-leader")
    original_start_call = worker.start_call
    task_holder = {}

    def start_then_cancel(call):
        original_start_call(call)
        task_holder["task"].cancel()

    async def yielding_generate(*args, **kwargs):
        await asyncio.sleep(1)
        return ModelResult("{}", Usage(1, 1, "unused"))

    monkeypatch.setattr(worker, "start_call", start_then_cancel)
    monkeypatch.setattr(worker, "generate", yielding_generate)

    async def check():
        task = asyncio.create_task(worker.paid_request(run, 1, Prepared([], 2000, 3000)))
        task_holder["task"] = task
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(check())
    with transaction() as conn:
        call = one(conn, "SELECT status, dispatch_pending, error_code FROM model_calls WHERE run_id=:id", id=run["id"])
        assert call == {"status": "uncertain", "dispatch_pending": 0, "error_code": "CALL_INTERRUPTED"}


def test_stop_during_settlement_preserves_known_usage(client, monkeypatch):
    project = create_project(client)
    assert submit(client, project["id"]).status_code == 202
    run = worker.claim("test-leader")
    settling = threading.Event()
    resume_settlement = threading.Event()

    async def generate(*args, **kwargs):
        return ModelResult("{}", Usage(1, 1, "known-usage"))

    def pause_settlement(*args):
        settling.set()
        assert resume_settlement.wait(5)
        return settle_call(*args)

    monkeypatch.setattr(worker, "generate", generate)
    monkeypatch.setattr(worker, "settle_call", pause_settlement)

    async def check():
        task = asyncio.create_task(worker.paid_request(run, 1, Prepared([], 2000, 3000)))
        try:
            assert await asyncio.to_thread(settling.wait, 5)
            stopped = client.post("/api/v1/runs/" + run["id"] + "/stop", json={}).json()
            assert stopped["status"] == "interrupted" and stopped["model_calls"] == 1
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            resume_settlement.set()

    asyncio.run(check())
    with transaction() as conn:
        call = one(conn, "SELECT status,provider_request_id FROM model_calls WHERE run_id=:id", id=run["id"])
        assert call == {"status": "settled", "provider_request_id": "known-usage"}
    wallet = client.get("/api/v1/wallet").json()
    assert wallet["held_units"] == 0 and wallet["spent"] == "0.000100"
