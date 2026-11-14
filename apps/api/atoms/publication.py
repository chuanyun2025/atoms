"""Publish approved, immutable snapshots through a stable public link."""
import json
import time
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import Field, model_validator

from . import service
from .db import execute, one, transaction
from .preview import csp, render_document
from .schemas import StrictModel
from .security import ticket_decode, ticket_encode, uid, visitor

router = APIRouter()


class PublicationChange(StrictModel):
    action: Literal["publish", "rollback", "unpublish"]
    expected_revision: int = Field(ge=0)
    version_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")

    @model_validator(mode="after")
    def validate_version(self):
        if (self.action == "publish") != (self.version_id is not None):
            raise ValueError("发布时必须指定正式版本")
        return self


def owner_publication(conn, pid):
    row = one(conn, """SELECT p.*, v.number AS version_number, old.number AS previous_version_number
        FROM publications p JOIN versions v ON v.id=p.version_id
        LEFT JOIN versions old ON old.id=p.previous_version_id WHERE p.project_id=:pid""", pid=pid)
    if row:
        row["published"] = bool(row["published"])
        row["path"] = "/p/" + row["slug"]
    return row


@router.get("/api/v1/projects/{pid}/publication")
def get_publication(pid: str, user=Depends(visitor)):
    with transaction() as conn:
        service.project(conn, pid, user["id"])
        return {"publication": owner_publication(conn, pid)}


@router.put("/api/v1/projects/{pid}/publication")
def change_publication(pid: str, data: PublicationChange, user=Depends(visitor)):
    with transaction(True) as conn:
        project = service.project(conn, pid, user["id"])
        service.mutable(conn)
        if project["kind"] not in {"web", "game"}:
            service.error(400, "publication_unsupported", "当前支持发布网站和游戏")
        current = owner_publication(conn, pid)
        if data.expected_revision != (current["revision"] if current else 0):
            service.error(409, "publication_conflict", "发布状态已更新，请确认最新状态后重试")

        if data.action == "publish":
            version = service.owned_version(conn, pid, data.version_id)
            report = json.loads(version["validation_json"])
            if report.get("ready") is not True or json.loads(version["raw_json"]).get("schema_version") not in {"1", "2"}:
                service.error(400, "version_not_publishable", "请选择已通过运行检查的正式版本")
            if current is None:
                execute(conn, """INSERT INTO publications(project_id,slug,version_id,published,revision)
                    VALUES(:pid,:slug,:vid,1,1)""", pid=pid, slug=uid(), vid=data.version_id)
            elif current["version_id"] != data.version_id:
                execute(conn, """UPDATE publications SET previous_version_id=version_id,version_id=:vid,
                    published=1,revision=revision+1 WHERE project_id=:pid""", pid=pid, vid=data.version_id)
            elif not current["published"]:
                execute(conn, """UPDATE publications SET published=1,revision=revision+1
                    WHERE project_id=:pid""", pid=pid)
        elif not current:
            service.error(404, "publication_not_found", "作品尚未发布")
        elif data.action == "unpublish":
            execute(conn, """UPDATE publications SET published=0,revision=revision+1
                WHERE project_id=:pid AND published=1""", pid=pid)
        else:
            if not current["published"] or not current["previous_version_id"]:
                service.error(409, "publication_rollback_unavailable", "当前没有可回滚的发布版本")
            execute(conn, """UPDATE publications SET version_id=previous_version_id,previous_version_id=version_id,
                revision=revision+1 WHERE project_id=:pid""", pid=pid)
        return {"publication": owner_publication(conn, pid)}


def public_snapshot(conn, slug, *, compiled=False):
    fields = ", a.compiled_json" if compiled else ""
    row = one(conn, """SELECT p.published,p.revision,v.title,a.digest""" + fields + """
        FROM publications p JOIN versions v ON v.id=p.version_id AND v.project_id=p.project_id
        JOIN artifacts a ON a.id=v.artifact_id WHERE p.slug=:slug""", slug=slug)
    if not row:
        service.error(404, "publication_not_found", "找不到这个作品")
    if not row["published"]:
        service.error(410, "publication_unpublished", "这个作品已下架")
    return row


@router.get("/api/v1/publications/{slug}")
def public_ticket(slug: str):
    with transaction() as conn:
        row = public_snapshot(conn, slug)
    payload = {"publication": slug, "revision": row["revision"], "digest": row["digest"],
               "instance_id": uid(), "channel_nonce": uid() + uid(), "exp": time.time() + 120, "read_only": False}
    return {"title": row["title"], "instance_id": payload["instance_id"], "channel_nonce": payload["channel_nonce"],
            "read_only": False, "url": "/sandbox/publications/" + slug + "?ticket=" + ticket_encode(payload)}


@router.get("/sandbox/publications/{slug}", response_class=HTMLResponse)
def public_sandbox(slug: str, request: Request, ticket: str = ""):
    if request.headers.get("sec-fetch-dest") != "iframe" or request.headers.get("sec-fetch-site") != "same-origin":
        service.error(403, "iframe_only", "请通过作品链接打开")
    payload = ticket_decode(ticket)
    if payload.get("publication") != slug:
        service.error(403, "invalid_preview", "预览凭证不匹配")
    with transaction() as conn:
        row = public_snapshot(conn, slug, compiled=True)
        if row["revision"] != payload.get("revision") or row["digest"] != payload.get("digest"):
            service.error(409, "publication_changed", "作品已更新，请重新打开链接")
    return HTMLResponse(render_document(json.loads(row["compiled_json"]), payload), headers={"Content-Security-Policy": csp()})
