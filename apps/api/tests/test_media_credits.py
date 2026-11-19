"""Native text video and money handling, including partial failures and recovery."""

import asyncio
import sys
from decimal import Decimal

import httpx
import pytest
from test_video import FIXTURES, PROMPT, project_and_image, start

from atoms import ops
from atoms.core.config import settings
from atoms.core.db import all_rows, execute, one, transaction
from atoms.gateway.provider_client import ProviderClient
from atoms.gateway.vidu import ViduClient
from atoms.runtime import video, worker
from atoms.runtime.model import ModelError


def job_for(run):
    with transaction() as conn:
        return one(conn, "SELECT * FROM video_jobs WHERE run_id=:id", id=run["id"])


def fake_provider(monkeypatch, handler):
    monkeypatch.setattr(settings(), "test_fixture", False)
    monkeypatch.setattr(video, "ProviderClient", lambda: ProviderClient(transport=httpx.MockTransport(handler)))

    async def download(run, url):
        from atoms.domains.media import store_asset

        with transaction(True) as conn:
            return store_asset(conn, run["project_id"], (FIXTURES / "video.mp4").read_bytes(), "video/mp4")["id"]

    monkeypatch.setattr(video, "download_video", download)


@pytest.mark.usefixtures("funded_video_wallet")
def test_text_only_video_needs_no_image_and_uses_shared_wallet(client):
    project = client.post(
        "/api/v1/projects", json={"kind": "video", "title": "海边夕阳", "client_key": "text-video-project"}
    ).json()
    quote = client.get("/api/v1/video/quote?duration=5").json()
    assert quote == {
        "credits": "100",
        "required_units": 100_000_000,
        "model": "viduq3-pro",
        "resolution": "540p",
        "duration": 5,
    }
    for duration in (1, 16):
        assert client.get(f"/api/v1/video/quote?duration={duration}").json() == {**quote, "duration": duration}
    assert start(client, project).status_code == 202
    assert client.get("/api/v1/wallet").json()["held"] == "100"
    run = worker.claim("test-leader")
    assert job_for(run)["input_mode"] == "text"
    asyncio.run(worker.execute_run(run))
    wallet = client.get("/api/v1/wallet").json()
    assert (wallet["balance"], wallet["held"], wallet["spent"]) == ("101", "0", "100")
    ledger = client.get("/api/v1/wallet/transactions").json()
    assert ledger["pending"] == []
    assert ledger["items"][0]["kind"] == "media_consumption"
    assert ledger["items"][0]["input_tokens"] == ledger["items"][0]["output_tokens"] == 0
    with transaction() as conn:
        assert len(all_rows(conn, "SELECT * FROM media_assets")) == 1  # MP4 only; no automatic image call
        assert all_rows(conn, "SELECT * FROM model_calls") == []
    vid = client.get(f"/api/v1/projects/{project['id']}").json()["current_version_id"]
    media = client.get(f"/api/v1/projects/{project['id']}/versions/{vid}").json()["artifact"]["media"]
    assert media["image_asset_id"] is None


def test_text_video_protocol_passes_original_prompt_without_images():
    calls = []

    def handler(request):
        import json

        body = json.loads(request.content)
        calls.append(request.url.path)
        assert body == {
            "model": "viduq3-pro",
            "prompt": PROMPT,
            "duration": 5,
            "resolution": "540p",
            "audio": True,
            "aspect_ratio": "16:9",
            "payload": "run",
            "off_peak": False,
        }
        return httpx.Response(200, json={"task_id": "text-video"})

    async def send():
        async with ViduClient("test", transport=httpx.MockTransport(handler)) as provider:
            assert (
                await provider.create_text(
                    prompt=PROMPT, model="viduq3-pro", resolution="540p", duration=5, audio=True, payload="run"
                )
                == "text-video"
            )

    asyncio.run(send())
    assert calls == ["/ent/v2/text2video"]


@pytest.mark.usefixtures("funded_video_wallet")
def test_fixed_video_charge_ignores_supplier_price_and_usage_changes(client, monkeypatch):
    project, _ = project_and_image(client)
    assert start(client, project).status_code == 202
    run = worker.claim("test-leader")
    job = job_for(run)
    monkeypatch.setattr(settings(), "vidu_credit_price_cny", Decimal("0.05"))
    video.begin_call(run, job)
    video.call_change(run, job["video_call_id"], "settle", 10_000)
    video.call_change(run, job["video_call_id"], "settle", 36)
    video.call_change(run, job["video_call_id"], "settle", None)
    wallet = client.get("/api/v1/wallet").json()
    assert (wallet["balance"], wallet["held"], wallet["spent"]) == ("101", "0", "100")
    assert (
        len(
            [
                item
                for item in client.get("/api/v1/wallet/transactions").json()["items"]
                if item["kind"] == "media_consumption"
            ]
        )
        == 1
    )


def test_insufficient_balance_rolls_back_run_and_reservation(client):
    project, _ = project_and_image(client)
    response = start(client, project, video={"duration": 1})
    assert response.status_code == 402
    with transaction() as conn:
        assert all_rows(conn, "SELECT * FROM runs") == []
        assert all_rows(conn, "SELECT * FROM media_calls") == []
    assert client.get("/api/v1/wallet").json()["held"] == "0"


