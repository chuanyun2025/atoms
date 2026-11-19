"""Media reservations and settlement in the platform wallet."""

import time
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from atoms.billing.amounts import SCALE, amount
from atoms.billing.credits import CreditError, wallet
from atoms.billing.passcodes import (
    authorize_paid_action,
    hold_passcode_units,
    release_passcode_units,
    settle_passcode_units,
)
from atoms.core.config import settings
from atoms.core.db import execute, one
from atoms.core.security_ids import uid

# Official Q3 Pro standard (not off-peak) rates, verified 2026-11-13:
# https://platform.vidu.cn/docs/overview/pricing
VIDEO_RATES = {"540p": 9, "720p": 20, "1080p": 24}
LEGACY_Q4_RATES = {"540p": 9, "720p": 19, "1080p": 24, "2K": 38, "4K": 78}
PLATFORM_CREDITS_PER_YUAN = 10
VIDEO_PRICE = 100
VIDEO_PRICE_UNITS = VIDEO_PRICE * SCALE


def convert(provider_credits, price, *, whole_credits=True):
    exact_credits = Decimal(provider_credits) * Decimal(price) * PLATFORM_CREDITS_PER_YUAN
    if whole_credits:
        return int(exact_credits.to_integral_value(rounding=ROUND_CEILING)) * SCALE
    return int((exact_credits * SCALE).to_integral_value(rounding=ROUND_HALF_UP))


def call_cost_units(call, provider_credits):
    if call["fixed_price"]:
        return call["reserved_units"]
    return convert(provider_credits, call["credit_price_cny"], whole_credits=bool(call["whole_credit_billing"]))


def estimated_usage(model, resolution, duration):
    return (LEGACY_Q4_RATES if model == "viduq4-preview" else VIDEO_RATES)[resolution] * duration


def quote(duration):
    cfg = settings()
    return {
        "credits": amount(VIDEO_PRICE_UNITS),
        "required_units": VIDEO_PRICE_UNITS,
        "model": cfg.vidu_model,
        "resolution": cfg.vidu_resolution,
        "duration": duration,
    }


def reserve(conn, run_id, owner, purpose, provider_credits):
    price = settings().vidu_credit_price_cny
    fixed_price = purpose == "video"
    held = VIDEO_PRICE_UNITS if fixed_price else convert(provider_credits, price)
    passcode_id, _ = authorize_paid_action(conn, owner, minimum_units=held, video=True)
    if wallet(conn, owner)["available_units"] < held:
        raise CreditError("insufficient_credits", f"可用积分不足，本次生成需要 {amount(held)} 积分")
    call_id = uid()
    now = time.time()
    execute(
        conn,
        """INSERT INTO media_calls(id,visitor_id,run_id,active_run_id,purpose,status,reserved_units,
        estimated_provider_credits,credit_price_cny,passcode_id,created_at,whole_credit_billing,fixed_price)
        VALUES(:id,:owner,:run,:run,:purpose,'reserved',:held,:estimate,:price,:passcode,:now,1,:fixed)""",
        id=call_id,
        owner=owner,
        run=run_id,
        purpose=purpose,
        held=held,
        estimate=provider_credits,
        price=str(price),
        passcode=passcode_id,
        now=now,
        fixed=fixed_price,
    )
    execute(
        conn,
        "UPDATE credit_wallets SET held_units=held_units+:held,updated_at=:now WHERE visitor_id=:owner",
        held=held,
        now=now,
        owner=owner,
    )
    hold_passcode_units(conn, passcode_id, held)
    return call_id


def reuse(conn, call_id, run_id, owner):
    call = one(conn, "SELECT * FROM media_calls WHERE id=:id AND visitor_id=:owner", id=call_id, owner=owner)
    if call and call["status"] != "released":
        execute(conn, "UPDATE media_calls SET active_run_id=:run WHERE id=:id", run=run_id, id=call_id)
        return call_id
    return None


def start(conn, call_id, run):
    current = one(conn, "SELECT * FROM runs WHERE id=:id", id=run["id"])
    if (
        not current
        or current["status"] != "running"
        or current["lease_token"] != run["lease_token"]
        or current["lease_until"] <= time.time()
    ):
        raise CreditError("CALL_LEASE_LOST", "任务执行者已失效，未发送生成请求")
    call = one(
        conn,
        "SELECT * FROM media_calls WHERE id=:id AND visitor_id=:owner AND active_run_id=:run",
        id=call_id,
        owner=run["owner_id"],
        run=run["id"],
    )
    if not call or call["status"] == "released":
        raise CreditError("MEDIA_AUTHORIZATION_MISSING", "媒体任务缺少有效积分预授权")
    if call["status"] == "reserved":
        execute(conn, "UPDATE media_calls SET status='in_flight' WHERE id=:id", id=call_id)


