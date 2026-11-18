"""Public daily budget circuit breaker and hashed visitor passcodes (FR-025 / FR-026)."""

import hashlib
import secrets
import time
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from atoms.core.config import settings
from atoms.core.db import all_rows, execute, maintenance, one, transaction
from atoms.core.security import enforce_rate_limit, error
from atoms.core.security_ids import uid

SCALE = 1_000_000
_FALLBACK_OFFSETS = {
    "Asia/Shanghai": timezone(timedelta(hours=8), name="CST"),
    "UTC": UTC,
}


def _fmt_credits(units: int) -> str:
    return format(Decimal(units) / SCALE, ".6f")


def _resolve_tz(name: str):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return _FALLBACK_OFFSETS.get(name, _FALLBACK_OFFSETS["Asia/Shanghai"])


def day_window(now: float | None = None, tz_name: str | None = None) -> tuple[float, float, str]:
    ts = time.time() if now is None else now
    tz = _resolve_tz(tz_name or settings().public_budget_timezone)
    local_now = datetime.fromtimestamp(ts, tz=tz)
    start_dt = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = start_dt + timedelta(days=1)
    label = end_dt.strftime("%Y-%m-%d %H:%M") + f" ({tz_name or settings().public_budget_timezone})"
    return start_dt.timestamp(), end_dt.timestamp(), label


def normalize_passcode(raw: str) -> str:
    return raw.strip().upper()


def hash_passcode(raw: str) -> str:
    return hashlib.sha256(("passcode:" + normalize_passcode(raw)).encode("utf-8")).hexdigest()


def generate_raw_passcode() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    part1 = "".join(secrets.choice(alphabet) for _ in range(4))
    part2 = "".join(secrets.choice(alphabet) for _ in range(4))
    return f"ATOMS-{part1}-{part2}"


def create_passcode(
    conn,
    *,
    label: str,
    credits: Decimal | int | str,
    max_visitors: int = 1,
    bypass_daily_budget: bool = True,
    allow_video: bool = True,
    expires_in_days: float | None = None,
    raw_code: str | None = None,
) -> dict:
    clean_label = label.strip()
    if not clean_label or len(clean_label) > 120:
        raise ValueError("口令标签不能为空且不超过 120 字")
    budget_units = int((Decimal(str(credits)) * SCALE).quantize(Decimal(1)))
    if budget_units <= 0:
        raise ValueError("口令额度必须大于 0")
    if max_visitors < 0:
        raise ValueError("最大绑定访客数不能为负数")
    plaintext = normalize_passcode(raw_code) if raw_code else generate_raw_passcode()
    if len(plaintext) < 6 or len(plaintext) > 64:
        raise ValueError("口令长度需在 6 到 64 位之间")
    code_digest = hash_passcode(plaintext)
    if one(conn, "SELECT id FROM passcodes WHERE code_hash=:h", h=code_digest):
        raise ValueError("相同口令已存在")
    now = time.time()
    expires_at = now + float(expires_in_days) * 86400 if expires_in_days is not None else None
    pid = uid()
    execute(
        conn,
        """INSERT INTO passcodes(
            id, label, code_hash, budget_units, spent_units, held_units,
            max_visitors, bypass_daily_budget, allow_video, expires_at, revoked_at, created_at
        ) VALUES(:id, :label, :hash, :budget, 0, 0, :max_v, :bypass, :video, :exp, NULL, :now)""",
        id=pid,
        label=clean_label,
        hash=code_digest,
        budget=budget_units,
        max_v=max_visitors,
        bypass=1 if bypass_daily_budget else 0,
        video=1 if allow_video else 0,
        exp=expires_at,
        now=now,
    )
    return {
        "id": pid,
        "code": plaintext,
        "label": clean_label,
        "budget": _fmt_credits(budget_units),
        "budget_units": budget_units,
        "max_visitors": max_visitors,
        "bypass_daily_budget": bypass_daily_budget,
        "allow_video": allow_video,
        "expires_at": expires_at,
    }