@pytest.mark.usefixtures("funded_video_wallet")
@pytest.mark.parametrize("mode", ["rejected", "generation_failed", "uncertain"])
def test_failure_release_or_hold_matches_provider_certainty(client, monkeypatch, mode):
    project, _ = project_and_image(client)
    assert start(client, project).status_code == 202
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "POST":
            if mode == "uncertain":
                raise httpx.ReadTimeout("timeout", request=request)
            if mode == "rejected":
                return httpx.Response(400, json={"code": "bad_request"})
            return httpx.Response(200, json={"task_id": "failed-task"})
        return httpx.Response(200, json={"state": "failed", "credits": 0})

    fake_provider(monkeypatch, handler)
    run = worker.claim("test-leader")
    with pytest.raises(ModelError) as caught:
        asyncio.run(worker.execute_run(run))
    worker.fail(run, caught.value.code, str(caught.value))
    wallet = client.get("/api/v1/wallet").json()
    assert wallet["balance"] == "201"
    assert wallet["held"] == ("100" if mode == "uncertain" else "0")
    assert len([request for request in requests if request.method == "POST"]) == 1
    if mode == "uncertain":
        assert start(client, project, retry_of_run_id=run["id"]).status_code == 409


@pytest.mark.usefixtures("funded_video_wallet")
def test_paid_success_survives_download_failure_and_retry_does_not_charge_twice(client, monkeypatch):
    project, _ = project_and_image(client)
    assert start(client, project).status_code == 202
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(
            200,
            json={"task_id": "paid-task"}
            if request.method == "POST"
            else {"state": "success", "video_url": "https://cdn.example.com/video.mp4"},
        )

    fake_provider(monkeypatch, handler)
    good_download = video.download_video

    async def missing(run, url):
        raise ModelError("VIDU_MEDIA_FORMAT", "暂未取到可播放文件")

    monkeypatch.setattr(video, "download_video", missing)
    run = worker.claim("test-leader")
    with pytest.raises(ModelError) as caught:
        asyncio.run(worker.execute_run(run))
    worker.fail(run, caught.value.code, str(caught.value))
    assert client.get("/api/v1/wallet").json()["spent"] == "100"
    assert start(client, project, retry_of_run_id=run["id"]).status_code == 202
    assert client.get("/api/v1/wallet").json()["held"] == "0"
    monkeypatch.setattr(video, "download_video", good_download)
    asyncio.run(worker.execute_run(worker.claim("test-leader")))
    assert calls == ["POST", "GET", "GET"]
    assert client.get("/api/v1/wallet").json()["spent"] == "100"
    assert client.get(f"/api/v1/projects/{project['id']}").json()["current_version_id"]


@pytest.mark.usefixtures("funded_video_wallet")
@pytest.mark.parametrize(
    ("whole_credit_billing", "reserved_units", "charged"),
    [(1, 15_000_000, "15"), (0, 14_062_500, "14.0625")],
)
def test_usage_based_video_missing_usage_still_requires_reconciliation(
    client, monkeypatch, whole_credit_billing, reserved_units, charged
):
    project, _ = project_and_image(client)
    assert start(client, project).status_code == 202
    with transaction(True) as conn:
        execute(
            conn,
            "UPDATE media_calls SET fixed_price=0, whole_credit_billing=:whole, reserved_units=:hold",
            whole=whole_credit_billing,
            hold=reserved_units,
        )
        execute(conn, "UPDATE credit_wallets SET held_units=:hold", hold=reserved_units)

    def handler(request):
        return httpx.Response(
            200,
            json={"task_id": "no-usage"}
            if request.method == "POST"
            else {"state": "success", "video_url": "https://cdn.example.com/video.mp4"},
        )

    fake_provider(monkeypatch, handler)
    run = worker.claim("test-leader")
    asyncio.run(worker.execute_run(run))
    assert client.get(f"/api/v1/projects/{project['id']}").json()["current_version_id"]
    pending = client.get("/api/v1/wallet/transactions").json()["pending"]
    assert pending[0]["category"] == "media" and pending[0]["status"] == "uncertain"
    assert pending[0]["reserved_units"] == reserved_units
    assert pending[0]["reserved"] == charged
    assert client.get("/api/v1/wallet").json()["spent"] == "0"
    monkeypatch.setattr(sys, "argv", ["ops", "media-reconcile", pending[0]["id"], "--provider-credits", "45"])
    ops.main()
    wallet = client.get("/api/v1/wallet").json()
    assert (wallet["spent"], wallet["held"]) == (charged, "0")
    ledger = client.get("/api/v1/wallet/transactions").json()
    assert [item["amount"] for item in ledger["items"] if item["kind"] == "media_consumption"] == ["-" + charged]
    assert client.get(f"/api/v1/runs/{run['id']}/inspector").json()["billing"]["total_settled_credits"] == charged
    with pytest.raises(ValueError):
        ops.main()


@pytest.mark.usefixtures("funded_video_wallet")
def test_unstarted_run_releases_hold_and_duplicate_request_reserves_once(client):
    project, _ = project_and_image(client)
    first = start(client, project)
    assert first.status_code == 202
    assert start(client, project).json()["id"] == first.json()["id"]
    run = worker.claim("test-leader")
    worker.fail(run, "STOPPED", "执行前终止")
    wallet = client.get("/api/v1/wallet").json()
    assert wallet["held"] == "0" and wallet["spent"] == "0"


def test_two_projects_share_available_balance_without_overspending(client):
    first, _ = project_and_image(client)
    second = client.post("/api/v1/projects", json={"kind": "video", "client_key": "another-video-project"}).json()
    with transaction(True) as conn:
        execute(conn, "UPDATE credit_wallets SET balance_units=101000000")
    assert start(client, first).status_code == 202
    response = client.post(
        f"/api/v1/projects/{second['id']}/runs",
        json={"prompt": PROMPT, "expected_revision": 0},
        headers={"Idempotency-Key": "second-project-request"},
    )
    assert response.status_code == 402
    assert client.get("/api/v1/wallet").json()["available"] == "1"
