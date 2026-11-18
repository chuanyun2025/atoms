import asyncio
import io
import json
import zipfile

import pytest
from conftest import create_project, submit

from atoms import SHARED_ROOT
from atoms.core.db import compact
from atoms.domains.artifacts import merge_react_patch
from atoms.runtime import worker
from atoms.runtime.model import prepare
from atoms.runtime.preview import export_zip
from atoms.runtime.prompts import messages_for, supports_incremental_patch
from atoms.skills import skill_for


def _validation_ok(digest="digest-patch-test"):
    return {
        "ok": True,
        "compiled": {
            "body_html": '<div id="root"></div>',
            "css_base64": "YmxvY2t7fQ==",
            "js_base64": "Y29uc29sZS5sb2coMSk=",
            "digest": digest,
            "compiler_version": "2",
            "sdk_version": "1",
        },
        "report": {
            "ready": True,
            "acceptance": "startup",
            "sandbox_enabled": True,
        },
    }


def test_merge_react_patch_guards_protected_files_and_merges_deterministically():
    base = {
        "schema_version": "2",
        "title": "多模块看板",
        "summary": "初始版本",
        "files": {
            "src/App.tsx": "export default function App(){return <main>v1</main>}",
            "src/styles.css": "body{margin:0;color:#111}",
            "src/components/Card.tsx": "export function Card(){return <div>old</div>}",
            "src/components/Deprecated.tsx": "export const old = 1;",
        },
    }
    patch = {
        "schema_version": "2",
        "mode": "patch",
        "title": "多模块看板",
        "summary": "升级卡片组件并清理废弃文件",
        "files": {
            "src/components/Card.tsx": "export function Card(){return <div>new</div>}",
            "src/components/Badge.tsx": "export function Badge(){return <span>ok</span>}",
        },
        "deleted_files": ["src/components/Deprecated.tsx"],
    }
    merged = merge_react_patch(patch, base)
    assert "mode" not in merged
    assert "deleted_files" not in merged
    assert merged["files"]["src/App.tsx"] == base["files"]["src/App.tsx"]
    assert merged["files"]["src/styles.css"] == base["files"]["src/styles.css"]
    assert merged["files"]["src/components/Card.tsx"] == "export function Card(){return <div>new</div>}"
    assert merged["files"]["src/components/Badge.tsx"] == "export function Badge(){return <span>ok</span>}"
    assert "src/components/Deprecated.tsx" not in merged["files"]

    for protected in ("src/App.tsx", "src/styles.css"):
        with pytest.raises(ValueError, match="禁止删除"):
            merge_react_patch(
                {
                    "schema_version": "2",
                    "mode": "patch",
                    "title": "bad",
                    "summary": "bad",
                    "files": {},
                    "deleted_files": [protected],
                },
                base,
            )


def test_incremental_patch_falls_back_to_full_mode_on_import_or_repeated_errors():
    context = {
        "project_kind": "web",
        "site_format": "react",
        "request": "只把卡片圆角调大",
        "base_artifact": {
            "schema_version": "2",
            "title": "看板",
            "summary": "v1",
            "files": {
                "src/App.tsx": "export default function App(){return null}",
                "src/styles.css": "body{}",
                "src/components/Board.tsx": "export default function Board(){return null}",
            },
        },
    }
    assert supports_incremental_patch(context, None) is True
    prepared_initial = asyncio.run(prepare(context, None, skill=skill_for("web")))
    assert prepared_initial.incremental_react is True
    assert '"mode":"patch"' in prepared_initial.messages[0]["content"]

    import_repair = {"diagnostic": {"code": "COMPILE_IMPORT"}, "diagnostics": "Missing module"}
    assert supports_incremental_patch(context, import_repair) is False
    prepared_fallback = asyncio.run(prepare(context, import_repair, skill=skill_for("web")))
    assert prepared_fallback.incremental_react is False
    assert '禁止使用 mode:"patch"' in prepared_fallback.messages[0]["content"]

    repeated_repair = {"diagnostic": {"code": "COMPILE_ERROR"}, "repeated_failure": True, "diagnostics": "Type error"}
    assert supports_incremental_patch(context, repeated_repair) is False