def list_passcodes(conn) -> list[dict]:
    now = time.time()
    rows = all_rows(
        conn,
        """SELECT p.*, (SELECT COUNT(*) FROM visitor_passcodes vp WHERE vp.passcode_id = p.id) AS bound_visitors
        FROM passcodes p ORDER BY p.created_at DESC""",
    )
    items = []
    for row in rows:
        remaining = max(0, row["budget_units"] - row["spent_units"] - row["held_units"])
        status = (
            "revoked"
            if row["revoked_at"] is not None
            else "expired"
            if row["expires_at"] is not None and row["expires_at"] <= now
            else "exhausted"
            if remaining <= 0
            else "active"
        )
        items.append(
            {
                "id": row["id"],
                "label": row["label"],
                "status": status,
                "budget": _fmt_credits(row["budget_units"]),
                "spent": _fmt_credits(row["spent_units"]),
                "held": _fmt_credits(row["held_units"]),
                "remaining": _fmt_credits(remaining),
                "bound_visitors": row["bound_visitors"],
                "max_visitors": row["max_visitors"],
                "bypass_daily_budget": bool(row["bypass_daily_budget"]),
                "allow_video": bool(row["allow_video"]),
                "expires_at": row["expires_at"],
                "revoked_at": row["revoked_at"],
                "created_at": row["created_at"],
            }
        )
    return items


def revoke_passcode(conn, passcode_id: str) -> bool:
    now = time.time()
    changed = execute(
        conn,
        "UPDATE passcodes SET revoked_at=:now WHERE id=:id AND revoked_at IS NULL",
        now=now,
        id=passcode_id,
    )
    return bool(changed.rowcount)


def public_daily_usage_units(conn, now: float | None = None) -> tuple[int, float, str]:
    ts = time.time() if now is None else now
    start, end, reset_label = day_window(ts)
    settled = one(
        conn,
        """SELECT COALESCE(SUM(-l.amount_units), 0) AS n
        FROM credit_ledger l
        LEFT JOIN model_calls mc ON mc.id = l.call_id
        LEFT JOIN media_calls mdc ON mdc.id = l.media_call_id
        LEFT JOIN passcodes p ON p.id = COALESCE(mc.passcode_id, mdc.passcode_id)
        WHERE l.kind IN ('consumption', 'media_consumption')
          AND l.created_at >= :start AND l.created_at < :end
          AND (p.id IS NULL OR p.bypass_daily_budget = 0)""",
        start=start,
        end=end,
    )["n"]
    held = one(
        conn,
        """SELECT (
          (SELECT COALESCE(SUM(mc.reserved_units), 0)
           FROM model_calls mc
           LEFT JOIN passcodes p ON p.id = mc.passcode_id
           WHERE (p.id IS NULL OR p.bypass_daily_budget = 0)
             AND mc.status IN ('in_flight', 'uncertain')
             AND mc.created_at < :end)
          +
          (SELECT COALESCE(SUM(mdc.reserved_units), 0)
           FROM media_calls mdc
           LEFT JOIN passcodes p ON p.id = mdc.passcode_id
           WHERE (p.id IS NULL OR p.bypass_daily_budget = 0)
             AND mdc.status IN ('reserved', 'in_flight', 'uncertain')
             AND mdc.created_at < :end)
        ) AS n""",
        end=end,
    )["n"]
    return int(settled) + int(held), end, reset_label


def visitor_passcode(conn, visitor_id: str, now: float | None = None) -> dict | None:
    ts = time.time() if now is None else now
    row = one(
        conn,
        """SELECT p.*, vp.bound_at
        FROM visitor_passcodes vp
        JOIN passcodes p ON p.id = vp.passcode_id
        WHERE vp.visitor_id = :vid AND vp.active = 1""",
        vid=visitor_id,
    )
    if not row:
        return None
    remaining = max(0, row["budget_units"] - row["spent_units"] - row["held_units"])
    status = (
        "revoked"
        if row["revoked_at"] is not None
        else "expired"
        if row["expires_at"] is not None and row["expires_at"] <= ts
        else "exhausted"
        if remaining <= 0
        else "active"
    )
    return {
        "id": row["id"],
        "label": row["label"],
        "status": status,
        "budget": _fmt_credits(row["budget_units"]),
        "spent": _fmt_credits(row["spent_units"]),
        "held": _fmt_credits(row["held_units"]),
        "remaining": _fmt_credits(remaining),
        "remaining_units": remaining,
        "bypass_daily_budget": bool(row["bypass_daily_budget"]),
        "allow_video": bool(row["allow_video"]),
        "expires_at": row["expires_at"],
    }


