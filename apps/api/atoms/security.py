import base64
import hashlib
import hmac
import json
import secrets
import time
from fastapi import HTTPException, Request
from .config import settings
from .db import transaction, one, execute
from .security_ids import uid

COOKIE = "atoms_session"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def signed(value):
    return hmac.new(settings().session_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def csrf(token):
    return signed("csrf:" + token)


def origin_check(request: Request, require_csrf=True):
    if request.headers.get("origin") != settings().app_origin:
        raise HTTPException(403, detail={"code":"invalid_origin","message":"请求来源无效，请从工作台重试"})
    if request.headers.get("x-app-request") != "atoms" or request.headers.get("content-type","").split(";")[0] != "application/json":
        raise HTTPException(403, detail={"code":"invalid_request","message":"请求校验失败"})
    if require_csrf:
        token = request.cookies.get(COOKIE, "")
        if not token or not hmac.compare_digest(csrf(token),request.headers.get("x-csrf-token","")):
            raise HTTPException(403, detail={"code":"csrf_failed","message":"会话已变化，请刷新页面"})


def visitor(request: Request):
    token = request.cookies.get(COOKIE,"")
    with transaction() as conn:
        row = one(conn,"SELECT * FROM visitors WHERE token_hash=:hash AND expires_at>:now",hash=digest(token),now=time.time())
    if not token or not row:
        raise HTTPException(401, detail={"code":"session_expired","message":"会话已过期，请刷新页面"})
    return row


def create_session(request):
    from .credits import ensure_wallet
    origin_check(request,False)
    token = request.cookies.get(COOKIE,"")
    now = time.time()
    with transaction(True) as conn:
        row = one(conn,"SELECT * FROM visitors WHERE token_hash=:hash AND expires_at>:now",hash=digest(token),now=now)
        if not token or not row:
            token = secrets.token_urlsafe(32)
            row = {"id":uid(),"expires_at":now+30*86400}
            execute(conn,"INSERT INTO visitors(id,token_hash,created_at,expires_at) VALUES(:id,:hash,:now,:expires)",
                    id=row["id"],hash=digest(token),now=now,expires=row["expires_at"])
        ensure_wallet(conn,row["id"])
    return row, token


def ticket_encode(payload):
    data = base64.urlsafe_b64encode(json.dumps(payload,separators=(",",":")).encode()).decode().rstrip("=")
    return data + "." + signed("preview:" + data)


def ticket_decode(value):
    try:
        data, signature = value.split(".")
        if not hmac.compare_digest(signed("preview:"+data),signature):
            raise ValueError()
        payload = json.loads(base64.urlsafe_b64decode(data+"="*(-len(data)%4)))
        if payload["exp"] < time.time():
            raise ValueError()
        return payload
    except (ValueError, KeyError, TypeError):
        raise HTTPException(403,detail={"code":"preview_expired","message":"预览凭证已过期，请重新加载"})
