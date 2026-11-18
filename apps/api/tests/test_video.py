import asyncio
import base64
import json
from pathlib import Path

import httpx
import pytest

from atoms.core.config import settings
from atoms.core.db import all_rows, execute, one, transaction
from atoms.domains.media import store_asset
from atoms.gateway.provider_client import ProviderClient
from atoms.gateway.vidu import ViduClient
from atoms.runtime import video, worker
from atoms.runtime.model import ModelError

FIXTURES = Path(__file__).resolve().parents[3] / "shared" / "test-fixtures"
PROMPT = "微风吹过，镜头缓缓拉远"


def project_and_image(client):
    project = client.post(
        "/api/v1/projects", json={"kind": "video", "title": "溪边微风", "client_key": "video-project-key"}
    ).json()
    response = client.post(
        f"/api/v1/projects/{project['id']}/media/images",
        json={
            "data_url": "data:image/png;base64,"
            + base64.b64encode((FIXTURES / "first-frame.png").read_bytes()).decode()
        },
    )
    assert response.status_code == 201, response.text
    return project, response.json()


def start(client, project, image=None, **extra):
    data = {"prompt": PROMPT, "expected_revision": 0, "base_version_id": None, **extra}
    if image:
        data["video"] = {"image_asset_id": image["id"]}
    return client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json=data,
        headers={"Idempotency-Key": "video-retry-key" if extra.get("retry_of_run_id") else "video-request-key"},
    )


def test_native_video_version_playback_download_and_private_assets(client):
    project, image = project_and_image(client)
    response = start(client, project, image)
    assert response.status_code == 202, response.text
    run = worker.claim("test-leader")
    asyncio.run(worker.execute_run(run))
    updated = client.get(f"/api/v1/projects/{project['id']}").json()
    vid = updated["current_version_id"]
    version = client.get(f"/api/v1/projects/{project['id']}/versions/{vid}").json()
    assert version["artifact"]["schema_version"] == "3"
    media = version["artifact"]["media"]
    assert (media["model"], media["resolution"], media["duration"]) == ("viduq3-pro", "540p", 5)
    url = f"/api/v1/projects/{project['id']}/media/{media['asset_id']}"
    partial = client.get(url, headers={"Range": "bytes=0-31"})
    assert partial.status_code == 206
    assert len(partial.content) == 32 and b"ftyp" in partial.content
    exported = client.get(f"/api/v1/projects/{project['id']}/versions/{vid}/export")
    assert exported.status_code == 200 and exported.headers["content-type"] == "video/mp4"
    assert exported.content == (FIXTURES / "video.mp4").read_bytes()
    assert client.post(f"/api/v1/projects/{project['id']}/versions/{vid}/preview-ticket", json={}).status_code == 400
    with transaction() as conn:
        assert all_rows(conn, "SELECT * FROM model_calls") == []
        assert one(conn, "SELECT status FROM runs WHERE id=:id", id=run["id"])["status"] == "succeeded"
    client.cookies.clear()
    auth = client.post("/api/v1/session", json={}).json()
    client.headers.update({"X-CSRF-Token": auth["csrf_token"]})
    assert client.get(url).status_code == 404
    assert client.get(f"/api/v1/projects/{project['id']}/media/{image['id']}").status_code == 404


def test_video_input_validation_and_configuration(client, monkeypatch):
    project, image = project_and_image(client)
    invalid = client.post(
        f"/api/v1/projects/{project['id']}/media/images",
        json={"data_url": "data:image/png;base64," + base64.b64encode(b"this is not a PNG image").decode()},
    )
    assert invalid.status_code == 422
    assert start(client, project, video={"image_asset_id": image["id"], "duration": 17}).status_code == 422
    with transaction(True) as conn:
        execute(conn, "UPDATE worker_status SET video_configured=0")
    missing = start(client, project, image)
    assert missing.status_code == 503
    assert missing.json()["detail"]["code"] == "video_not_configured"


def test_vidu_protocol_and_default_quality():
    requests = []

    def transport(request):
        requests.append(request)
        assert request.headers["authorization"] == "Token test-private-key"
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["model"] == "viduq3-pro" and body["resolution"] == "540p"
            assert body["duration"] == 5 and body["images"] == ["data:image/png;base64,AAAA"]
            assert body["is_rec"] is False and body["audio"] is True
            return httpx.Response(200, json={"task_id": "task_123", "state": "created"})
        return httpx.Response(
            200,
            json={
                "id": "task_123",
                "state": "success",
                "creations": [{"url": "https://cdn.example.com/video.mp4"}],
                "credits": 20,
            },
        )

    async def call():
        async with ViduClient("test-private-key", transport=httpx.MockTransport(transport)) as provider:
            task = await provider.create(
                image="data:image/png;base64,AAAA",
                prompt=PROMPT,
                model="viduq3-pro",
                resolution="540p",
                duration=5,
                audio=True,
                payload="local-run-id",
            )
            assert (await provider.query(task))["state"] == "success"

    asyncio.run(call())
    assert [request.url.path for request in requests] == ["/ent/v2/img2video", "/ent/v2/tasks/task_123/creations"]