def public_guardrail_status(conn, visitor_id: str, now: float | None = None) -> dict:
    cfg = settings()
    ts = time.time() if now is None else now
    bound = visitor_passcode(conn, visitor_id, ts)
    budget_enabled = cfg.should_enforce_public_budget()
    cap_units = int((cfg.public_daily_budget_credits * SCALE).quantize(Decimal(1)))
    used_units, reset_at, reset_label = public_daily_usage_units(conn, ts)
    remaining_units = max(0, cap_units - used_units)
    active_passcode = bound and bound["status"] == "active"
    budget_reached = bool(
        budget_enabled and remaining_units <= 0 and not (active_passcode and bound["bypass_daily_budget"])
    )
    video_unlocked = bool(cfg.allows_public_video() or (active_passcode and bound["allow_video"]))
    return {
        "daily_budget_enabled": budget_enabled,
        "daily_budget_credits": _fmt_credits(cap_units),
        "daily_remaining_credits": _fmt_credits(remaining_units),
        "daily_budget_reached": budget_reached,
        "reset_at": reset_at,
        "reset_label": reset_label,
        "public_video_enabled": cfg.allows_public_video(),
        "video_unlocked": video_unlocked,
        "passcode": bound,
    }


def redeem_passcode(conn, visitor_id: str, raw_code: str, ip: str) -> dict:
    cfg = settings()
    clean = normalize_passcode(raw_code)
    if not clean or len(clean) > 64:
        error(422, "invalid_passcode", "请输入有效的体验口令")
    now = time.time()
    row = one(conn, "SELECT * FROM passcodes WHERE code_hash=:h", h=hash_passcode(clean))
    if not row:
        if cfg.should_rate_limit():
            enforce_rate_limit(conn, f"passcode_fail:{ip}", 10, 900, "体验口令尝试过于频繁，请稍后再试")
        error(404, "passcode_not_found", "体验口令无效，请核对后重试")
    if row["revoked_at"] is not None:
        error(403, "passcode_revoked", "该体验口令已被吊销")
    if row["expires_at"] is not None and row["expires_at"] <= now:
        error(403, "passcode_expired", "该体验口令已过期")
    remaining = row["budget_units"] - row["spent_units"] - row["held_units"]
    if remaining <= 0:
        error(402, "passcode_exhausted", "该体验口令额度已用完")

    already_bound = one(
        conn,
        "SELECT 1 FROM visitor_passcodes WHERE visitor_id=:vid AND passcode_id=:pid",
        vid=visitor_id,
        pid=row["id"],
    )
    if not already_bound and row["max_visitors"] > 0:
        bound_count = one(conn, "SELECT COUNT(*) AS n FROM visitor_passcodes WHERE passcode_id=:pid", pid=row["id"])[
            "n"
        ]
        if bound_count >= row["max_visitors"]:
            error(403, "passcode_visitor_limit", "该体验口令已达到可绑定人数上限")

    execute(conn, "UPDATE visitor_passcodes SET active=0 WHERE visitor_id=:vid", vid=visitor_id)
    execute(
        conn,
        """INSERT INTO visitor_passcodes(visitor_id, passcode_id, active, bound_at)
        VALUES(:vid, :pid, 1, :now)
        ON CONFLICT(visitor_id, passcode_id) DO UPDATE SET active=1, bound_at=:now""",
        vid=visitor_id,
        pid=row["id"],
        now=now,
    )
    # Ensure the visitor's personal wallet also has enough headroom to exercise the passcode quota.
    wallet_row = one(conn, "SELECT * FROM credit_wallets WHERE visitor_id=:vid", vid=visitor_id)
    if wallet_row:
        wallet_avail = wallet_row["balance_units"] - wallet_row["held_units"]
        if wallet_avail < remaining:
            topup = remaining - wallet_avail
            event_key = f"passcode:{row['id']}"
            inserted = execute(
                conn,
                """INSERT INTO credit_ledger(id, visitor_id, event_key, kind, amount_units, created_at)
                VALUES(:id, :vid, :key, 'passcode_grant', :amount, :now)
                ON CONFLICT(visitor_id, event_key) DO NOTHING""",
                id=uid(),
                vid=visitor_id,
                key=event_key,
                amount=topup,
                now=now,
            )
            if inserted.rowcount:
                execute(
                    conn,
                    "UPDATE credit_wallets SET balance_units=balance_units+:amount, updated_at=:now WHERE visitor_id=:vid",
                    amount=topup,
                    now=now,
                    vid=visitor_id,
                )
    return visitor_passcode(conn, visitor_id, now)