def test_worker_executes_end_to_end_incremental_patch_and_preserves_untouched_modules(client, monkeypatch):
    validated_snapshots = []

    async def fake_validate(artifact, run_id, preview_kind="web", lightweight_3d=False):
        validated_snapshots.append(json.loads(compact(artifact)))
        result = _validation_ok(f"digest-{len(validated_snapshots)}")
        result["compiled"]["dependencies"] = ["react", "react-dom", "lucide-react"]
        return result

    monkeypatch.setattr(worker, "validate_artifact", fake_validate)

    v1_files = {
        "src/App.tsx": 'import Board from "./components/Board"; import {Sparkles} from "lucide-react"; export default function App(){return <main><Sparkles/><Board/></main>}',
        "src/styles.css": "body { margin: 0; background: #0f172a; }",
        "src/components/Board.tsx": "export default function Board(){return <section>V1</section>}",
        "src/components/UnusedOld.tsx": "export const legacy = true;",
        "src/data/items.json": '{"count": 3}',
    }

    responses = [
        compact(
            {
                "schema_version": "2",
                "title": "敏捷看板",
                "summary": "初始多文件版本",
                "files": v1_files,
            }
        ),
        compact(
            {
                "schema_version": "2",
                "mode": "patch",
                "title": "敏捷看板",
                "summary": "仅局部更新 Board 组件并移除废弃模块",
                "files": {
                    "src/components/Board.tsx": "export default function Board(){return <section>V2-PATCHED</section>}",
                },
                "deleted_files": ["src/components/UnusedOld.tsx"],
            }
        ),
    ]

    async def fake_paid_generate(run, context, repair, *, skill):
        return responses.pop(0)

    monkeypatch.setattr(worker, "paid_generate", fake_paid_generate)

    proj = create_project(client)
    r1 = submit(client, proj["id"], prompt="创建敏捷看板", request_key="patch-e2e-1")
    assert r1.status_code == 202
    asyncio.run(worker.execute_run(worker.claim("test-leader")))

    proj_after_v1 = client.get(f"/api/v1/projects/{proj['id']}").json()
    v1_id = proj_after_v1["current_version_id"]
    assert v1_id is not None

    r2 = submit(
        client,
        proj["id"],
        prompt="把看板标题改成 V2-PATCHED 并清理无用组件",
        revision=proj_after_v1["revision"],
        base=v1_id,
        request_key="patch-e2e-2",
    )
    assert r2.status_code == 202
    asyncio.run(worker.execute_run(worker.claim("test-leader")))

    proj_after_v2 = client.get(f"/api/v1/projects/{proj['id']}").json()
    v2_id = proj_after_v2["current_version_id"]
    assert v2_id != v1_id

    v2 = client.get(f"/api/v1/projects/{proj['id']}/versions/{v2_id}").json()
    saved_files = v2["artifact"]["files"]
    assert "mode" not in v2["artifact"]
    assert "deleted_files" not in v2["artifact"]
    assert saved_files["src/App.tsx"] == v1_files["src/App.tsx"]
    assert saved_files["src/styles.css"] == v1_files["src/styles.css"]
    assert saved_files["src/data/items.json"] == v1_files["src/data/items.json"]
    assert (
        saved_files["src/components/Board.tsx"]
        == "export default function Board(){return <section>V2-PATCHED</section>}"
    )
    assert "src/components/UnusedOld.tsx" not in saved_files

    exported = client.get(f"/api/v1/projects/{proj['id']}/versions/{v2_id}/export")
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        pkg = json.loads(archive.read("source/package.json").decode("utf-8"))
        assert "react" in pkg["dependencies"]
        assert "react-dom" in pkg["dependencies"]
        assert pkg["dependencies"].get("lucide-react") == "0.468.0"
        assert "three" not in pkg["dependencies"]


def test_lucide_react_is_whitelisted_in_react_prompts():
    msgs = messages_for(
        {"project_kind": "web", "site_format": "react", "request": "制作带图标的个人主页"},
        None,
        skill=skill_for("web"),
    )
    dep_line = next(line for line in msgs[0]["content"].splitlines() if line.startswith("只支持静态 import"))
    allowed = dep_line.split("；不支持", 1)[0]
    assert '"lucide-react"' in allowed