def settle(conn, call_id, provider_credits):
    row = one(conn, "SELECT * FROM media_calls WHERE id=:id", id=call_id)
    if not row:
        raise CreditError("MEDIA_CALL_MISSING", "媒体用量记录不存在")
    if row["status"] == "settled":
        if (
            not row["fixed_price"]
            and provider_credits is not None
            and row["actual_provider_credits"] != provider_credits
        ):
            raise CreditError("USAGE_CONFLICT", "该媒体任务已按其他用量结算")
        return
    if row["status"] == "released":
        raise CreditError("CALL_RELEASED", "媒体预授权已释放，请核对后再结算")
    if type(provider_credits) is not int or provider_credits < 0:
        if not row["fixed_price"]:
            execute(
                conn, "UPDATE media_calls SET status='uncertain',error_code='MISSING_USAGE' WHERE id=:id", id=call_id
            )
            return
        provider_credits = None
    cost = call_cost_units(row, provider_credits)
    if cost > row["reserved_units"]:
        execute(
            conn,
            "UPDATE media_calls SET status='uncertain',actual_provider_credits=:actual,error_code='USAGE_EXCEEDS_AUTHORIZATION' WHERE id=:id",
            id=call_id,
            actual=provider_credits,
        )
        return
    now = time.time()
    execute(
        conn,
        """UPDATE credit_wallets SET balance_units=balance_units-:cost,held_units=held_units-:held,
        spent_units=spent_units+:cost,updated_at=:now WHERE visitor_id=:owner""",
        cost=cost,
        held=row["reserved_units"],
        now=now,
        owner=row["visitor_id"],
    )
    execute(
        conn,
        "UPDATE media_calls SET status='settled',actual_provider_credits=:actual,settled_at=:now,error_code=NULL WHERE id=:id",
        actual=provider_credits,
        now=now,
        id=call_id,
    )
    settle_passcode_units(conn, row.get("passcode_id"), row["reserved_units"], cost)
    execute(
        conn,
        """INSERT INTO credit_ledger(id,visitor_id,event_key,kind,amount_units,run_id,media_call_id,created_at)
        VALUES(:id,:owner,:event,'media_consumption',:cost,:run,:call,:now)""",
        id=uid(),
        owner=row["visitor_id"],
        event="media:" + call_id,
        cost=-cost,
        run=row["run_id"],
        call=call_id,
        now=now,
    )


def release(conn, call_id, code):
    row = one(conn, "SELECT * FROM media_calls WHERE id=:id", id=call_id)
    if not row or row["status"] in {"settled", "released"}:
        return
    now = time.time()
    execute(
        conn,
        "UPDATE credit_wallets SET held_units=held_units-:held,updated_at=:now WHERE visitor_id=:owner",
        held=row["reserved_units"],
        now=now,
        owner=row["visitor_id"],
    )
    execute(
        conn,
        "UPDATE media_calls SET status='released',settled_at=:now,error_code=:code WHERE id=:id",
        now=now,
        code=code,
        id=call_id,
    )
    release_passcode_units(conn, row.get("passcode_id"), row["reserved_units"])
    execute(
        conn,
        """INSERT INTO credit_ledger(id,visitor_id,event_key,kind,amount_units,run_id,media_call_id,created_at)
        VALUES(:id,:owner,:event,'release',0,:run,:call,:now) ON CONFLICT(visitor_id,event_key) DO NOTHING""",
        id=uid(),
        owner=row["visitor_id"],
        event="media-release:" + call_id,
        run=row["run_id"],
        call=call_id,
        now=now,
    )


def finish_run(conn, run_id, code):
    from atoms.core.db import all_rows

    for call in all_rows(
        conn, "SELECT * FROM media_calls WHERE active_run_id=:run AND status IN ('reserved','in_flight')", run=run_id
    ):
        if call["status"] == "reserved":
            release(conn, call["id"], code)
        else:
            execute(
                conn,
                "UPDATE media_calls SET status='uncertain',error_code=:code WHERE id=:id",
                code=code,
                id=call["id"],
            )
