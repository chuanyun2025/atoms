import asyncio
import json
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from atoms.billing import credits
from atoms.core.config import settings
from atoms.core.db import all_rows, one, transaction
from atoms.core.schemas import ImageUpload, PasscodeRedeem, ProjectCreate, Restore, RunCreate, SourceSave, StatePatch
from atoms.core.security import (
    COOKIE,
    client_ip,
    csrf,
    origin_check,
    read_visitor,
    ticket_decode,
    ticket_encode,
    uid,
    visitor,
)
from atoms.domains.examples import compiled_example, example_source
from atoms.domains.media import asset_path, owned_asset, upload_image
from atoms.runtime import service
from atoms.runtime.preview import csp, export_zip, render_document
from atoms.runtime.publication import router as publication_router
from atoms.runtime.source_edits import save_source_version, source_artifact, validate_source


@asynccontextmanager
async def lifespan(app):
    from atoms.runtime.worker import recover_expired

    async def recover_loop():
        while True:
            await run_in_threadpool(recover_expired)
            await asyncio.sleep(5)

    task = asyncio.create_task(recover_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


class _PayloadTooLarge(Exception):
    pass


def _boundary_response(status: int, detail: dict):
    return JSONResponse(
        {"detail": detail},
        status_code=status,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


class BoundaryMiddleware:
    def __init__(self, wrapped):
        self.wrapped = wrapped

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.wrapped(scope, receive, send)
            return
        method = scope.get("method", "GET")
        path = scope.get("path", "")
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        large_source = (
            method == "POST"
            and path.startswith("/api/v1/projects/")
            and "/versions/" in path
            and path.endswith("/source")
        )
        large_image = path.endswith("/media/images")
        maximum = (12 if large_source else 8 if large_image else 2) * 1024 * 1024
        raw_size = headers.get(b"content-length")
        if raw_size is not None:
            size_text = raw_size.decode("latin-1").strip()
            if not size_text.isdecimal() or int(size_text) > maximum:
                await _boundary_response(413, {"code": "request_too_large", "message": "请求过大"})(
                    scope, receive, send
                )
                return
        if method in {"POST", "PATCH", "PUT", "DELETE"} and path.startswith("/api/v1/"):
            try:
                origin_check(Request(scope), path != "/api/v1/session")
            except Exception as exc:
                if hasattr(exc, "status_code"):
                    await _boundary_response(exc.status_code, exc.detail)(scope, receive, send)
                    return
                raise
        received = 0
        too_large = False
        response_started = False

        async def limited_receive():
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > maximum:
                    too_large = True
                    raise _PayloadTooLarge()
            return message

        async def send_with_headers(message):
            nonlocal response_started
            if too_large and not response_started:
                return
            if message["type"] == "http.response.start":
                response_started = True
                hdrs = list(message.get("headers", []))
                names = {k.lower() for k, _ in hdrs}
                if b"cache-control" not in names:
                    hdrs.append((b"cache-control", b"no-store"))
                if b"x-content-type-options" not in names:
                    hdrs.append((b"x-content-type-options", b"nosniff"))
                if b"referrer-policy" not in names:
                    hdrs.append((b"referrer-policy", b"no-referrer"))
                message = {**message, "headers": hdrs}
            await send(message)

        try:
            await self.wrapped(scope, limited_receive, send_with_headers)
        except _PayloadTooLarge:
            if response_started:
                raise
        if too_large and not response_started:
            await _boundary_response(413, {"code": "request_too_large", "message": "请求过大"})(scope, receive, send)


app = FastAPI(
    title="Atoms Demo API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings().app_env != "production" else None,
    redoc_url=None,
)
app.include_router(publication_router)
app.add_middleware(BoundaryMiddleware)


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready(response: Response):
    with transaction() as conn:
        worker = one(conn, "SELECT * FROM worker_status WHERE id=1")
    healthy = bool(worker and worker["heartbeat_at"] > time.time() - 20 and worker["lease_until"] > time.time())
    configured = bool(worker and (worker["model_configured"] or worker["video_configured"]))
    if not healthy or not configured:
        response.status_code = 503
    return {"database": True, "worker": healthy, "model_configured": configured}


@app.post("/api/v1/session")
def bootstrap(request: Request, response: Response):
    row, token = service.create_session(request)
    response.set_cookie(
        COOKIE, token, max_age=30 * 86400, httponly=True, secure=settings().cookie_secure, samesite="lax", path="/"
    )
    return {"visitor_id": row["id"], "csrf_token": csrf(token), "expires_at": row["expires_at"]}


@app.get("/api/v1/capabilities")
def capabilities(session=Depends(read_visitor)):
    from atoms.billing.passcodes import public_guardrail_status
    from atoms.core.db import maintenance

    user, conn = session
    readonly = maintenance(conn)
    worker = one(conn, "SELECT * FROM worker_status WHERE id=1")
    available = bool(worker and worker["heartbeat_at"] > time.time() - 20 and worker["lease_until"] > time.time())
    guardrails = public_guardrail_status(conn, user["id"])
    return {
        "model_configured": bool(available and worker["model_configured"]),
        "model": worker["text_model"] if available else None,
        "video_configured": bool(available and worker["video_configured"]),
        "video_model": settings().vidu_model,
        "video_resolution": settings().vidu_resolution,
        "worker_available": available,
        "read_only": readonly,
        "scope": "React / TypeScript 网站与游戏、网页幻灯片、Vidu 图生视频",
        "limits": {
            "billing": "credits",
            "initial_credits": credits.WELCOME_CREDITS,
            "input_credits_per_million": 20,
            "output_credits_per_million": 80,
        },
        "guardrails": guardrails,
    }


@app.get("/api/v1/wallet")
def wallet_get(session=Depends(read_visitor)):
    user, conn = session
    return credits.wallet(conn, user["id"])


@app.post("/api/v1/wallet/passcode")
def wallet_redeem_passcode(data: PasscodeRedeem, request: Request, user=Depends(visitor)):
    from atoms.billing.passcodes import redeem_passcode_request

    origin_check(request)
    return redeem_passcode_request(user["id"], data.code, client_ip(request))


@app.post("/api/v1/wallet/passcode/detach")
def wallet_detach_passcode(request: Request, user=Depends(visitor)):
    from atoms.billing.passcodes import detach_passcode

    origin_check(request)
    with transaction(True) as conn:
        service.mutable(conn)
        detach_passcode(conn, user["id"])
        return credits.wallet(conn, user["id"])


@app.get("/api/v1/video/quote")
def video_quote(duration: int = Query(default=5, ge=1, le=16), user=Depends(visitor)):
    from atoms.billing.media_credits import quote

    return quote(duration)


@app.get("/api/v1/wallet/transactions")
def wallet_transactions(before: float | None = None, session=Depends(read_visitor)):
    user, conn = session
    return credits.transactions(conn, user["id"], before)


@app.get("/api/v1/projects")
def projects(session=Depends(read_visitor)):
    user, conn = session
    return {
        "items": all_rows(
            conn, "SELECT * FROM projects WHERE owner_id=:owner ORDER BY updated_at DESC", owner=user["id"]
        )
    }


@app.post("/api/v1/projects", status_code=201)
def project_create(data: ProjectCreate, user=Depends(visitor)):
    with transaction(True) as conn:
        return service.create_project(conn, user["id"], data)


@app.get("/api/v1/projects/{pid}")
def project_get(pid: str, session=Depends(read_visitor)):
    user, conn = session
    return service.project(conn, pid, user["id"])


@app.get("/api/v1/projects/{pid}/messages")
def messages(pid: str, session=Depends(read_visitor)):
    user, conn = session
    service.project(conn, pid, user["id"])
    return {
        "items": all_rows(
            conn,
            """SELECT m.*,r.status AS run_status,r.error_code AS run_error_code,
        CASE WHEN m.role='assistant' AND r.status IN ('failed','interrupted') THEN r.prompt END AS run_prompt,
        r.retry_of_run_id,r.base_version_id AS run_base_version_id,r.model_calls,(c.run_id IS NOT NULL) AS has_candidate
        FROM messages m LEFT JOIN runs r ON m.run_id=r.id
        LEFT JOIN run_candidates c ON c.run_id=r.id
        WHERE m.project_id=:id ORDER BY m.created_at,m.id""",
            id=pid,
        )
    }


@app.post("/api/v1/projects/{pid}/media/images", status_code=201)
def media_image_upload(pid: str, data: ImageUpload, user=Depends(visitor)):
    with transaction(True) as conn:
        project = service.project(conn, pid, user["id"])
        service.mutable(conn)
        if project["kind"] != "video":
            service.error(422, "invalid_project_kind", "请在视频项目中上传首帧")
        return upload_image(conn, pid, data.data_url)


@app.get("/api/v1/projects/{pid}/media/{asset_id}")
def media_get(pid: str, asset_id: str, download: bool = False, user=Depends(visitor)):
    with transaction() as conn:
        service.project(conn, pid, user["id"])
        asset = owned_asset(conn, pid, asset_id)
    path = asset_path(asset)
    if not path.is_file():
        service.error(404, "media_missing", "媒体文件暂不可用")
    return FileResponse(
        path,
        media_type=asset["mime_type"],
        filename="atoms-video.mp4" if asset["mime_type"] == "video/mp4" else path.name,
        content_disposition_type="attachment" if download else "inline",
        headers={} if download else {"Cache-Control": "private, max-age=3600"},
    )


@app.get("/api/v1/projects/{pid}/video-input")
def video_input(pid: str, session=Depends(read_visitor)):
    user, conn = session
    service.project(conn, pid, user["id"])
    job = one(
        conn,
        "SELECT j.*,r.prompt FROM video_jobs j JOIN runs r ON r.id=j.run_id WHERE r.project_id=:pid ORDER BY r.created_at DESC LIMIT 1",
        pid=pid,
    )
    if not job:
        image = one(
            conn,
            "SELECT id FROM media_assets WHERE project_id=:pid AND mime_type LIKE 'image/%' ORDER BY created_at DESC LIMIT 1",
            pid=pid,
        )
        if image:
            return {"image_asset_id": image["id"], "duration": 5, "audio": True}
    return {key: job[key] for key in ("image_asset_id", "duration", "audio", "prompt", "input_mode")} if job else None


@app.post("/api/v1/projects/{pid}/runs", status_code=202)
def run_create(
    pid: str, data: RunCreate, request: Request, idempotency_key: str = Header(default=""), user=Depends(visitor)
):
    with transaction(True) as conn:
        return service.create_run(conn, user["id"], pid, data, idempotency_key, client_ip(request))


def owned_run(conn, rid, owner):
    row = one(conn, "SELECT * FROM runs WHERE id=:id AND owner_id=:owner", id=rid, owner=owner)
    if not row:
        service.error(404, "run_not_found", "任务不存在")
    return row


@app.get("/api/v1/runs/{rid}")
def run_get(rid: str, session=Depends(read_visitor)):
    user, conn = session
    run = service.public_run(owned_run(conn, rid, user["id"]))
    workspace = one(conn, "SELECT source_revision,digest AS preview_digest FROM run_workspace WHERE run_id=:id", id=rid)
    if workspace:
        workspace["has_preview"] = bool(workspace["preview_digest"])
    event_seq = one(conn, "SELECT COALESCE(MAX(seq),0) AS seq FROM run_events WHERE run_id=:id", id=rid)["seq"]
    return {**run, "workspace": workspace, "event_seq": event_seq}


@app.post("/api/v1/runs/{rid}/stop")
def run_stop(rid: str, user=Depends(visitor)):
    from atoms.runtime.worker import fail_locked

    with transaction(True) as conn:
        run = owned_run(conn, rid, user["id"])
        if run["status"] in {"pending", "running"}:
            if service.project(conn, run["project_id"], user["id"])["kind"] == "video":
                service.error(409, "stop_unsupported", "此任务暂不支持停止")
            fail_locked(conn, run, "interrupted", service.USER_STOPPED, "你已停止本次构建")
            run = owned_run(conn, rid, user["id"])
        return service.public_run(run)


@app.get("/api/v1/runs/{rid}/source")
def run_source(rid: str, session=Depends(read_visitor)):
    user, conn = session
    run = owned_run(conn, rid, user["id"])
    row = one(conn, "SELECT source_json FROM run_workspace WHERE run_id=:id", id=rid)
    if not row and run["result_version_id"]:
        version = service.owned_version(conn, run["project_id"], run["result_version_id"])
        artifact = json.loads(version["raw_json"])
        if artifact.get("files"):
            return {"schema_version": artifact["schema_version"], "files": artifact["files"]}
    if not row:
        service.error(404, "source_unavailable", "源码暂未就绪")
    return json.loads(row["source_json"])


@app.get("/api/v1/runs/{rid}/inspector")
def run_inspector(rid: str, session=Depends(read_visitor)):
    user, conn = session
    return service.run_inspector(conn, rid, user["id"])


def can_preview_run(run):
    return (
        run["status"] in {"running", "succeeded"}
        or (run["status"] == "failed" and run["error_code"] in service.LEGACY_ACCEPTANCE_ERRORS)
        or (run["status"] == "interrupted" and run["error_code"] == service.USER_STOPPED)
    )


@app.post("/api/v1/runs/{rid}/preview-ticket")
def run_preview_ticket(rid: str, session=Depends(read_visitor)):
    user, conn = session
    run = owned_run(conn, rid, user["id"])
    if run["result_version_id"]:
        row = one(
            conn,
            """SELECT a.digest FROM versions v JOIN artifacts a ON a.id=v.artifact_id
            WHERE v.id=:id AND json_extract(a.raw_json,'$.schema_version')!='3'""",
            id=run["result_version_id"],
        )
    else:
        row = one(conn, "SELECT digest FROM run_workspace WHERE run_id=:id AND digest IS NOT NULL", id=rid)
    if not can_preview_run(run) or not row:
        service.error(404, "preview_unavailable", "临时预览已结束或尚未就绪")
    payload = {
        "run_id": rid,
        "digest": row["digest"],
        "instance_id": uid(),
        "channel_nonce": uid() + uid(),
        "exp": time.time() + 120,
        "read_only": False,
    }
    return {**payload, "url": "/sandbox/runs/" + rid + "?ticket=" + ticket_encode(payload)}


def read_events(rid, owner, after):
    with transaction() as conn:
        row = owned_run(conn, rid, owner)
        events = all_rows(
            conn, "SELECT * FROM run_events WHERE run_id=:id AND seq>:after ORDER BY seq LIMIT 200", id=rid, after=after
        )
    return row, events


@app.get("/api/v1/runs/{rid}/events")
async def run_events(rid: str, request: Request, after: int = 0, user=Depends(visitor)):
    raw = request.headers.get("last-event-id")
    if raw:
        try:
            after = max(after, int(raw))
        except ValueError:
            service.error(400, "invalid_cursor", "事件游标无效")
    after = max(0, after)
    await run_in_threadpool(read_events, rid, user["id"], after)

    async def stream():
        cursor = after
        heartbeat = time.monotonic()
        while not await request.is_disconnected():
            row, events = await run_in_threadpool(read_events, rid, user["id"], cursor)
            for event in events:
                cursor = event["seq"]
                yield "id: " + str(cursor) + "\nevent: " + event["type"] + "\ndata: " + event["payload"] + "\n\n"
            if row["status"] not in {"pending", "running"} and len(events) < 200:
                return
            if time.monotonic() - heartbeat > 15:
                yield ": heartbeat\n\n"
                heartbeat = time.monotonic()
            await asyncio.sleep(0.5)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no", "Connection": "keep-alive"}
    )


@app.get("/api/v1/projects/{pid}/versions")
def versions(pid: str, session=Depends(read_visitor)):
    user, conn = session
    service.project(conn, pid, user["id"])
    return {
        "items": [
            service.public_version(row)
            for row in all_rows(conn, "SELECT * FROM versions WHERE project_id=:id ORDER BY number DESC", id=pid)
        ]
    }


@app.get("/api/v1/projects/{pid}/versions/{vid}")
def version_get(pid: str, vid: str, session=Depends(read_visitor)):
    user, conn = session
    service.project(conn, pid, user["id"])
    return service.public_version(service.owned_version(conn, pid, vid), True)


@app.post("/api/v1/projects/{pid}/versions/{vid}/source")
async def save_version_source(
    pid: str, vid: str, data: SourceSave, idempotency_key: str = Header(default=""), user=Depends(visitor)
):
    owner = user["id"]
    replay, artifact, kind = await run_in_threadpool(source_artifact, owner, pid, vid, data, idempotency_key)
    if replay:
        return replay
    validation = await validate_source(artifact, kind)
    return await run_in_threadpool(save_source_version, owner, pid, vid, data, idempotency_key, artifact, validation)


@app.post("/api/v1/projects/{pid}/versions/{vid}/restore")
def version_restore(pid: str, vid: str, data: Restore, user=Depends(visitor)):
    with transaction(True) as conn:
        return service.restore_version(conn, user["id"], pid, vid, data.expected_revision)


@app.post("/api/v1/projects/{pid}/versions/{vid}/preview-ticket")
def preview_ticket(pid: str, vid: str, session=Depends(read_visitor)):
    from atoms.core.db import maintenance

    user, conn = session
    row = service.project(conn, pid, user["id"])
    version = service.owned_version(conn, pid, vid)
    if json.loads(version["raw_json"]).get("schema_version") == "3":
        service.error(400, "native_video", "视频请使用原生播放器打开")
    readonly = maintenance(conn) or row["current_version_id"] != vid
    payload = {
        "version_id": vid,
        "digest": version["digest"],
        "instance_id": uid(),
        "channel_nonce": uid() + uid(),
        "exp": time.time() + 120,
        "read_only": readonly,
    }
    return {**payload, "url": "/sandbox/versions/" + vid + "?ticket=" + ticket_encode(payload)}


@app.get("/api/v1/game-examples/{example_id}/preview-ticket")
@app.get("/api/v1/examples/{example_id}/preview-ticket")
def example_ticket(example_id: str):
    compiled = compiled_example(example_id)
    payload = {
        "example_id": example_id,
        "digest": compiled["digest"],
        "instance_id": uid(),
        "channel_nonce": uid() + uid(),
        "exp": time.time() + 120,
        "read_only": False,
    }
    return {**payload, "url": "/sandbox/examples/" + example_id + "?ticket=" + ticket_encode(payload)}


@app.get("/api/v1/game-examples/{example_id}/source")
@app.get("/api/v1/examples/{example_id}/source")
def example_source_get(example_id: str):
    return example_source(example_id)


@app.get("/sandbox/examples/{example_id}", response_class=HTMLResponse)
def example_sandbox(example_id: str, request: Request, ticket: str = ""):
    if request.headers.get("sec-fetch-dest") != "iframe" or request.headers.get("sec-fetch-site") != "same-origin":
        service.error(403, "iframe_only", "请在工作台内打开预览")
    payload = ticket_decode(ticket)
    compiled = compiled_example(example_id)
    if payload.get("example_id") != example_id or payload.get("digest") != compiled["digest"]:
        service.error(403, "invalid_preview", "预览凭证不匹配")
    return HTMLResponse(render_document(compiled, payload), headers={"Content-Security-Policy": csp()})


@app.get("/sandbox/versions/{vid}", response_class=HTMLResponse)
def sandbox(vid: str, request: Request, ticket: str = ""):
    if request.headers.get("sec-fetch-dest") != "iframe" or request.headers.get("sec-fetch-site") != "same-origin":
        service.error(403, "iframe_only", "请在工作台内打开预览")
    payload = ticket_decode(ticket)
    if payload.get("version_id") != vid:
        service.error(403, "invalid_preview", "预览凭证不匹配")
    with transaction() as conn:
        row = one(conn, "SELECT a.* FROM artifacts a JOIN versions v ON a.id=v.artifact_id WHERE v.id=:id", id=vid)
    if not row or row["digest"] != payload["digest"]:
        service.error(403, "invalid_preview", "预览内容校验失败")
    return HTMLResponse(
        render_document(json.loads(row["compiled_json"]), payload), headers={"Content-Security-Policy": csp()}
    )


@app.get("/sandbox/runs/{rid}", response_class=HTMLResponse)
def run_sandbox(rid: str, request: Request, ticket: str = ""):
    if request.headers.get("sec-fetch-dest") != "iframe" or request.headers.get("sec-fetch-site") != "same-origin":
        service.error(403, "iframe_only", "请在工作台内打开预览")
    payload = ticket_decode(ticket)
    if payload.get("run_id") != rid:
        service.error(403, "invalid_preview", "预览凭证不匹配")
    with transaction() as conn:
        row = one(
            conn,
            """SELECT w.compiled_json,w.digest,r.status,r.error_code FROM run_workspace w JOIN runs r ON r.id=w.run_id
            WHERE w.run_id=:id AND w.compiled_json IS NOT NULL
            UNION ALL SELECT a.compiled_json,a.digest,r.status,r.error_code FROM runs r JOIN versions v ON v.id=r.result_version_id
            JOIN artifacts a ON a.id=v.artifact_id WHERE r.id=:id AND r.status='succeeded'""",
            id=rid,
        )
        if not row or not can_preview_run(row) or row["digest"] != payload["digest"]:
            service.error(404, "preview_unavailable", "临时预览已结束或尚未就绪")
    return HTMLResponse(
        render_document(json.loads(row["compiled_json"]), payload), headers={"Content-Security-Policy": csp()}
    )


@app.get("/api/v1/projects/{pid}/app-state")
def state_get(pid: str, session=Depends(read_visitor)):
    user, conn = session
    service.project(conn, pid, user["id"])
    return service.app_state(conn, pid)


@app.patch("/api/v1/projects/{pid}/app-state")
def state_patch(pid: str, data: StatePatch, user=Depends(visitor)):
    with transaction(True) as conn:
        return service.patch_state(conn, user["id"], pid, data)


@app.get("/api/v1/projects/{pid}/versions/{vid}/export")
def export(pid: str, vid: str, user=Depends(visitor)):
    with transaction() as conn:
        service.project(conn, pid, user["id"])
        version = service.owned_version(conn, pid, vid)
        artifact = json.loads(version["raw_json"])
        if artifact.get("schema_version") == "3":
            asset = owned_asset(conn, pid, artifact["media"]["asset_id"])
            path = asset_path(asset)
            if not path.is_file():
                service.error(404, "media_missing", "视频文件暂不可用")
            return FileResponse(
                path, media_type="video/mp4", filename="atoms-video-v" + str(version["number"]) + ".mp4"
            )
    return Response(
        export_zip(version),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="atoms-v' + str(version["number"]) + '.zip"'},
    )
