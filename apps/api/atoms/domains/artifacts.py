"""Parse and normalize the generator output before artifact validation."""

import json
import re

PROTECTED_REACT_FILES = frozenset({"src/App.tsx", "src/styles.css"})
_PATCH_DELETE_PATH = re.compile(r"^src/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.(?:tsx?|json)$")


def strict_json(raw):
    text = raw.strip()
    fence = chr(96) * 3
    for marker in ("~~~", fence):
        if text.startswith(marker) and text.endswith(marker) and "\n" in text:
            text = text.split("\n", 1)[1].rsplit(marker, 1)[0].strip()

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("重复 JSON 属性")
            result[key] = value
        return result

    return json.loads(
        text, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("非法数值"))
    )


def normalize_artifact(artifact):
    """Fix unambiguous envelope mistakes before checking the full contract."""
    if type(artifact.get("schema_version")) is int and artifact["schema_version"] in (1, 2):
        artifact["schema_version"] = str(artifact["schema_version"])
    if artifact.get("schema_version") == "2":
        return artifact
    files = artifact.get("files")
    if isinstance(files, dict):
        for name in ("index.html", "styles.css", "app.js"):
            if name not in files and isinstance(artifact.get(name), str):
                files[name] = artifact.pop(name)
    return artifact


def merge_react_patch(artifact: dict, base_artifact: dict | None = None) -> dict:
    """Deterministically merge an incremental React patch onto base_artifact.files."""
    if artifact.get("schema_version") != "2":
        return artifact
    mode = artifact.get("mode")
    has_deleted = "deleted_files" in artifact
    if mode is None and not has_deleted:
        return artifact
    if mode not in (None, "full", "patch"):
        raise ValueError("增量协议 mode 字段只能为 full 或 patch")
    deleted_files = artifact.get("deleted_files", [])
    if not isinstance(deleted_files, list) or any(not isinstance(item, str) for item in deleted_files):
        raise ValueError("deleted_files 必须是文件路径字符串数组")
    if mode == "full":
        if deleted_files:
            raise ValueError("mode 为 full 时不能同时指定非空的 deleted_files")
        return {key: value for key, value in artifact.items() if key not in {"mode", "deleted_files"}}

    if (
        not isinstance(base_artifact, dict)
        or str(base_artifact.get("schema_version")) != "2"
        or not isinstance(base_artifact.get("files"), dict)
    ):
        raise ValueError("当前任务不存在可合并的 schema_version 2 基础版本，请输出完整源码文件")

    patch_files = artifact.get("files")
    if not isinstance(patch_files, dict) or any(
        not isinstance(path, str) or not isinstance(source, str) for path, source in patch_files.items()
    ):
        raise ValueError("增量 files 必须是路径到完整源码字符串的映射")
    if not patch_files and not deleted_files:
        raise ValueError("增量 patch 至少需要包含一处新增、修改或删除的文件")

    for del_path in deleted_files:
        if del_path in PROTECTED_REACT_FILES:
            raise ValueError(f"禁止删除核心入口或全局样式文件：{del_path}")
        if not _PATCH_DELETE_PATH.fullmatch(del_path):
            raise ValueError(f"非法删除文件路径：{del_path}")

    merged_files = dict(base_artifact["files"])
    for del_path in deleted_files:
        merged_files.pop(del_path, None)
    merged_files.update(patch_files)

    merged = {key: value for key, value in artifact.items() if key not in {"mode", "deleted_files"}}
    merged["schema_version"] = "2"
    if not isinstance(merged.get("title"), str) or not merged["title"].strip():
        merged["title"] = str(base_artifact.get("title") or "")
    if not isinstance(merged.get("summary"), str) or not merged["summary"].strip():
        merged["summary"] = str(base_artifact.get("summary") or "")
    merged["files"] = merged_files
    return merged