def redeem_passcode_request(visitor_id: str, raw_code: str, ip: str) -> dict:
    """Redeem a passcode in an atomic transaction while persisting failed-attempt rate limits."""
    from atoms.billing import credits

    cfg = settings()
    clean = normalize_passcode(raw_code)
    if not clean or len(clean) > 64:
        error(422, "invalid_passcode", "请输入有效的体验口令")

    not_found = False
    with transaction(True) as conn:
        if maintenance(conn):
            error(503, "maintenance", "系统维护中，暂时只读")
        row = one(conn, "SELECT id FROM passcodes WHERE code_hash=:h", h=hash_passcode(clean))
        if not row:
            if cfg.should_rate_limit():
                enforce_rate_limit(conn, f"passcode_fail:{ip}", 10, 900, "体验口令尝试过于频繁，请稍后再试")
            not_found = True
        else:
            redeem_passcode(conn, visitor_id, clean, ip)
            result = credits.wallet(conn, visitor_id)
    if not_found:
        error(404, "passcode_not_found", "体验口令无效，请核对后重试")
    return result


def detach_passcode(conn, visitor_id: str) -> None:
    execute(conn, "UPDATE visitor_passcodes SET active=0 WHERE visitor_id=:vid", vid=visitor_id)


def authorize_paid_action(
    conn,
    visitor_id: str,
    *,
    minimum_units: int,
    video: bool = False,
    now: float | None = None,
) -> tuple[str | None, int | None]:
    """Verify public daily budget / video gate or active passcode inside a write transaction."""
    from atoms.billing.credits import CreditError

    cfg = settings()
    ts = time.time() if now is None else now
    bound = visitor_passcode(conn, visitor_id, ts)
    if bound is not None:
        if bound["status"] == "revoked":
            raise CreditError("PASSCODE_REVOKED", "当前绑定的体验口令已被吊销，请更换或解除绑定")
        if bound["status"] == "expired":
            raise CreditError("PASSCODE_EXPIRED", "当前绑定的体验口令已过期，请更换或解除绑定")
        if bound["status"] == "exhausted" or bound["remaining_units"] < minimum_units:
            raise CreditError("PASSCODE_EXHAUSTED", "当前体验口令专项额度不足或已用完")
        if video and not bound["allow_video"] and not cfg.allows_public_video():
            raise CreditError("PUBLIC_VIDEO_DISABLED", "当前体验口令未开放视频生成权限")
        pool_cap = bound["remaining_units"]
        if not bound["bypass_daily_budget"] and cfg.should_enforce_public_budget():
            cap_units = int((cfg.public_daily_budget_credits * SCALE).quantize(Decimal(1)))
            used_units, _, reset_label = public_daily_usage_units(conn, ts)
            public_rem = max(0, cap_units - used_units)
            if public_rem < minimum_units:
                raise CreditError(
                    "PUBLIC_DAILY_BUDGET_REACHED",
                    f"今日全站公共体验额度已达上限，预计 {reset_label} 重置；已有项目预览、源码编辑和导出仍正常可用",
                )
            pool_cap = min(pool_cap, public_rem)
        return bound["id"], pool_cap

    if video and not cfg.allows_public_video():
        raise CreditError("PUBLIC_VIDEO_DISABLED", "公共环境默认关闭高成本视频生成，请输入体验口令解锁")

    if cfg.should_enforce_public_budget():
        cap_units = int((cfg.public_daily_budget_credits * SCALE).quantize(Decimal(1)))
        used_units, _, reset_label = public_daily_usage_units(conn, ts)
        public_rem = max(0, cap_units - used_units)
        if public_rem < minimum_units:
            raise CreditError(
                "PUBLIC_DAILY_BUDGET_REACHED",
                f"今日全站公共体验额度已达上限，预计 {reset_label} 重置；你仍可浏览作品、编辑已有项目源码或输入体验口令解锁",
            )
        return None, public_rem

    return None, None


def hold_passcode_units(conn, passcode_id: str | None, held_units: int) -> None:
    if passcode_id:
        execute(
            conn,
            "UPDATE passcodes SET held_units = held_units + :held WHERE id = :id",
            held=held_units,
            id=passcode_id,
        )


def settle_passcode_units(conn, passcode_id: str | None, held_units: int, cost_units: int) -> None:
    if passcode_id:
        execute(
            conn,
            "UPDATE passcodes SET held_units = MAX(0, held_units - :held), spent_units = spent_units + :cost WHERE id = :id",
            held=held_units,
            cost=cost_units,
            id=passcode_id,
        )


def release_passcode_units(conn, passcode_id: str | None, held_units: int) -> None:
    if passcode_id:
        execute(
            conn,
            "UPDATE passcodes SET held_units = MAX(0, held_units - :held) WHERE id = :id",
            held=held_units,
            id=passcode_id,
        )
