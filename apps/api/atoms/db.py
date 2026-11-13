import json
import time
from contextlib import contextmanager
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import NullPool
from .config import settings

engine = create_engine(settings().database_url, poolclass=NullPool, connect_args={"check_same_thread": False, "timeout": 5})


@event.listens_for(engine, "connect")
def setup_connection(conn, _):
    conn.isolation_level = None
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA synchronous=FULL")
    mode=cursor.execute("PRAGMA journal_mode").fetchone()[0]
    if mode not in {"delete","memory"}:
        raise RuntimeError("本项目要求 SQLite DELETE journal mode，请离线切换后启动")
    cursor.close()


@event.listens_for(engine, "begin")
def begin_connection(conn):
    conn.exec_driver_sql("BEGIN IMMEDIATE" if conn.get_execution_options().get("write_lock") else "BEGIN")


@contextmanager
def transaction(write=False):
    with engine.connect().execution_options(write_lock=write) as conn:
        with conn.begin():
            yield conn


def execute(conn, sql, **params):
    return conn.execute(text(sql), params)


def one(conn, sql, **params):
    row = execute(conn, sql, **params).mappings().first()
    return dict(row) if row else None


def all_rows(conn, sql, **params):
    return [dict(row) for row in execute(conn, sql, **params).mappings()]


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def add_event(conn, run_id, kind, payload):
    seq = one(conn, "SELECT COALESCE(MAX(seq),0)+1 AS n FROM run_events WHERE run_id=:id", id=run_id)["n"]
    execute(conn, "INSERT INTO run_events(run_id,seq,type,payload,created_at) VALUES(:id,:seq,:kind,:payload,:now)",
            id=run_id, seq=seq, kind=kind, payload=compact(payload), now=time.time())
    return seq


def maintenance(conn):
    row = one(conn, "SELECT value FROM system_settings WHERE key='maintenance'")
    return settings().read_only_mode or bool(row and row["value"] == "true")
