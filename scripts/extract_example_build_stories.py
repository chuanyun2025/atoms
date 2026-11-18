"""Extract sanitized real BuildStory records from a local SQLite backup into shared example snapshots.

Usage:
    python scripts/extract_example_build_stories.py --db backups/local-before-publication-20261114-081554/atoms.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_ROOT = REPO_ROOT / "shared"
WEB_STORIES_PATH = REPO_ROOT / "apps" / "web" / "src" / "publishedBuildStories.json"

SCALE = Decimal(1_000_000)
STAGE_LABELS = {
    "researching": "检索同类作品与玩法参考",
    "planning": "主 Agent 规划实现方案",
    "plan_ready": "构建计划已整理",
    "generating": "生成工程源码",
    "validating": "静态契约与产物结构检查",
    "browser_check": "隔离 Chromium 启动与交互验收",
    "repairing": "触发自动修复",
    "reviewing": "主 Agent 复核源码与浏览器证据",
    "failed": "本轮校验未通过（保留候选待续）",
    "completed": "通过验收并保存不可变版本",
}
SKIPPED_EVENTS = frozenset({"accepted", "read_context", "source_ready", "preview_ready", "committing"})


def _rendering_stack(artifact: dict, validation: dict) -> str:
    schema_ver = str(artifact.get("schema_version") or "1")
    if schema_ver == "1":
        if validation.get("slide_renderer"):
            return f"HTML5 · CSS3 · ES2022 JavaScript · {validation['slide_renderer']}"
        return "HTML5 · CSS3 · ES2022 JavaScript"
    plan = validation.get("task_plan") if isinstance(validation.get("task_plan"), dict) else {}
    rendering = plan.get("rendering")
    if rendering == "threejs":
        return "React · TypeScript · Three.js (WebGL)"
    if rendering == "canvas2d":
        return "React · TypeScript · Canvas 2D"
    return "React · TypeScript · DOM"


def extract_story_for_snapshot(conn: sqlite3.Connection, snapshot: dict) -> dict:
    digest = snapshot["compiled"]["digest"]
    artifact = snapshot["artifact"]
    version_row = conn.execute(
        """SELECT v.id AS vid, v.source_run_id, a.validation_json
        FROM versions v
        JOIN artifacts a ON a.id = v.artifact_id
        WHERE a.digest = ?
        ORDER BY v.created_at DESC LIMIT 1""",
        (digest,),
    ).fetchone()
    if not version_row:
        raise RuntimeError(f"No version found in database for compiled digest {digest}")

    validation = json.loads(version_row["validation_json"] or "{}")
    chain = []
    cur_run_id = version_row["source_run_id"]
    while cur_run_id:
        run_row = conn.execute("SELECT * FROM runs WHERE id = ?", (cur_run_id,)).fetchone()
        if not run_row:
            break
        chain.append(run_row)
        cur_run_id = run_row["retry_of_run_id"]
    if not chain:
        raise RuntimeError(f"No source run chain found for digest {digest}")
    chain.reverse()

    run_ids = [r["id"] for r in chain]
    placeholders = ",".join("?" * len(run_ids))

    elapsed_seconds = round(
        sum(
            max(0.0, float(r["finished_at"]) - float(r["started_at"]))
            for r in chain
            if r["started_at"] is not None and r["finished_at"] is not None
        ),
        2,
    )

    calls = conn.execute(
        f"""SELECT status, input_tokens, output_tokens
        FROM model_calls
        WHERE run_id IN ({placeholders})
        ORDER BY created_at ASC, attempt ASC""",
        run_ids,
    ).fetchall()
    settled_calls = [c for c in calls if c["status"] == "settled"]
    input_tokens = sum(int(c["input_tokens"] or 0) for c in settled_calls)
    output_tokens = sum(int(c["output_tokens"] or 0) for c in settled_calls)

    ledger_units = int(
        conn.execute(
            f"""SELECT COALESCE(SUM(-amount_units), 0) AS u
            FROM credit_ledger
            WHERE run_id IN ({placeholders}) AND kind IN ('consumption', 'media_consumption')""",
            run_ids,
        ).fetchone()["u"]
    )
    credits_str = format(Decimal(ledger_units) / SCALE, ".6f")

    stages = []
    repair_rounds = 0
    for run_idx, r in enumerate(chain, start=1):
        evs = conn.execute(
            "SELECT type, payload FROM run_events WHERE run_id = ? ORDER BY seq ASC",
            (r["id"],),
        ).fetchall()
        for ev in evs:
            ev_type = ev["type"]
            if ev_type in SKIPPED_EVENTS:
                continue
            payload = json.loads(ev["payload"] or "{}")
            message = str(payload.get("message") or "").strip()
            if ev_type == "repairing":
                repair_rounds += 1
            stage_item: dict = {
                "phase": ev_type,
                "label": STAGE_LABELS.get(ev_type, ev_type),
                "detail": message[:240] if message else STAGE_LABELS.get(ev_type, ev_type),
            }
            if len(chain) > 1:
                stage_item["runIndex"] = run_idx
            diag = payload.get("diagnostic") if isinstance(payload.get("diagnostic"), dict) else None
            if ev_type == "failed" and payload.get("code"):
                stage_item["diagnostic"] = {
                    "code": str(payload["code"]),
                    "detail": message[:280],
                }
            elif diag and diag.get("code"):
                loc = diag.get("file") or ""
                if loc and diag.get("line"):
                    loc = f"{loc}:{diag['line']}"
                stage_item["diagnostic"] = {
                    "code": str(diag["code"]),
                    **({"location": loc} if loc else {}),
                    "detail": str(diag.get("subject") or message)[:280],
                }
            stages.append(stage_item)

    raw_plan = validation.get("task_plan") if isinstance(validation.get("task_plan"), dict) else {}
    plan_summary = str(raw_plan.get("visual_direction") or artifact.get("summary") or "").strip()
    requirements = [str(item) for item in (raw_plan.get("requirements") or [])[:4] if isinstance(item, str)]

    return {
        "source": "atoms-sqlite-run-archive-v1",
        "compiledDigest": digest,
        "originalPrompt": str(chain[0]["prompt"]).strip(),
        "planSummary": plan_summary,
        "requirements": requirements,
        "rendering": _rendering_stack(artifact, validation),
        "architecture": sorted(artifact.get("files", {}).keys()),
        "runCount": len(chain),
        "elapsedSeconds": elapsed_seconds,
        "modelCalls": len(settled_calls),
        "repairRounds": repair_rounds,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "credits": credits_str,
        "stages": stages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract sanitized real BuildStory records for published examples")
    parser.add_argument(
        "--db",
        default=str(REPO_ROOT / "backups" / "local-before-publication-20261114-081554" / "atoms.db"),
        help="Path to SQLite database containing original example build runs",
    )
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.is_file():
        raise SystemExit(f"Database file not found: {db_path}")

    uri = db_path.as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row

    web_bundle: dict[str, dict] = {}
    try:
        for subdir in ("published-examples", "game-examples"):
            for json_path in sorted((SHARED_ROOT / subdir).glob("*.json")):
                data = json.loads(json_path.read_text(encoding="utf-8"))
                story = extract_story_for_snapshot(conn, data)
                data["build_story"] = story
                json_path.write_text(
                    json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )
                web_bundle[json_path.stem] = story
                print(
                    f"Extracted {json_path.stem}: runs={story['runCount']} elapsed={story['elapsedSeconds']}s "
                    f"calls={story['modelCalls']} repairs={story['repairRounds']} credits={story['credits']}"
                )
    finally:
        conn.close()

    WEB_STORIES_PATH.write_text(
        json.dumps(dict(sorted(web_bundle.items())), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(web_bundle)} real build stories to {WEB_STORIES_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