def test_uncertain_paid_submission_is_not_automatically_repeated():
    calls = []

    def transport(request):
        calls.append(request)
        raise httpx.ReadTimeout("timeout", request=request)

    async def call():
        async with ViduClient("private-test-key", transport=httpx.MockTransport(transport)) as provider:
            with pytest.raises(ModelError) as caught:
                await provider.create(
                    image="data:image/png;base64,AAAA",
                    prompt=PROMPT,
                    model="viduq3-pro",
                    resolution="540p",
                    duration=5,
                    audio=True,
                    payload="run",
                )
            assert caught.value.code == "VIDU_SUBMISSION_UNCERTAIN"
            assert "private-test-key" not in str(caught.value)

    asyncio.run(call())
    assert len(calls) == 1


def test_resume_queries_existing_provider_task_without_resubmission(client, monkeypatch):
    project, image = project_and_image(client)
    assert start(client, project, image).status_code == 202
    old = worker.claim("test-leader")
    video.checkpoint(old, phase="processing", provider_task_id="existing-task")
    worker.fail(old, "WORKER_LOST", "服务曾中断")
    response = start(client, project, retry_of_run_id=old["id"])
    assert response.status_code == 202, response.text
    cfg = settings()
    monkeypatch.setattr(cfg, "test_fixture", False)
    calls = []

    def transport(request):
        calls.append(request)
        assert request.method == "GET" and request.url.path == "/internal/v1/video/tasks/existing-task"
        return httpx.Response(
            200, json={"state": "success", "credits": 10, "video_url": "https://cdn.example.com/result.mp4"}
        )

    monkeypatch.setattr(video, "ProviderClient", lambda: ProviderClient(transport=httpx.MockTransport(transport)))

    async def download(run, url):
        with transaction(True) as conn:
            return store_asset(conn, run["project_id"], (FIXTURES / "video.mp4").read_bytes(), "video/mp4")["id"]

    monkeypatch.setattr(video, "download_video", download)
    run = worker.claim("test-leader")
    asyncio.run(worker.execute_run(run))
    assert len(calls) == 1
    with transaction() as conn:
        assert one(conn, "SELECT status FROM runs WHERE id=:id", id=run["id"])["status"] == "succeeded"


def test_media_downloader_blocks_private_network_addresses():
    for url in [
        "http://example.com/video.mp4",
        "https://127.0.0.1/video.mp4",
        "https://user:pass@example.com/video.mp4",
    ]:
        with pytest.raises(ModelError):
            asyncio.run(video.public_media_url(url))


def test_backup_and_offline_restore_include_native_media(client, monkeypatch, tmp_path):
    import sys

    from conftest import create_project, submit

    from atoms import ops
    from atoms.billing.credits import reserve_call
    from atoms.domains.media import asset_path

    project, image = project_and_image(client)
    assert start(client, project, image).status_code == 202
    asyncio.run(worker.execute_run(worker.claim("test-leader")))
    text_project = create_project(client)
    assert submit(client, text_project["id"]).status_code == 202
    call = reserve_call(worker.claim("test-leader"), 1, 1000, 3000)
    backup = tmp_path / "video-backup.db"
    monkeypatch.setattr(sys, "argv", ["ops", "backup", str(backup)])
    ops.main()
    assert ops.inspect_backup(backup)["schema"] == ops.CURRENT_SCHEMA
    with transaction(True) as conn:
        asset = one(
            conn, "SELECT * FROM media_assets WHERE project_id=:pid AND mime_type='video/mp4'", pid=project["id"]
        )
        execute(conn, "UPDATE worker_status SET lease_until=0")
    target = asset_path(asset)
    original = target.read_bytes()
    target.unlink()
    monkeypatch.setattr(sys, "argv", ["ops", "restore", str(backup), "--offline", "--confirm-restore"])
    ops.main()
    assert target.read_bytes() == original
    with transaction() as conn:
        assert one(conn, "SELECT status FROM model_calls WHERE id=:id", id=call["id"])["status"] == "released"
        assert (
            one(conn, "SELECT held_units FROM credit_wallets WHERE visitor_id=:id", id=call["visitor_id"])["held_units"]
            == 0
        )
