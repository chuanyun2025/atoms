import asyncio
import json
from pathlib import Path

import pytest
from conftest import create_project

from atoms.core.db import one, transaction
from atoms.runtime.evals import (
    DEFAULT_CASES_PATH,
    compare_eval_reports,
    load_eval_cases,
    render_comparison_markdown,
    render_eval_markdown,
    run_eval_suite,
    sanitize_eval_report,
)


def test_eval_catalog_covers_all_required_categories_with_at_least_twenty_cases():
    cases = load_eval_cases(DEFAULT_CASES_PATH)
    assert len(cases) >= 20
    categories = {item["category"] for item in cases}
    assert {
        "web_stateful",
        "web_data_snapshot",
        "slides_template",
        "game_2d",
        "game_3d",
        "iterative_patch",
    } <= categories


def test_live_eval_requires_explicit_billing_confirmation():
    with pytest.raises(ValueError, match="confirm-live-billing"):
        asyncio.run(run_eval_suite(fixture=False, confirm_live_billing=False, limit=1))


def test_eval_runner_isolates_database_scrubs_secrets_and_compares_two_runs(client, tmp_path: Path):
    existing = create_project(client)
    with transaction() as conn:
        projects_before = one(conn, "SELECT COUNT(*) AS n FROM projects")["n"]
        runs_before = one(conn, "SELECT COUNT(*) AS n FROM runs")["n"]

    subset = ["web-budget-lucide", "patch-counter-step5"]
    seen_first_case = {"count": 0}

    async def baseline_validator(artifact, run_id, preview_kind="web", lightweight_3d=False):
        files = artifact.get("files") or {}
        if "lucide-react" in files.get("src/App.tsx", "") and seen_first_case["count"] == 0:
            seen_first_case["count"] += 1
            return {
                "ok": False,
                "error": "Simulated compile failure at http://validator:9000/internal/validate",
                "diagnostic": {"code": "COMPILE_ERROR", "file": "src/App.tsx", "line": 3},
            }
        return {
            "ok": True,
            "compiled": {
                "body_html": '<div id="root"></div>',
                "css_base64": "YmxvY2t7fQ==",
                "js_base64": "Y29uc29sZS5sb2coMSk=",
                "digest": "eval-digest-" + str(len(files)),
                "compiler_version": "2",
                "sdk_version": "1",
            },
            "report": {"ready": True, "acceptance": "startup", "sandbox_enabled": True},
        }

    baseline = asyncio.run(
        run_eval_suite(
            label="model-v1-baseline",
            case_ids=subset,
            fixture=True,
            validate_fn=baseline_validator,
        )
    )
    candidate = asyncio.run(
        run_eval_suite(
            label="model-v2-candidate",
            case_ids=subset,
            fixture=True,
        )
    )

    with transaction() as conn:
        projects_after = one(conn, "SELECT COUNT(*) AS n FROM projects")["n"]
        runs_after = one(conn, "SELECT COUNT(*) AS n FROM runs")["n"]
        still_exists = one(conn, "SELECT id FROM projects WHERE id=:id", id=existing["id"])
    assert projects_after == projects_before
    assert runs_after == runs_before
    assert still_exists is not None

    assert baseline["summary"]["total_cases"] == 2
    assert baseline["summary"]["delivery_rate"] == 1.0
    assert baseline["summary"]["first_round_compile_pass_rate"] == 0.5
    assert baseline["summary"]["diagnostic_distribution"] == {"COMPILE_ERROR": 1}

    assert candidate["summary"]["first_round_compile_pass_rate"] == 1.0
    assert candidate["summary"]["avg_repair_rounds"] == 0.0

    diff = compare_eval_reports(baseline, candidate)
    assert diff["summary_delta"]["delta_first_round_compile_pass_rate"] == 0.5
    assert diff["summary_delta"]["delta_avg_repair_rounds"] < 0
    verdicts = {item["id"]: item["verdict"] for item in diff["case_diffs"]}
    assert verdicts["web-budget-lucide"] == "improved"
    assert verdicts["patch-counter-step5"] == "unchanged"

    md = render_comparison_markdown(baseline, candidate)
    assert "model-v1-baseline" in md and "model-v2-candidate" in md
    assert "**improved**" in md

    scrubbed = sanitize_eval_report(
        {
            "visitor_id": "secret-visitor",
            "note": "Authorization: Bearer super-secret-token and sk-1234567890abcdef and http://provider-gateway:8100/v1",
        }
    )
    assert "visitor_id" not in scrubbed
    assert "super-secret-token" not in scrubbed["note"]
    assert "sk-1234567890abcdef" not in scrubbed["note"]
    assert "provider-gateway" not in scrubbed["note"]

    base_file = tmp_path / "base.json"
    cand_file = tmp_path / "cand.json"
    md_file = tmp_path / "compare.md"
    base_file.write_text(json.dumps(baseline), encoding="utf-8")
    cand_file.write_text(json.dumps(candidate), encoding="utf-8")

    import importlib.util

    spec = importlib.util.spec_from_file_location("run_eval_cli", DEFAULT_CASES_PATH.parent / "run_eval.py")
    assert spec and spec.loader
    cli_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli_mod)
    rc = cli_mod.main(["compare", str(base_file), str(cand_file), "--markdown", str(md_file)])
    assert rc == 0
    assert md_file.is_file()
    assert "核心指标回归对比" in md_file.read_text(encoding="utf-8")
    assert "Atoms Eval Report" in render_eval_markdown(candidate)


def test_eval_runner_continuously_renews_worker_and_active_run_leases(monkeypatch):
    from atoms.runtime import worker

    real_heartbeat = worker.heartbeat
    seen_active_leases = []

    def spy_heartbeat(token, active_leases=(), capabilities=None):
        if active_leases:
            seen_active_leases.append(tuple(active_leases))
        return real_heartbeat(token, active_leases, capabilities)

    monkeypatch.setattr(worker, "heartbeat", spy_heartbeat)

    orig_wait_for = asyncio.wait_for

    async def fast_pulse_wait(coro, timeout):
        return await orig_wait_for(coro, 0.05 if timeout == 5.0 else timeout)

    monkeypatch.setattr(asyncio, "wait_for", fast_pulse_wait)

    report = asyncio.run(
        run_eval_suite(
            label="lease-pulse-check",
            case_ids=["web-kanban-storage"],
            fixture=True,
        )
    )
    assert report["summary"]["delivery_rate"] == 1.0
    assert len(seen_active_leases) >= 1
