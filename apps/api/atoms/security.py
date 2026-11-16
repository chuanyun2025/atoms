import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
import time
from functools import lru_cache
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


@lru_cache(maxsize=16)
def _proxy_networks(cidrs: str):
    networks = []
    for item in cidrs.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    return tuple(networks)


_INTERNAL_PROXY_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def _parse_ip(raw: str):
    value = raw.strip()
    if value.startswith("[") and "]" in value:
        value = value[1:value.index("]")]
    elif value.count(":") == 1 and "." in value:
        value = value.split(":", 1)[0]
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return None
    return getattr(addr, "ipv4_mapped", None) or addr


def _is_trusted_proxy(addr, cfg) -> bool:
    if addr is None:
        return False
    if any(addr in network for network in _proxy_networks(cfg.trusted_proxy_cidrs)):
        return True
    if cfg.trust_private_proxies and any(addr in network for network in _INTERNAL_PROXY_NETWORKS):
        return True
    return False


def client_ip(request: Request) -> str:
    cfg = settings()
    forwarded = request.headers.get("x-real-ip", "").strip()
    host = request.client.host if request.client else ""
    peer = forwarded or host or "unknown"
    peer_addr = _parse_ip(peer)
    if _is_trusted_proxy(peer_addr, cfg):
        if cfg.trust_cf_connecting_ip:
            cf_ip = _parse_ip(request.headers.get("cf-connecting-ip", ""))
            if cf_ip is not None:
                return cf_ip.compressed[:64]
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            hops = [part.strip() for part in xff.split(",") if part.strip()]
            for hop in reversed(hops):
                hop_addr = _parse_ip(hop)
                if hop_addr is None:
                    break
                if not _is_trusted_proxy(hop_addr, cfg):
                    return hop_addr.compressed[:64]
    return (peer_addr.compressed if peer_addr is not None else peer)[:64]


def origin_check(request: Request, require_csrf=True):
    if request.headers.get("origin") != settings().app_origin:
        raise HTTPException(403, detail={"code":"invalid_origin","message":"请求来源无效，请从工作台重试"})
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if request.headers.get("x-app-request") != "atoms" or content_type != "application/json":
        raise HTTPException(403, detail={"code":"invalid_request","message":"请求校验失败"})
    if require_csrf:
        token = request.cookies.get(COOKIE, "")
        if not token or not hmac.compare_digest(csrf(token),request.headers.get("x-csrf-token","")):
            raise HTTPException(403, detail={"code":"csrf_failed","message":"会话已变化，请刷新页面"})


def _visitor_on(conn, token: str):
    if not token:
        raise HTTPException(401, detail={"code":"session_expired","message":"会话已过期，请刷新页面"})
    row = one(conn,"SELECT * FROM visitors WHERE token_hash=:hash AND expires_at>:now",hash=digest(token),now=time.time())
    if not row:
        raise HTTPException(401, detail={"code":"session_expired","message":"会话已过期，请刷新页面"})
    return row


def visitor(request: Request):
    token = request.cookies.get(COOKIE,"")
    if not token:
        raise HTTPException(401, detail={"code":"session_expired","message":"会话已过期，请刷新页面"})
    with transaction() as conn:
        return _visitor_on(conn, token)


def read_visitor(request: Request):
    token = request.cookies.get(COOKIE,"")
    if not token:
        raise HTTPException(401, detail={"code":"session_expired","message":"会话已过期，请刷新页面"})
    with transaction() as conn:
        yield _visitor_on(conn, token), conn


def create_session(request):
    from .credits import ensure_wallet
    from .service import enforce_rate_limit
    origin_check(request,False)
    token = request.cookies.get(COOKIE,"")
    now = time.time()
    ip = client_ip(request)
    cfg = settings()
    with transaction(True) as conn:
        row = one(conn,"SELECT * FROM visitors WHERE token_hash=:hash AND expires_at>:now",hash=digest(token),now=now)
        if not token or not row:
            if cfg.should_rate_limit():
                enforce_rate_limit(conn, f"session:{ip}", cfg.session_rate_limit_per_hour, 3600,
                                   "新建访客会话过于频繁，请稍后再试")
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
