"""Model billing and wallet accounting in units of 0.000001 credit."""

import time

from atoms.billing.amounts import SCALE, amount, ceil_credit_units
from atoms.billing.passcodes import (
    authorize_paid_action,
    hold_passcode_units,
    public_guardrail_status,
    release_passcode_units,
    settle_passcode_units,
)
from atoms.core.db import all_rows, execute, one, transaction
from atoms.core.security_ids import uid

WELCOME_CREDITS = 50
WELCOME = WELCOME_CREDITS * SCALE
INPUT_RATE = 20
OUTPUT_RATE = 80


class CreditError(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def model_cost_units(input_tokens: int, output_tokens: int, *, whole_credits: bool) -> int:
    raw_units = input_tokens * INPUT_RATE + output_tokens * OUTPUT_RATE
    return ceil_credit_units(raw_units) if whole_credits else raw_units


def ensure_wallet(conn, visitor_id):
    now = time.time()
    execute(
        conn,
        """INSERT INTO credit_wallets(visitor_id,balance_units,created_at,updated_at)
    VALUES(:id,:grant,:now,:now) ON CONFLICT(visitor_id) DO NOTHING""",
        id=visitor_id,
        grant=WELCOME,
        now=now,
    )
    execute(
        conn,
        """INSERT INTO credit_ledger(id,visitor_id,event_key,kind,amount_units,created_at)
    VALUES(:id,:owner,'welcome','welcome',:grant,:now) ON CONFLICT(visitor_id,event_key) DO NOTHING""",
        id=uid(),
        owner=visitor_id,
        grant=WELCOME,
        now=now,
    )


def wallet(conn, visitor_id):
    row = one(conn, "SELECT * FROM credit_wallets WHERE visitor_id=:id", id=visitor_id)
    if not row:
        raise CreditError("WALLET_MISSING", "积分账户尚未初始化，请刷新页面")
    return {
        "visitor_id": visitor_id,
        "balance": amount(row["balance_units"]),
        "held": amount(row["held_units"]),
        "available": amount(row["balance_units"] - row["held_units"]),
        "spent": amount(row["spent_units"]),
        "balance_units": row["balance_units"],
        "held_units": row["held_units"],
        "available_units": row["balance_units"] - row["held_units"],
        "welcome_credits": WELCOME_CREDITS,
        "credits_per_yuan": 10,
        "pricing": {"input_per_million": 20, "output_per_million": 80},
        "guardrails": public_guardrail_status(conn, visitor_id),
    }


def transactions(conn, visitor_id, before=None):
    rows = all_rows(
        conn,
        """SELECT l.id,l.kind,l.amount_units,l.input_tokens,l.output_tokens,l.run_id,l.call_id,l.created_at,
    m.purpose AS media_purpose FROM credit_ledger l LEFT JOIN media_calls m ON m.id=l.media_call_id
    WHERE l.visitor_id=:owner AND (:before IS NULL OR l.created_at<:before)
    ORDER BY l.created_at DESC,l.id DESC LIMIT 50""",
        owner=visitor_id,
        before=before,
    )
    for row in rows:
        row["amount"] = amount(row["amount_units"])
    pending = all_rows(
        conn,
        """SELECT id,run_id,attempt,CASE WHEN dispatch_pending=1 THEN 'reserved' ELSE status END AS status,
    reserved_units,error_code,created_at
    FROM model_calls WHERE visitor_id=:owner AND status IN ('in_flight','uncertain') ORDER BY created_at DESC LIMIT 100""",
        owner=visitor_id,
    )
    for row in pending:
        row["reserved"] = amount(row["reserved_units"])
    media = all_rows(
        conn,
        """SELECT id,run_id,status,reserved_units,error_code,created_at,purpose FROM media_calls
        WHERE visitor_id=:owner AND status IN ('reserved','in_flight','uncertain') ORDER BY created_at DESC LIMIT 100""",
        owner=visitor_id,
    )
    for row in media:
        row["reserved"] = amount(row["reserved_units"])
        row["category"] = "media"
    pending = sorted(pending + media, key=lambda item: item["created_at"], reverse=True)[:100]
    return {"items": rows, "pending": pending, "next_before": rows[-1]["created_at"] if len(rows) == 50 else None}


def require_balance(conn, visitor_id, prompt_bytes: int = 0):
    balance = wallet(conn, visitor_id)
    minimum = ceil_credit_units(max(INPUT_RATE + OUTPUT_RATE, prompt_bytes * INPUT_RATE + OUTPUT_RATE))
    if balance["available_units"] < minimum:
        raise CreditError("insufficient_credits", "可用积分不足，无法继续生成；已有项目仍可查看和导出")
    authorize_paid_action(conn, visitor_id, minimum_units=minimum, video=False)


def reserve_call(run, attempt, input_ceiling, provider_output_limit):
    now = time.time()
    with transaction(True) as conn:
        current = one(conn, "SELECT * FROM runs WHERE id=:id", id=run["id"])
        if (
            not current
            or current["status"] != "running"
            or current["lease_token"] != run["lease_token"]
            or current["lease_until"] <= now
        ):
            raise CreditError("CALL_LEASE_LOST", "任务执行者已失效，未发送模型请求")
        if one(
            conn, "SELECT id FROM model_calls WHERE run_id=:run AND attempt=:attempt", run=run["id"], attempt=attempt
        ):
            raise CreditError("CALL_ALREADY_STARTED", "该次模型请求已执行，不自动重复发送")
        available = wallet(conn, run["owner_id"])["available_units"]
        input_hold = input_ceiling * INPUT_RATE
        min_hold = ceil_credit_units(input_hold + OUTPUT_RATE)
        if available < min_hold:
            raise CreditError("insufficient_credits", "可用积分不足以预授权本次输入和输出，请查看积分明细")
        passcode_id, pool_cap = authorize_paid_action(
            conn, run["owner_id"], minimum_units=min_hold, video=False, now=now
        )
        effective_available = min(available, pool_cap) if pool_cap is not None else available
        max_hold = (effective_available // SCALE) * SCALE
        if max_hold < min_hold:
            raise CreditError("insufficient_credits", "可用积分不足以预授权本次输入和输出，请查看积分明细")
        output_limit = min(provider_output_limit, (max_hold - input_hold) // OUTPUT_RATE)
        if output_limit < 1:
            raise CreditError("insufficient_credits", "可用积分不足以预授权本次输入和输出，请查看积分明细")
        held = ceil_credit_units(input_hold + output_limit * OUTPUT_RATE)
        call = {
            "id": uid(),
            "visitor_id": run["owner_id"],
            "run_id": run["id"],
            "attempt": attempt,
            "lease_token": run["lease_token"],
            "reserved_units": held,
            "input_ceiling": input_ceiling,
            "output_limit": output_limit,
            "passcode_id": passcode_id,
        }
        execute(
            conn,
            """INSERT INTO model_calls(id,visitor_id,run_id,attempt,lease_token,status,dispatch_pending,reserved_units,
        input_ceiling,output_limit,passcode_id,created_at,whole_credit_billing)
        VALUES(:id,:owner,:run,:attempt,:lease,'in_flight',1,:held,:input,:output,:passcode,:now,1)""",
            id=call["id"],
            owner=call["visitor_id"],
            run=call["run_id"],
            attempt=attempt,
            lease=call["lease_token"],
            held=held,
            input=input_ceiling,
            output=output_limit,
            passcode=passcode_id,
            now=now,
        )
        execute(
            conn,
            "UPDATE credit_wallets SET held_units=held_units+:held,updated_at=:now WHERE visitor_id=:id",
            held=held,
            now=now,
            id=call["visitor_id"],
        )
        hold_passcode_units(conn, passcode_id, held)
        return call


def start_call(call):
    with transaction(True) as conn:
        now = time.time()
        changed = execute(
            conn,
            """UPDATE model_calls SET dispatch_pending=0
            WHERE id=:id AND run_id=:run AND lease_token=:lease AND status='in_flight' AND dispatch_pending=1
              AND EXISTS(SELECT 1 FROM runs WHERE id=:run AND status='running' AND lease_token=:lease AND lease_until>:now)""",
            id=call["id"],
            run=call["run_id"],
            lease=call["lease_token"],
            now=now,
        )
        if changed.rowcount:
            execute(conn, "UPDATE runs SET model_calls=model_calls+1 WHERE id=:id", id=call["run_id"])
            return
        pending = one(
            conn,
            """SELECT * FROM model_calls WHERE id=:id AND lease_token=:lease
            AND status='in_flight' AND dispatch_pending=1""",
            id=call["id"],
            lease=call["lease_token"],
        )
        if pending:
            _release_call(conn, pending, "CALL_LEASE_LOST")
    raise CreditError("CALL_LEASE_LOST", "任务已停止或请求状态已变化，未发送模型请求")


def settle_call(call, input_tokens, output_tokens, provider_request_id=None, operator=False):
    if type(input_tokens) is not int or type(output_tokens) is not int or min(input_tokens, output_tokens) < 0:
        raise CreditError("INVALID_USAGE", "模型用量无效，需核对")
    with transaction(True) as conn:
        row = one(conn, "SELECT * FROM model_calls WHERE id=:id", id=call["id"])
        if not row or (not operator and row["lease_token"] != call["lease_token"]):
            raise CreditError("CALL_IDENTITY", "积分调用标识不匹配")
        cost = model_cost_units(input_tokens, output_tokens, whole_credits=bool(row["whole_credit_billing"]))
        if row["status"] == "settled":
            if (row["input_tokens"], row["output_tokens"]) != (input_tokens, output_tokens):
                raise CreditError("USAGE_CONFLICT", "该调用已按不同用量结算")
            return amount(cost)
        if row["status"] == "released":
            raise CreditError("CALL_RELEASED", "该调用已释放，请先人工核对")
        if row["dispatch_pending"]:
            raise CreditError("CALL_NOT_DISPATCHED", "模型请求尚未发送")
        if input_tokens > row["input_ceiling"] or output_tokens > row["output_limit"] or cost > row["reserved_units"]:
            execute(
                conn,
                "UPDATE model_calls SET status='uncertain',input_tokens=:input,output_tokens=:output,error_code='USAGE_EXCEEDS_AUTHORIZATION' WHERE id=:id",
                input=input_tokens,
                output=output_tokens,
                id=row["id"],
            )
            # Commit the hold as uncertain; do not charge untrusted excessive usage.
            exceeded = True
        else:
            exceeded = False
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
                """UPDATE model_calls SET status='settled',input_tokens=:input,output_tokens=:output,
            provider_request_id=:request,settled_at=:now,error_code=NULL WHERE id=:id""",
                input=input_tokens,
                output=output_tokens,
                request=(provider_request_id or "")[:200],
                now=now,
                id=row["id"],
            )
            settle_passcode_units(conn, row.get("passcode_id"), row["reserved_units"], cost)
            execute(
                conn,
                """INSERT INTO credit_ledger(id,visitor_id,event_key,kind,amount_units,input_tokens,output_tokens,run_id,call_id,created_at)
            VALUES(:id,:owner,:key,'consumption',:amount,:input,:output,:run,:call,:now)""",
                id=uid(),
                owner=row["visitor_id"],
                key="call:" + row["id"],
                amount=-cost,
                input=input_tokens,
                output=output_tokens,
                run=row["run_id"],
                call=row["id"],
                now=now,
            )
    if exceeded:
        raise CreditError("USAGE_EXCEEDS_AUTHORIZATION", "模型用量超过预授权，积分暂冻结待核对")
    return amount(cost)


def finish_unbilled(call, code, uncertain=False, operator=False):
    with transaction(True) as conn:
        row = one(conn, "SELECT * FROM model_calls WHERE id=:id", id=call["id"])
        if not row or (not operator and row["lease_token"] != call["lease_token"]):
            raise CreditError("CALL_IDENTITY", "积分调用标识不匹配")
        if row["status"] in {"settled", "released"}:
            return
        if uncertain and not row["dispatch_pending"]:
            execute(
                conn, "UPDATE model_calls SET status='uncertain',error_code=:code WHERE id=:id", code=code, id=row["id"]
            )
            return
        _release_call(conn, row, code)


def _release_call(conn, row, code):
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
        "UPDATE model_calls SET status='released',dispatch_pending=0,error_code=:code,settled_at=:now WHERE id=:id",
        code=code,
        now=now,
        id=row["id"],
    )
    release_passcode_units(conn, row.get("passcode_id"), row["reserved_units"])
    execute(
        conn,
        """INSERT INTO credit_ledger(id,visitor_id,event_key,kind,amount_units,run_id,call_id,created_at)
    VALUES(:id,:owner,:key,'release',0,:run,:call,:now) ON CONFLICT(visitor_id,event_key) DO NOTHING""",
        id=uid(),
        owner=row["visitor_id"],
        key="release:" + row["id"],
        run=row["run_id"],
        call=row["id"],
        now=now,
    )


def finish_model_calls(conn, run_id, code):
    for row in all_rows(
        conn, "SELECT * FROM model_calls WHERE run_id=:id AND status='in_flight' AND dispatch_pending=1", id=run_id
    ):
        _release_call(conn, row, code)
    execute(
        conn,
        """UPDATE model_calls SET status='uncertain',error_code=:code
        WHERE run_id=:id AND status='in_flight' AND dispatch_pending=0""",
        code=code,
        id=run_id,
    )