def test_repair_round_patch_preserves_earlier_file_modifications_from_same_run(client, monkeypatch):
    attempt_counter = {"n": 0}

    async def fake_validate(artifact, run_id, preview_kind="web", lightweight_3d=False):
        attempt_counter["n"] += 1
        if attempt_counter["n"] == 2:
            # Round 1 of v2 run: B.tsx has a compile error while A.tsx was already validly updated!
            assert artifact["files"]["src/components/A.tsx"] == "export const A = 'V2-UPDATED';"
            return {
                "ok": False,
                "error": "Syntax error in B.tsx",
                "diagnostic": {"code": "COMPILE_ERROR", "file": "src/components/B.tsx", "line": 1},
            }
        return _validation_ok(f"digest-repair-{attempt_counter['n']}")

    monkeypatch.setattr(worker, "validate_artifact", fake_validate)

    responses = [
        compact(
            {
                "schema_version": "2",
                "title": "双组件应用",
                "summary": "v1",
                "files": {
                    "src/App.tsx": "export default function App(){return <main>ok</main>}",
                    "src/styles.css": "body{margin:0}",
                    "src/components/A.tsx": "export const A = 'V1-OLD';",
                    "src/components/B.tsx": "export const B = 'V1-OLD';",
                },
            }
        ),
        compact(
            {
                "schema_version": "2",
                "mode": "patch",
                "title": "双组件应用",
                "summary": "同时更新 A 和 B",
                "files": {
                    "src/components/A.tsx": "export const A = 'V2-UPDATED';",
                    "src/components/B.tsx": "export const B = BROKEN;",
                },
            }
        ),
        compact(
            {
                "schema_version": "2",
                "mode": "patch",
                "title": "双组件应用",
                "summary": "修复 B 组件",
                "files": {
                    "src/components/B.tsx": "export const B = 'V2-FIXED';",
                },
            }
        ),
    ]

    async def fake_paid_generate(run, context, repair, *, skill):
        return responses.pop(0)

    monkeypatch.setattr(worker, "paid_generate", fake_paid_generate)

    proj = create_project(client)
    submit(client, proj["id"], prompt="创建初始版本", request_key="same-run-patch-1")
    asyncio.run(worker.execute_run(worker.claim("test-leader")))
    p1 = client.get(f"/api/v1/projects/{proj['id']}").json()

    submit(
        client,
        proj["id"],
        prompt="更新 A 和 B 组件",
        revision=p1["revision"],
        base=p1["current_version_id"],
        request_key="same-run-patch-2",
    )
    asyncio.run(worker.execute_run(worker.claim("test-leader")))

    p2 = client.get(f"/api/v1/projects/{proj['id']}").json()
    v2 = client.get(f"/api/v1/projects/{proj['id']}/versions/{p2['current_version_id']}").json()
    assert v2["artifact"]["files"]["src/components/A.tsx"] == "export const A = 'V2-UPDATED';"
    assert v2["artifact"]["files"]["src/components/B.tsx"] == "export const B = 'V2-FIXED';"


def test_legacy_react_zip_includes_full_runtime_allowlist():
    source = (
        r'import {Vector3} from "th\u0072ee";'
        "\nexport default function App(){return <p>{new Vector3().length()}</p>}"
    )
    artifact = {
        "schema_version": "2",
        "title": "历史 React 项目",
        "summary": "使用转义包名导入 Three.js",
        "files": {"src/App.tsx": source, "src/styles.css": "body{}", "src/extra.json": "{}"},
    }
    compiled = _validation_ok()["compiled"]
    version = {
        "raw_json": compact(artifact),
        "compiled_json": compact(compiled),
        "project_id": "legacy-project",
        "number": 1,
        "digest": compiled["digest"],
    }

    with zipfile.ZipFile(io.BytesIO(export_zip(version))) as archive:
        package = json.loads(archive.read("source/package.json"))
        assert archive.read("source/src/App.tsx").decode("utf-8") == source

    runtime_deps = json.loads((SHARED_ROOT / "runtime-dependencies.json").read_text("utf-8"))
    assert package["dependencies"] == runtime_deps
