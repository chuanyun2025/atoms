"""Offline generation quality benchmark runner and regression comparator (FR-029 / NFR-014)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config

from atoms import PACKAGE_ROOT, REPO_ROOT
from atoms.billing.amounts import SCALE, amount
from atoms.billing.credits import ensure_wallet
from atoms.core import config as core_config
from atoms.core import db as core_db
from atoms.core.schemas import ProjectCreate, RunCreate
from atoms.core.security_ids import uid
from atoms.runtime import service, worker

DEFAULT_CASES_PATH = REPO_ROOT / "evals" / "cases.json"
COMPILE_STAGE_CATEGORIES = frozenset({"artifact", "compile", "sandbox"})

_REDACT_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._\-+/=]+", re.I),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"https?://(?:provider-gateway|validator|127\.0\.0\.1|localhost)(?::\d+)?[^\s\"']*"),
)


def load_eval_cases(
    cases_path: Path | str = DEFAULT_CASES_PATH,
    *,
    case_ids: list[str] | None = None,
    category: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    payload = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    items = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError("Eval cases file must contain a non-empty 'cases' list")
    selected = list(items)
    if case_ids:
        wanted = set(case_ids)
        selected = [item for item in selected if item.get("id") in wanted]
    if category:
        selected = [item for item in selected if item.get("category") == category]
    if limit is not None and limit > 0:
        selected = selected[:limit]
    if not selected:
        raise ValueError("No benchmark cases matched the requested filter")
    return selected


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, math.ceil((pct / 100.0) * len(ordered)) - 1))
    return round(ordered[rank], 3)


def _offline_fixture_validator(artifact: dict, run_id: str, preview_kind: str = "web", lightweight_3d: bool = False):
    files = artifact.get("files") if isinstance(artifact, dict) else None
    if not isinstance(files, dict) or not files:
        return {
            "ok": False,
            "error": "Missing artifact files",
            "diagnostic": {"code": "ARTIFACT_SCHEMA_INVALID"},
        }
    schema_ver = str(artifact.get("schema_version") or "1")
    if schema_ver == "2" and ("src/App.tsx" not in files or "src/styles.css" not in files):
        return {
            "ok": False,
            "error": "React artifact requires src/App.tsx and src/styles.css",
            "diagnostic": {"code": "ARTIFACT_SCHEMA_INVALID", "file": "src/App.tsx"},
        }
    digest = hashlib.sha256(core_db.compact(artifact).encode("utf-8")).hexdigest()
    return {
        "ok": True,
        "compiled": {
            "body_html": '<div id="root"></div>',
            "css_base64": "YmxvY2t7fQ==",
            "js_base64": "Y29uc29sZS5sb2coMSk=",
            "digest": digest,
            "compiler_version": "2" if schema_ver == "2" else "1",
            "sdk_version": "1",
        },
        "report": {
            "ready": True,
            "acceptance": "startup",
            "sandbox_enabled": True,
        },
    }


def _seed_base_version(conn, project_id: str, base_artifact: dict) -> tuple[str, int]:
    now = time.time()
    seed_run_id = uid()
    owner_id = core_db.one(conn, "SELECT owner_id FROM projects WHERE id=:id", id=project_id)["owner_id"]
    core_db.execute(
        conn,
        """INSERT INTO runs(id,project_id,owner_id,prompt,base_version_id,expected_revision,status,stage,created_at,finished_at)
        VALUES(:id,:pid,:owner,'seed base version',NULL,0,'succeeded','completed',:now,:now)""",
        id=seed_run_id,
        pid=project_id,
        owner=owner_id,
        now=now,
    )
    project_row = core_db.one(conn, "SELECT * FROM projects WHERE id=:id", id=project_id)
    run_row = core_db.one(conn, "SELECT * FROM runs WHERE id=:id", id=seed_run_id)
    validation = _offline_fixture_validator(base_artifact, seed_run_id, project_row["kind"])
    vid, _ = service.write_version(conn, project_row, run_row, base_artifact, validation, now)
    updated = core_db.one(conn, "SELECT revision FROM projects WHERE id=:id", id=project_id)
    return vid, int(updated["revision"])


def _summarize_group(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(case_results)
    if total == 0:
        return {
            "total_cases": 0,
            "first_round_compile_pass_rate": 0.0,
            "first_round_startup_pass_rate": 0.0,
            "delivery_rate": 0.0,
            "avg_repair_rounds": 0.0,
            "avg_elapsed_seconds": 0.0,
            "p50_elapsed_seconds": 0.0,
            "p95_elapsed_seconds": 0.0,
            "avg_credits": "0",
            "total_credits": "0",
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "diagnostic_distribution": {},
        }
    compile_passes = sum(1 for item in case_results if item["first_round_compile_pass"])
    startup_passes = sum(1 for item in case_results if item["first_round_startup_pass"])
    delivered = sum(1 for item in case_results if item["delivered"])
    repairs = [item["repair_rounds"] for item in case_results]
    latencies = [item["elapsed_seconds"] for item in case_results]
    total_units = sum(int(item["settled_units"]) for item in case_results)
    in_tokens = sum(int(item["input_tokens"]) for item in case_results)
    out_tokens = sum(int(item["output_tokens"]) for item in case_results)
    diag_counter: Counter[str] = Counter()
    for item in case_results:
        for code in item["diagnostic_codes"]:
            diag_counter[code] += 1
    return {
        "total_cases": total,
        "first_round_compile_pass_rate": round(compile_passes / total, 4),
        "first_round_startup_pass_rate": round(startup_passes / total, 4),
        "delivery_rate": round(delivered / total, 4),
        "avg_repair_rounds": round(sum(repairs) / total, 3),
        "avg_elapsed_seconds": round(sum(latencies) / total, 3),
        "p50_elapsed_seconds": _percentile(latencies, 50),
        "p95_elapsed_seconds": _percentile(latencies, 95),
        "avg_credits": amount(round(total_units / total)),
        "total_credits": amount(total_units),
        "total_input_tokens": in_tokens,
        "total_output_tokens": out_tokens,
        "diagnostic_distribution": dict(sorted(diag_counter.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


def sanitize_eval_report(payload: Any) -> Any:
    secrets_to_scrub = [
        os.environ.get(name, "")
        for name in (
            "SESSION_SECRET",
            "SERVICE_TOKEN",
            "PROVIDER_GATEWAY_TOKEN",
            "LLM_API_KEY",
            "VIDU_API_KEY",
        )
        if len(os.environ.get(name, "")) >= 8
    ]
    if isinstance(payload, str):
        cleaned = payload
        for secret in secrets_to_scrub:
            cleaned = cleaned.replace(secret, "[REDACTED]")
        for pattern in _REDACT_PATTERNS:
            cleaned = pattern.sub("[REDACTED]", cleaned)
        return cleaned
    if isinstance(payload, list):
        return [sanitize_eval_report(item) for item in payload]
    if isinstance(payload, dict):
        return {
            key: sanitize_eval_report(value)
            for key, value in payload.items()
            if key not in {"visitor_id", "token_hash", "lease_token", "client_ip"}
        }
    return payload


async def run_eval_suite(
    *,
    label: str = "eval-run",
    cases_path: Path | str = DEFAULT_CASES_PATH,
    case_ids: list[str] | None = None,
    category: str | None = None,
    limit: int | None = None,
    fixture: bool = False,
    confirm_live_billing: bool = False,
    live_validator: bool = False,
    validate_fn=None,
    generate_fn=None,
) -> dict[str, Any]:
    if not fixture and not confirm_live_billing:
        raise ValueError(
            "Live evaluation incurs real LLM billing. Pass confirm_live_billing=True (--confirm-live-billing) "
            "or run with fixture=True (--fixture)."
        )
    cases = load_eval_cases(cases_path, case_ids=case_ids, category=category, limit=limit)

    saved_env = dict(os.environ)
    prev_engine = core_db.engine
    prev_validate = worker.validate_artifact
    prev_paid_generate = worker.paid_generate
    prev_agent_plan = worker.agent_plan

    with tempfile.TemporaryDirectory(prefix="atoms-eval-") as temp_root:
        db_file = Path(temp_root) / "eval.sqlite3"
        media_dir = Path(temp_root) / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        temp_db_url = "sqlite:///" + str(db_file).replace("\\", "/")

        try:
            os.environ["DATABASE_URL"] = temp_db_url
            os.environ["MEDIA_ROOT"] = str(media_dir)
            if fixture:
                os.environ["APP_ENV"] = "test"
                os.environ["TEST_FIXTURE"] = "true"
                os.environ.setdefault("SESSION_SECRET", "eval-isolated-session-secret-" * 3)
                os.environ.setdefault("SERVICE_TOKEN", "eval-isolated-service-token-" * 3)
                os.environ.setdefault("APP_ORIGIN", "http://localhost:8080")
            else:
                os.environ["TEST_FIXTURE"] = "false"

            core_config.settings.cache_clear()
            eval_engine = core_db.make_engine(temp_db_url)
            core_db.engine = eval_engine

            alembic_cfg = Config(str(PACKAGE_ROOT.parent / "alembic.ini"))
            alembic_cfg.set_main_option("script_location", str(PACKAGE_ROOT.parent / "migrations"))
            await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

            if validate_fn is not None:
                worker.validate_artifact = validate_fn
            elif fixture and not live_validator:

                async def _stub_validate(artifact, run_id, preview_kind="web", lightweight_3d=False):
                    return _offline_fixture_validator(artifact, run_id, preview_kind, lightweight_3d)

                worker.validate_artifact = _stub_validate

            if generate_fn is not None:
                worker.paid_generate = generate_fn

            if fixture:
                from atoms.domains.artifacts import strict_json
                from atoms.runtime.model_fixture import test_plan
                from atoms.runtime.orchestration import parse_plan

                async def _fixture_plan(run, context):
                    return parse_plan(strict_json(test_plan(context)), context=context)

                worker.agent_plan = _fixture_plan

            leader_token = "eval-leader-" + uid()
            await asyncio.to_thread(worker.acquire_leader, leader_token)
            capabilities = (
                None if fixture else {"text_configured": True, "video_configured": False, "text_model": label}
            )
            if capabilities is not None:
                await asyncio.to_thread(worker.heartbeat, leader_token, (), capabilities)

            active_leases: dict[str, str] = {}
            stop_pulse = asyncio.Event()

            async def _lease_pulse():
                while not stop_pulse.is_set():
                    try:
                        await asyncio.wait_for(stop_pulse.wait(), timeout=5.0)
                        break
                    except TimeoutError:
                        await asyncio.to_thread(
                            worker.heartbeat,
                            leader_token,
                            tuple(active_leases.items()),
                            capabilities,
                        )

            pulse_task = asyncio.create_task(_lease_pulse())

            case_results: list[dict[str, Any]] = []
            try:
                for case in cases:
                    owner = "eval-visitor-" + uid()
                    with core_db.transaction(True) as conn:
                        now = time.time()
                        core_db.execute(
                            conn,
                            "INSERT INTO visitors(id,token_hash,created_at,expires_at) VALUES(:id,:hash,:now,:exp)",
                            id=owner,
                            hash=uid() + uid(),
                            now=now,
                            exp=now + 86400,
                        )
                        ensure_wallet(conn, owner)
                        core_db.execute(
                            conn,
                            "UPDATE credit_wallets SET balance_units=:bal WHERE visitor_id=:id",
                            bal=50_000 * SCALE,
                            id=owner,
                        )
                        proj = service.create_project(
                            conn,
                            owner,
                            ProjectCreate(
                                client_key="eval-proj-" + case["id"],
                                title=case["title"],
                                kind=case["kind"],
                                slide_template_id=case.get("slide_template_id"),
                            ),
                        )
                        base_vid = None
                        expected_rev = 0
                        if isinstance(case.get("base_artifact"), dict):
                            base_vid, expected_rev = _seed_base_version(conn, proj["id"], case["base_artifact"])
                        run_public = service.create_run(
                            conn,
                            owner,
                            proj["id"],
                            RunCreate(
                                prompt=case["prompt"],
                                expected_revision=expected_rev,
                                base_version_id=base_vid,
                            ),
                            "eval-req-" + case["id"],
                            "127.0.0.1",
                        )

                    await asyncio.to_thread(
                        worker.heartbeat,
                        leader_token,
                        tuple(active_leases.items()),
                        capabilities,
                    )
                    claimed = await asyncio.to_thread(worker.claim, leader_token)
                    assert claimed and claimed["id"] == run_public["id"]
                    active_leases[claimed["id"]] = claimed["lease_token"]
                    t0 = time.perf_counter()
                    try:
                        await worker.execute_run(claimed)
                    except (worker.ModelError, service.CreditError) as err:
                        await worker.finish_failed_run(claimed, err.code, str(err))
                    except Exception as exc:
                        await worker.finish_failed_run(claimed, "INTERNAL_ERROR", str(exc))
                    finally:
                        active_leases.pop(claimed["id"], None)
                    elapsed = round(max(0.001, time.perf_counter() - t0), 3)

                    with core_db.transaction() as conn:
                        final_run = core_db.one(conn, "SELECT * FROM runs WHERE id=:id", id=claimed["id"])
                        events = core_db.all_rows(
                            conn, "SELECT type,payload FROM run_events WHERE run_id=:id ORDER BY seq", id=claimed["id"]
                        )
                        calls = core_db.all_rows(
                            conn,
                            """SELECT m.status,m.input_tokens,m.output_tokens,l.amount_units
                            FROM model_calls m
                            LEFT JOIN credit_ledger l ON l.call_id=m.id AND l.kind='consumption'
                            WHERE m.run_id=:id ORDER BY m.attempt""",
                            id=claimed["id"],
                        )

                    repair_events = []
                    saw_browser_before_repair = False
                    saw_repair = False
                    for ev in events:
                        if ev["type"] == "browser_check" and not saw_repair:
                            saw_browser_before_repair = True
                        elif ev["type"] == "repairing":
                            saw_repair = True
                            try:
                                repair_events.append(json.loads(ev["payload"]))
                            except ValueError:
                                repair_events.append({})

                    diag_codes: list[str] = []
                    first_repair_category = None
                    for idx, rep in enumerate(repair_events):
                        diag = rep.get("diagnostic") if isinstance(rep.get("diagnostic"), dict) else {}
                        code = diag.get("code")
                        if isinstance(code, str):
                            diag_codes.append(code)
                        if idx == 0:
                            first_repair_category = diag.get("category")

                    delivered = final_run["status"] == "succeeded" and bool(final_run["result_version_id"])
                    if not delivered and final_run.get("error_code"):
                        diag_codes.append(str(final_run["error_code"]))

                    if not repair_events and delivered:
                        first_compile_ok = True
                        first_startup_ok = True
                    elif repair_events:
                        first_compile_ok = (
                            saw_browser_before_repair and first_repair_category not in COMPILE_STAGE_CATEGORIES
                        )
                        first_startup_ok = False
                    else:
                        first_compile_ok = saw_browser_before_repair
                        first_startup_ok = False

                    in_tok = sum(int(c["input_tokens"] or 0) for c in calls if c["status"] == "settled")
                    out_tok = sum(int(c["output_tokens"] or 0) for c in calls if c["status"] == "settled")
                    settled_units = -sum(int(c["amount_units"] or 0) for c in calls if c["status"] == "settled")

                    case_results.append(
                        {
                            "id": case["id"],
                            "category": case["category"],
                            "kind": case["kind"],
                            "title": case["title"],
                            "status": final_run["status"],
                            "delivered": delivered,
                            "first_round_compile_pass": first_compile_ok,
                            "first_round_startup_pass": first_startup_ok,
                            "repair_rounds": len(repair_events),
                            "model_calls": len(calls),
                            "elapsed_seconds": elapsed,
                            "input_tokens": in_tok,
                            "output_tokens": out_tok,
                            "settled_units": settled_units,
                            "settled_credits": amount(settled_units),
                            "diagnostic_codes": diag_codes,
                            "error_code": final_run["error_code"],
                        }
                    )
            finally:
                stop_pulse.set()
                await pulse_task

            eval_engine.dispose()
        finally:
            worker.validate_artifact = prev_validate
            worker.paid_generate = prev_paid_generate
            worker.agent_plan = prev_agent_plan
            core_db.engine = prev_engine
            os.environ.clear()
            os.environ.update(saved_env)
            core_config.settings.cache_clear()

    categories = sorted({item["category"] for item in case_results})
    by_category = {
        cat: _summarize_group([item for item in case_results if item["category"] == cat]) for cat in categories
    }
    report = {
        "schema_version": "1",
        "label": label,
        "mode": "fixture" if fixture else "live",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": _summarize_group(case_results),
        "by_category": by_category,
        "cases": case_results,
    }
    return sanitize_eval_report(report)


def _pct(rate: float) -> str:
    return f"{rate * 100:.1f}%"


def render_eval_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        f"# Atoms Eval Report — `{report['label']}`",
        "",
        f"- **模式**: `{report['mode']}`",
        f"- **生成时间 (UTC)**: `{report['generated_at']}`",
        f"- **用例总数**: `{summary['total_cases']}`",
        "",
        "## 总体指标",
        "",
        "| 指标 | 结果 |",
        "| --- | --- |",
        f"| 首轮编译通过率 | {_pct(summary['first_round_compile_pass_rate'])} |",
        f"| 首轮浏览器启动通过率 | {_pct(summary['first_round_startup_pass_rate'])} |",
        f"| 最终交付成功率 | {_pct(summary['delivery_rate'])} |",
        f"| 平均自动修复轮次 | {summary['avg_repair_rounds']:.2f} |",
        f"| 平均耗时 / P50 / P95 | {summary['avg_elapsed_seconds']:.2f}s / {summary['p50_elapsed_seconds']:.2f}s / {summary['p95_elapsed_seconds']:.2f}s |",
        f"| 平均积分成本 / 总积分 | {summary['avg_credits']} / {summary['total_credits']} |",
        f"| 总输入 / 输出 Token | {summary['total_input_tokens']:,} / {summary['total_output_tokens']:,} |",
        "",
        "## 分类明细",
        "",
        "| 类别 | 用例数 | 首轮编译通过 | 首轮启动通过 | 最终交付率 | 平均修复轮次 | 平均积分 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for cat, stats in report.get("by_category", {}).items():
        lines.append(
            f"| `{cat}` | {stats['total_cases']} | {_pct(stats['first_round_compile_pass_rate'])} | "
            f"{_pct(stats['first_round_startup_pass_rate'])} | {_pct(stats['delivery_rate'])} | "
            f"{stats['avg_repair_rounds']:.2f} | {stats['avg_credits']} |"
        )
    lines.extend(["", "## 失败与修复诊断码分布", ""])
    dist = summary.get("diagnostic_distribution") or {}
    if dist:
        lines.extend(["| 诊断码 | 出现次数 |", "| --- | --- |"])
        for code, count in dist.items():
            lines.append(f"| `{code}` | {count} |")
    else:
        lines.append("全部用例零失败诊断。")
    lines.extend(
        [
            "",
            "## 逐条用例结果",
            "",
            "| 用例 ID | 类别 | 状态 | 首轮编译 | 首轮启动 | 修复轮次 | 耗时(s) | 积分 | 诊断码 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in report.get("cases", []):
        codes = ", ".join(item["diagnostic_codes"]) if item["diagnostic_codes"] else "-"
        lines.append(
            f"| `{item['id']}` | `{item['category']}` | {item['status']} | "
            f"{'PASS' if item['first_round_compile_pass'] else 'FAIL'} | "
            f"{'PASS' if item['first_round_startup_pass'] else 'FAIL'} | "
            f"{item['repair_rounds']} | {item['elapsed_seconds']:.2f} | {item['settled_credits']} | {codes} |"
        )
    return "\n".join(lines) + "\n"


def compare_eval_reports(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    b_sum = baseline["summary"]
    c_sum = candidate["summary"]
    base_cases = {item["id"]: item for item in baseline.get("cases", [])}
    cand_cases = {item["id"]: item for item in candidate.get("cases", [])}
    shared_ids = sorted(set(base_cases) & set(cand_cases))

    case_diffs = []
    for cid in shared_ids:
        b = base_cases[cid]
        c = cand_cases[cid]
        if not b["delivered"] and c["delivered"]:
            verdict = "improved"
        elif b["delivered"] and not c["delivered"]:
            verdict = "regressed"
        elif c["repair_rounds"] < b["repair_rounds"]:
            verdict = "improved"
        elif c["repair_rounds"] > b["repair_rounds"]:
            verdict = "regressed"
        else:
            verdict = "unchanged"
        case_diffs.append(
            {
                "id": cid,
                "category": c["category"],
                "verdict": verdict,
                "baseline_delivered": b["delivered"],
                "candidate_delivered": c["delivered"],
                "baseline_repairs": b["repair_rounds"],
                "candidate_repairs": c["repair_rounds"],
                "delta_repairs": c["repair_rounds"] - b["repair_rounds"],
                "baseline_credits": b["settled_credits"],
                "candidate_credits": c["settled_credits"],
            }
        )

    all_cats = sorted(set(baseline.get("by_category", {})) | set(candidate.get("by_category", {})))
    cat_diffs = {}
    for cat in all_cats:
        bc = baseline.get("by_category", {}).get(cat) or _summarize_group([])
        cc = candidate.get("by_category", {}).get(cat) or _summarize_group([])
        cat_diffs[cat] = {
            "baseline_delivery_rate": bc["delivery_rate"],
            "candidate_delivery_rate": cc["delivery_rate"],
            "delta_delivery_rate": round(cc["delivery_rate"] - bc["delivery_rate"], 4),
            "baseline_avg_repairs": bc["avg_repair_rounds"],
            "candidate_avg_repairs": cc["avg_repair_rounds"],
            "delta_avg_repairs": round(cc["avg_repair_rounds"] - bc["avg_repair_rounds"], 3),
        }

    return {
        "baseline_label": baseline.get("label", "baseline"),
        "candidate_label": candidate.get("label", "candidate"),
        "summary_delta": {
            "delta_first_round_compile_pass_rate": round(
                c_sum["first_round_compile_pass_rate"] - b_sum["first_round_compile_pass_rate"], 4
            ),
            "delta_first_round_startup_pass_rate": round(
                c_sum["first_round_startup_pass_rate"] - b_sum["first_round_startup_pass_rate"], 4
            ),
            "delta_delivery_rate": round(c_sum["delivery_rate"] - b_sum["delivery_rate"], 4),
            "delta_avg_repair_rounds": round(c_sum["avg_repair_rounds"] - b_sum["avg_repair_rounds"], 3),
            "delta_avg_elapsed_seconds": round(c_sum["avg_elapsed_seconds"] - b_sum["avg_elapsed_seconds"], 3),
            "delta_avg_credits": round(float(c_sum["avg_credits"]) - float(b_sum["avg_credits"]), 6),
        },
        "category_deltas": cat_diffs,
        "case_diffs": case_diffs,
    }


def _signed_pp(delta: float) -> str:
    sign = "+" if delta > 0 else ""
    return f"{sign}{delta * 100:.1f} pp"


def render_comparison_markdown(baseline: dict[str, Any], candidate: dict[str, Any]) -> str:
    diff = compare_eval_reports(baseline, candidate)
    b_sum = baseline["summary"]
    c_sum = candidate["summary"]
    d = diff["summary_delta"]
    lines = [
        f"# Atoms Eval 对比报告：`{diff['baseline_label']}` vs `{diff['candidate_label']}`",
        "",
        "## 核心指标回归对比",
        "",
        f"| 指标 | `{diff['baseline_label']}` | `{diff['candidate_label']}` | 变化 (Δ) |",
        "| --- | --- | --- | --- |",
        f"| 首轮编译通过率 | {_pct(b_sum['first_round_compile_pass_rate'])} | {_pct(c_sum['first_round_compile_pass_rate'])} | {_signed_pp(d['delta_first_round_compile_pass_rate'])} |",
        f"| 首轮启动通过率 | {_pct(b_sum['first_round_startup_pass_rate'])} | {_pct(c_sum['first_round_startup_pass_rate'])} | {_signed_pp(d['delta_first_round_startup_pass_rate'])} |",
        f"| 最终交付成功率 | {_pct(b_sum['delivery_rate'])} | {_pct(c_sum['delivery_rate'])} | {_signed_pp(d['delta_delivery_rate'])} |",
        f"| 平均修复轮次 | {b_sum['avg_repair_rounds']:.2f} | {c_sum['avg_repair_rounds']:.2f} | {d['delta_avg_repair_rounds']:+.2f} |",
        f"| 平均耗时 (s) | {b_sum['avg_elapsed_seconds']:.2f} | {c_sum['avg_elapsed_seconds']:.2f} | {d['delta_avg_elapsed_seconds']:+.2f}s |",
        f"| 平均积分成本 | {b_sum['avg_credits']} | {c_sum['avg_credits']} | {d['delta_avg_credits']:+g} |",
        "",
        "## 分类交付与修复对比",
        "",
        f"| 类别 | `{diff['baseline_label']}` 交付率 | `{diff['candidate_label']}` 交付率 | Δ 交付率 | Δ 平均修复轮次 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for cat, cd in diff["category_deltas"].items():
        lines.append(
            f"| `{cat}` | {_pct(cd['baseline_delivery_rate'])} | {_pct(cd['candidate_delivery_rate'])} | "
            f"{_signed_pp(cd['delta_delivery_rate'])} | {cd['delta_avg_repairs']:+.2f} |"
        )
    lines.extend(
        [
            "",
            "## 逐条用例回归差异",
            "",
            f"| 用例 ID | 类别 | 结论 | `{diff['baseline_label']}` (交付/修复) | `{diff['candidate_label']}` (交付/修复) |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for item in diff["case_diffs"]:
        lines.append(
            f"| `{item['id']}` | `{item['category']}` | **{item['verdict']}** | "
            f"{'PASS' if item['baseline_delivered'] else 'FAIL'} / {item['baseline_repairs']} | "
            f"{'PASS' if item['candidate_delivered'] else 'FAIL'} / {item['candidate_repairs']} |"
        )
    return "\n".join(lines) + "\n"
