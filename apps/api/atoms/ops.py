"""Offline operator commands. Never exposed by HTTP."""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from sqlalchemy.engine import make_url

from atoms.core.config import settings
from atoms.core.db import engine, execute, one, transaction
from atoms.core.security_ids import uid
from atoms.domains.media import asset_path

DISPATCH_SCHEMA = "0011_model_call_dispatch"
INDEX_SCHEMA = "0012_query_indexes"
PASSCODE_SCHEMA = "0013_public_budget_and_passcodes"
WHOLE_CREDIT_SCHEMA = "0014_whole_credit_billing"
CURRENT_SCHEMA = "0015_fixed_video_price"
SUPPORTED_SCHEMAS = {
    "0007",
    "0008",
    "0009",
    "0009_publish",
    "0010",
    DISPATCH_SCHEMA,
    INDEX_SCHEMA,
    PASSCODE_SCHEMA,
    WHOLE_CREDIT_SCHEMA,
    CURRENT_SCHEMA,
}


def database_path():
    return Path(make_url(settings().database_url).database).resolve()


def inspect_backup(path, media_directory=None):
    if not path.is_file():
        raise ValueError("备份文件不存在")
    with closing(sqlite3.connect("file:" + path.as_posix() + "?mode=ro", uri=True)) as source:
        if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("备份完整性检查失败")
        version = source.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        if version not in SUPPORTED_SCHEMAS:
            raise ValueError("备份数据库版本不受当前程序支持，请先核对对应代码版本")
        projects = source.execute("SELECT count(*) FROM projects").fetchone()[0]
        source.row_factory = sqlite3.Row
        assets = source.execute("SELECT id,mime_type,size_bytes,sha256 FROM media_assets").fetchall()
        for asset in assets:
            media = (media_directory or Path(str(path) + ".media")) / asset_path(dict(asset)).name
            if not media.is_file() or media.stat().st_size != asset["size_bytes"]:
                raise ValueError("备份缺少配套媒体文件，请同时保留 .media 目录")
            with media.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != asset["sha256"]:
                    raise ValueError("备份媒体文件校验失败")
    return {"integrity": "ok", "schema": version, "projects": projects}


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    maintenance = sub.add_parser("maintenance")
    maintenance.add_argument("mode", choices=["on", "off"])
    reconcile = sub.add_parser("credits-reconcile")
    reconcile.add_argument("call_id")
    reconcile.add_argument("--release", action="store_true")
    reconcile.add_argument("--input-tokens", type=int)
    reconcile.add_argument("--output-tokens", type=int)
    media = sub.add_parser("media-reconcile")
    media.add_argument("call_id")
    choice = media.add_mutually_exclusive_group(required=True)
    choice.add_argument("--release", action="store_true")
    choice.add_argument("--provider-credits", type=int)
    backup = sub.add_parser("backup")
    backup.add_argument("path", type=Path)
    restore = sub.add_parser("restore")
    restore.add_argument("path", type=Path)
    restore.add_argument("--offline", action="store_true")
    restore.add_argument("--confirm-restore", action="store_true")
    pc_create = sub.add_parser("passcode-create")
    pc_create.add_argument("--label", required=True)
    pc_create.add_argument("--credits", required=True)
    pc_create.add_argument("--max-visitors", type=int, default=1)
    pc_create.add_argument("--days", type=float, default=None)
    pc_create.add_argument("--code", default=None)
    pc_create.add_argument("--no-video", action="store_true")
    pc_create.add_argument("--no-bypass-budget", action="store_true")
    sub.add_parser("passcode-list")
    pc_revoke = sub.add_parser("passcode-revoke")
    pc_revoke.add_argument("passcode_id")
    args = parser.parse_args()
    if args.action == "passcode-create":
        from atoms.billing.passcodes import create_passcode

        with transaction(True) as conn:
            created = create_passcode(
                conn,
                label=args.label,
                credits=args.credits,
                max_visitors=args.max_visitors,
                bypass_daily_budget=not args.no_bypass_budget,
                allow_video=not args.no_video,
                expires_in_days=args.days,
                raw_code=args.code,
            )
        print(json.dumps(created, ensure_ascii=False))
        return
    if args.action == "passcode-list":
        from atoms.billing.passcodes import list_passcodes

        with transaction() as conn:
            print(json.dumps({"items": list_passcodes(conn)}, ensure_ascii=False, indent=2))
        return
    if args.action == "passcode-revoke":
        from atoms.billing.passcodes import revoke_passcode

        with transaction(True) as conn:
            if not revoke_passcode(conn, args.passcode_id):
                raise ValueError("体验口令不存在或已被吊销")
        print(f"revoked={args.passcode_id}")
        return
    if args.action == "media-reconcile":
        from atoms.billing import media_credits

        with transaction(True) as conn:
            call = one(
                conn,
                """SELECT m.*,r.status AS run_status FROM media_calls m
                JOIN runs r ON r.id=m.active_run_id WHERE m.id=:id""",
                id=args.call_id,
            )
            if not call or call["status"] != "uncertain" or call["run_status"] in {"pending", "running"}:
                raise ValueError("只允许核对已结束任务的 uncertain 媒体调用")
            if args.release:
                media_credits.release(conn, args.call_id, "OPERATOR_RELEASED")
            else:
                if (
                    args.provider_credits < 0
                    or media_credits.call_cost_units(call, args.provider_credits) > call["reserved_units"]
                ):
                    raise ValueError("账单用量无效或超出已授权金额，请人工核对")
                media_credits.settle(conn, args.call_id, args.provider_credits)
        print("媒体积分已核对，重复执行不会重复扣费")
        return
    if args.action == "credits-reconcile":
        from atoms.billing.credits import finish_unbilled, settle_call

        with transaction() as conn:
            call = one(conn, "SELECT * FROM model_calls WHERE id=:id", id=args.call_id)
        if not call or call["status"] != "uncertain":
            raise ValueError("只允许核对状态为 uncertain 的调用")
        if args.release:
            if args.input_tokens is not None or args.output_tokens is not None:
                raise ValueError("释放与按用量结算不能同时指定")
            finish_unbilled(call, "OPERATOR_RELEASED", operator=True)
            print("已释放待核对预授权")
        else:
            if args.input_tokens is None or args.output_tokens is None:
                raise ValueError("请填写供应商账单的输入、输出 token，或使用 --release")
            print("已按账单结算积分：" + settle_call(call, args.input_tokens, args.output_tokens, operator=True))
        return
    if args.action == "maintenance":
        with transaction(True) as conn:
            execute(
                conn,
                "INSERT INTO system_settings(key,value) VALUES('maintenance',:value) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                value="true" if args.mode == "on" else "false",
            )
        print("maintenance=" + args.mode)
        return
    path = args.path.resolve()
    db = database_path()
    if path == db:
        raise ValueError("备份路径不能指向在线数据库")
    if args.action == "backup":
        if not db.is_file() or path.exists():
            raise ValueError("数据库不存在，或目标备份已存在")
        path.parent.mkdir(parents=True, exist_ok=True)
        with (
            closing(sqlite3.connect("file:" + db.as_posix() + "?mode=ro", uri=True)) as source,
            closing(sqlite3.connect(path)) as target,
        ):
            source.backup(target, pages=128, sleep=0.05)
        with closing(sqlite3.connect(path)) as snapshot:
            snapshot.row_factory = sqlite3.Row
            assets = snapshot.execute("SELECT id,mime_type FROM media_assets").fetchall()
        media_backup = Path(str(path) + ".media")
        if assets:
            media_backup.mkdir()
        for asset in assets:
            original = asset_path(dict(asset))
            shutil.copyfile(original, media_backup / original.name)
        print(json.dumps(inspect_backup(path)))
        return
    report = inspect_backup(path)
    print(json.dumps({"dry_run": not args.confirm_restore, **report}))
    if not args.confirm_restore:
        return
    if not args.offline:
        raise ValueError("恢复要求停止 API、Worker 后传入 --offline")
    engine.dispose()
    if db.exists():
        with closing(sqlite3.connect(db)) as current:
            if current.execute("SELECT lease_until FROM worker_status WHERE id=1").fetchone()[0] > time.time():
                raise ValueError("Worker 租约仍有效，请停止服务并等待租约过期")
    temp = db.with_name(db.name + ".restore-tmp")
    if temp.exists():
        raise ValueError("存在未处理的恢复临时文件")
    with (
        closing(sqlite3.connect("file:" + path.as_posix() + "?mode=ro", uri=True)) as source,
        closing(sqlite3.connect(temp)) as target,
    ):
        source.backup(target)
        target.execute(
            "UPDATE worker_status SET lease_token=NULL,lease_until=0,heartbeat_at=0,state='offline',model_configured=0"
        )
        if report["schema"] != "0007":
            target.execute("UPDATE worker_status SET video_configured=0,text_model=NULL")
        if report["schema"] in {"0009", "0010", DISPATCH_SCHEMA, PASSCODE_SCHEMA, WHOLE_CREDIT_SCHEMA, CURRENT_SCHEMA}:
            target.execute("UPDATE run_workspace SET compiled_json=NULL,digest=NULL")
        if report["schema"] in {DISPATCH_SCHEMA, PASSCODE_SCHEMA, WHOLE_CREDIT_SCHEMA, CURRENT_SCHEMA}:
            now = time.time()
            pending = target.execute("""SELECT id,visitor_id,run_id,reserved_units FROM model_calls
                WHERE status='in_flight' AND dispatch_pending=1""").fetchall()
            for call_id, owner, run_id, held in pending:
                target.execute(
                    "UPDATE credit_wallets SET held_units=held_units-?,updated_at=? WHERE visitor_id=?",
                    (held, now, owner),
                )
                target.execute(
                    """INSERT INTO credit_ledger(id,visitor_id,event_key,kind,amount_units,run_id,call_id,created_at)
                    VALUES(?,?,?,'release',0,?,?,?)""",
                    (uid(), owner, "release:" + call_id, run_id, call_id, now),
                )
            target.execute(
                """UPDATE model_calls SET status='released',dispatch_pending=0,error_code='RESTORED_UNSENT',settled_at=?
                WHERE status='in_flight' AND dispatch_pending=1""",
                (now,),
            )
        target.execute(
            "UPDATE model_calls SET status='uncertain',error_code='RESTORED_WITHOUT_USAGE' WHERE status='in_flight'"
        )
        target.execute(
            "UPDATE media_calls SET status='uncertain',error_code='RESTORED_WITHOUT_USAGE' WHERE status='in_flight'"
        )
        target.execute(
            "INSERT INTO system_settings(key,value) VALUES('maintenance','true') ON CONFLICT(key) DO UPDATE SET value='true'"
        )
        target.commit()
    media_backup = Path(str(path) + ".media")
    inspect_backup(temp, media_directory=media_backup)
    with closing(sqlite3.connect(temp)) as snapshot:
        snapshot.row_factory = sqlite3.Row
        assets = snapshot.execute("SELECT id,mime_type FROM media_assets").fetchall()
    for asset in assets:
        destination = asset_path(dict(asset))
        destination.parent.mkdir(parents=True, exist_ok=True)
        pending = destination.with_suffix(".restore-part")
        if pending.exists():
            raise ValueError("存在未处理的媒体恢复临时文件")
        shutil.copyfile(media_backup / destination.name, pending)
        os.replace(pending, destination)
    os.replace(temp, db)
    print("恢复完成，保持维护模式；验证数据后再关闭维护模式")


if __name__ == "__main__":
    main()
