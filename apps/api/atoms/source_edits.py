"""Validate manual source edits before atomically creating a new version."""
import hashlib
import json
import re
import time

import httpx

from . import service
from .db import add_event, execute, one, transaction
from .orchestration import has_threejs
from .security import uid
from .validator_client import validate_artifact


def request_fingerprint(pid, vid, data, key):
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{8,100}", key):
        service.error(400, "invalid_idempotency_key", "保存凭证无效")
    body = json.dumps(["source", pid, vid, data.expected_revision, data.files], sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


def source_save_result(version, project):
    return {**service.public_version(version, True), "project": project}


def replay_version(conn, project, key, fingerprint):
    previous = one(
        conn, """SELECT k.request_hash,r.result_version_id FROM request_keys k
            JOIN runs r ON r.id=k.run_id WHERE k.owner_id=:owner AND k.key=:key""",
        owner=project["owner_id"], key=key,
    )
    if previous:
        if previous["request_hash"] != fingerprint:
            service.error(409, "idempotency_conflict", "此保存凭证已用于其他请求，请重新编辑后保存")
        version = service.owned_version(conn, project["id"], previous["result_version_id"])
        return source_save_result(version, project)


def check_base(project, vid, revision):
    service.check_revision(project, revision)
    if project["current_version_id"] != vid:
        service.error(409, "base_version_conflict", "当前版本已变化，请基于最新版本编辑")
    if project["active_run_id"]:
        service.error(409, "run_active", "生成期间暂时无法保存源码，请等待构建完成")


def source_artifact(owner, pid, vid, data, key):
    with transaction() as conn:
        project = service.project(conn, pid, owner)
        fingerprint = request_fingerprint(pid, vid, data, key)
        replay = replay_version(conn, project, key, fingerprint)
        if replay:
            return replay, None, None
        service.mutable(conn)
        check_base(project, vid, data.expected_revision)
        base = service.owned_version(conn, pid, vid)
    artifact = json.loads(base["raw_json"])
    if artifact.get("schema_version") not in {"1", "2"} or project["kind"] == "video":
        service.error(422, "source_not_editable", "此版本没有可编辑的源码")
    files = artifact["files"]
    if data.files.keys() - files.keys():
        service.error(422, "unknown_source_file", "只能编辑此版本已有的文件")
    if all(files[path] == value for path, value in data.files.items()):
        return source_save_result(base, project), None, None
    files.update(data.files)
    artifact["summary"] = "手动编辑源码"
    return None, artifact, project["kind"]


async def validate_source(artifact, kind):
    try:
        validation = await validate_artifact(artifact, uid(), kind, kind == "game" and has_threejs(artifact))
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 429:
            service.error(503, "validator_busy", "校验服务正在处理其他构建，请稍后重新保存")
        if error.response.status_code == 413:
            service.error(413, "source_too_large", "源码超过校验服务的大小限制")
        service.error(503, "validator_unavailable", "校验服务暂不可用，请稍后重新保存")
    except (httpx.HTTPError, ValueError):
        service.error(503, "validator_unavailable", "校验服务暂不可用或响应超时，请稍后重新保存")
    if isinstance(validation, dict):
        diagnostic = validation.get("error")
        if validation.get("ok") is False and isinstance(diagnostic, str) and diagnostic:
            service.error(422, "source_validation_failed", diagnostic[:2000])
        report = validation.get("report")
        compiled = validation.get("compiled")
        required = ("body_html", "css_base64", "js_base64", "digest", "compiler_version", "sdk_version")
        if (validation.get("ok") is True and isinstance(report, dict) and report.get("ready") is True
                and report.get("acceptance") == "smoke" and isinstance(compiled, dict)
                and all(isinstance(compiled.get(field), str) for field in required)):
            return validation
    service.error(503, "validator_unavailable", "校验服务未完成预览检查，请稍后重新保存")


def save_source_version(owner, pid, vid, data, key, artifact, validation):
    fingerprint = request_fingerprint(pid, vid, data, key)
    with transaction(True) as conn:
        project = service.project(conn, pid, owner)
        replay = replay_version(conn, project, key, fingerprint)
        if replay:
            return replay
        service.mutable(conn)
        check_base(project, vid, data.expected_revision)
        now, rid = time.time(), uid()
        # A completed source run links the version to its origin without queuing work or charging credits.
        execute(
            conn, """INSERT INTO runs(id,project_id,owner_id,prompt,base_version_id,expected_revision,
                status,stage,created_at)
                VALUES(:id,:pid,:owner,:prompt,:base,:revision,'succeeded','completed',:now)""",
            id=rid, pid=pid, owner=owner, prompt=artifact["summary"], base=vid,
            revision=data.expected_revision, now=now,
        )
        run = {"id": rid, "project_id": pid, "base_version_id": vid}
        result, number = service.write_version(conn, project, run, artifact, validation, now)
        execute(
            conn, """INSERT INTO request_keys(owner_id,key,request_hash,run_id,created_at)
                VALUES(:owner,:key,:fingerprint,:rid,:now)""",
            owner=owner, key=key, fingerprint=fingerprint, rid=rid, now=now,
        )
        add_event(conn, rid, "completed", {"version_id": result, "version_number": number, "message": artifact["summary"]})
        return source_save_result(service.owned_version(conn, pid, result), service.project(conn, pid, owner))
