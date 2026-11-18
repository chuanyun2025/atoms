import base64
import io
import json
import re
import zipfile

from atoms import SHARED_ROOT
from atoms.core.config import settings

SHARED = SHARED_ROOT / "preview-runtime"


def csp():
    return (
        "sandbox allow-scripts allow-pointer-lock; default-src 'none'; script-src data:; style-src 'unsafe-inline' data:; img-src data: blob:; connect-src 'none'; font-src 'none'; media-src 'none'; worker-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors "
        + settings().app_origin
        + ";"
    )


def render_document(compiled, payload):
    config = {
        "app_origin": settings().app_origin,
        "instance_id": payload["instance_id"],
        "channel_nonce": payload["channel_nonce"],
        "read_only": payload["read_only"],
        "js_base64": compiled["js_base64"],
    }
    values = {
        "BODY_HTML": compiled["body_html"],
        "CSS_BASE64": compiled["css_base64"],
        "RUNTIME_BASE64": base64.b64encode((SHARED / "runtime.js").read_bytes()).decode(),
        "CONFIG_BASE64": base64.b64encode(json.dumps(config, ensure_ascii=False).encode()).decode(),
    }
    return re.sub(r"\{\{([A-Z0-9_]+)\}\}", lambda m: values[m[1]], (SHARED / "document.html").read_text("utf-8"))


EXPORT_RUNTIME = """(() => {
const prefix='atoms-export:';
const valid=k=>typeof k==='string'&&/^[A-Za-z0-9_.:-]{1,64}$/.test(k)&&!['__proto__','prototype','constructor'].includes(k);
let error=null;
window.atoms=Object.freeze({storage:Object.freeze({
get(k,f=null){if(!valid(k))throw Error('Invalid key');try{const v=localStorage.getItem(prefix+k);return v===null?JSON.parse(JSON.stringify(f)):JSON.parse(v)}catch(e){error=e;return f}},
set(k,v){if(!valid(k)||v===undefined)throw Error('Invalid value');try{localStorage.setItem(prefix+k,JSON.stringify(v));error=null}catch(e){error=e;throw e}},
remove(k){if(!valid(k))throw Error('Invalid key');try{localStorage.removeItem(prefix+k);error=null}catch(e){error=e;throw e}},
async flush(){if(error)throw error}
})});
})();"""


def _export_dependencies(compiled: dict) -> dict[str, str]:
    runtime_deps: dict[str, str] = json.loads((SHARED.parent / "runtime-dependencies.json").read_text("utf-8"))
    dependencies = compiled.get("dependencies")
    if not isinstance(dependencies, list):
        # Older snapshots lack compiler metadata. Include every supported runtime package.
        return runtime_deps

    used_packages = {"react", "react-dom"}
    used_packages.update(pkg for pkg in dependencies if isinstance(pkg, str))
    return {name: runtime_deps[name] for name in runtime_deps if name in used_packages}


def export_zip(version):
    artifact = json.loads(version["raw_json"])
    compiled = json.loads(version["compiled_json"])
    react = artifact["schema_version"] == "2"
    html = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="./styles.css"><script defer src="./atoms-runtime.js"></script><script defer src="./app.js"></script></head><body>'
        + compiled["body_html"]
        + "</body></html>"
    )
    runtime = EXPORT_RUNTIME.replace("atoms-export:", "atoms-export:" + version["project_id"] + ":")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("index.html", html)
        archive.writestr(
            "styles.css", base64.b64decode(compiled["css_base64"]) if react else artifact["files"]["styles.css"]
        )
        archive.writestr("app.js", base64.b64decode(compiled["js_base64"]) if react else artifact["files"]["app.js"])
        archive.writestr("atoms-runtime.js", runtime)
        if react:
            for path, content in artifact["files"].items():
                archive.writestr("source/" + path, content)
            archive.writestr("source/public/atoms-runtime.js", runtime)
            archive.writestr(
                "source/index.html",
                '<html lang="zh-CN"><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><script src="/atoms-runtime.js"></script><body><div id="root"></div><script type="module" src="/bootstrap.tsx"></script></body></html>',
            )
            archive.writestr(
                "source/bootstrap.tsx",
                """import React from "react";
import {createRoot} from "react-dom/client";
import App from "./src/App";
import "./src/styles.css";

createRoot(document.getElementById("root")!).render(<App />);
""",
            )
            archive.writestr(
                "source/package.json",
                json.dumps(
                    {
                        "name": "atoms-export",
                        "private": True,
                        "type": "module",
                        "scripts": {"dev": "vite", "build": "vite build"},
                        "dependencies": _export_dependencies(compiled),
                        "devDependencies": {"vite": "7.3.8"},
                    },
                    indent=2,
                ),
            )
            archive.writestr(
                "source/tsconfig.json",
                json.dumps(
                    {
                        "compilerOptions": {"jsx": "react-jsx", "moduleResolution": "bundler", "target": "ES2022"},
                    },
                    indent=2,
                ),
            )
        else:
            archive.writestr("source/index.html", artifact["files"]["index.html"])
        archive.writestr(
            "artifact.json",
            json.dumps(
                {"version": version["number"], "digest": version["digest"], "artifact": artifact},
                ensure_ascii=False,
                indent=2,
            ),
        )
        instructions = (
            "\n\n编辑 React 源码时，进入 source 目录运行 npm install 和 npm run dev。已打包的站点可以直接运行。"
            if react
            else ""
        )
        archive.writestr(
            "README.md",
            "# "
            + artifact["title"]
            + "\n\n运行：在本目录执行 python -m http.server 8081，然后打开 http://localhost:8081。"
            + instructions
            + "\n\n请使用独立目录、端口运行。导出 SDK 使用此站点的 localStorage；工作台中的业务数据、对话、密钥不包含在导出包内。\n",
        )
    return buffer.getvalue()
