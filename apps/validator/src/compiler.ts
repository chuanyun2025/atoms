import { parse, serialize } from "parse5";
import postcss from "postcss";
import valueParser from "postcss-value-parser";
import { parse as parseJS } from "acorn";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { Ajv2020 } from "ajv/dist/2020.js";

export type Artifact = {schema_version: "1"; title: string; summary: string; files: {"index.html": string; "styles.css": string; "app.js": string}};
export type Compiled = {body_html: string; css_base64: string; js_base64: string; digest: string; compiler_version: string; sdk_version: string};
const root = new URL("../../../shared/preview-runtime/", import.meta.url);
export const runtime = readFileSync(new URL("runtime.js", root), "utf8");
const template = readFileSync(new URL("document.html", root), "utf8");
const validate = new Ajv2020({strict:true,allErrors:true}).compile(JSON.parse(readFileSync(new URL("../contracts/artifact.schema.json",root),"utf8")));
const policy = JSON.parse(readFileSync(new URL("../contracts/html-policy.json",root),"utf8"));
const tags = new Set<string>(policy.tags.split(" "));
const attrs = new Set<string>(policy.attributes.split(" "));
const exactKeys = (obj: object, keys: string[]) => Object.keys(obj).sort().join() === [...keys].sort().join();
function fail(message: string): never { throw new Error(message); }
export function compile(input: unknown): Compiled {
  if (!validate(input)) {
    const details=validate.errors?.slice(0,8).map(issue=>{
      const path=issue.instancePath||"根对象";
      if (issue.keyword==="required") return path+" 缺少 "+issue.params.missingProperty;
      if (issue.keyword==="additionalProperties") return path+" 多出 "+JSON.stringify(issue.params.additionalProperty).slice(0,100);
      return path+" "+issue.message;
    });
    fail("产物字段不符合契约："+details?.join("；"));
  }
  if (!input || typeof input !== "object" || !exactKeys(input, ["schema_version","title","summary","files"])) fail("产物字段不符合契约");
  const a = input as Artifact;
  if (a.schema_version !== "1" || typeof a.title !== "string" || !a.title.trim() || a.title.length > 80 ||
      typeof a.summary !== "string" || !a.summary.trim() || a.summary.length > 600) fail("产物版本、标题或摘要无效");
  if (!a.files || typeof a.files !== "object" || !exactKeys(a.files, ["index.html","styles.css","app.js"])) fail("必须提供约定的三个文件");
  let total = 0;
  for (const value of Object.values(a.files)) {
    if (typeof value !== "string") fail("文件内容必须是文本");
    const size = Buffer.byteLength(value);
    if (size > 4*1024*1024) fail("单文件超过 4 MiB 资源保护");
    total += size;
  }
  if (total > 8*1024*1024 || !a.files["app.js"].trim()) fail("代码为空或总大小超过 8 MiB 资源保护");
  const doc = parse(a.files["index.html"]) as any;
  const problems = new Set<string>();
  let body: any;
  function visit(node: any, inHead = false) {
    if (node.nodeName === "#comment") return;
    if (node.tagName) {
      if (!tags.has(node.tagName)) {
        if (node.tagName === "meta" && inHead && node.attrs.every((x: any) => ["charset","name","content"].includes(x.name)) &&
            !node.attrs.some((x: any) => x.name === "name" && !["viewport","description"].includes(x.value))) return;
        problems.add("不支持的 HTML 标签：" + node.tagName);
      }
      if (node.tagName === "body") body = node;
      for (const attr of node.attrs || []) {
        const n = attr.name.toLowerCase(), v = attr.value.trim();
        if ((!attrs.has(n) && !/^data-[a-z0-9-]+$/.test(n) && !/^aria-[a-z-]+$/.test(n)) || n.startsWith("on") || attr.namespace) problems.add("不支持的 HTML 属性：" + n);
        if (["src","href","action"].includes(n)) {
          if (n === "src" ? !/^data:image\/(?:png|jpeg|webp|gif);base64,[a-z0-9+/=\s]+$/i.test(v) : (v !== "" && !/^#[a-z0-9_.:-]*$/i.test(v))) problems.add("HTML 包含不支持的外部或主动 URL");
        }
        if (n === "target" && v !== "_self") problems.add("不允许打开新窗口");
        if (n === "style") checkCSS("x{" + v + "}");
      }
    }
    for (const child of node.childNodes || []) visit(child, inHead || node.tagName === "head");
  }
  visit(doc);
  if (problems.size) fail([...problems].slice(0,20).join("；"));
  if (!body || !serialize(body).trim()) fail("页面 body 不能为空");
  checkCSS(a.files["styles.css"]);
  try {
    const ast = parseJS(a.files["app.js"], {ecmaVersion: 2022, sourceType: "script"});
    const visitJS = (node: any) => {
      if (!node || typeof node !== "object") return;
      if (node.type === "ImportExpression") fail("不支持动态 import");
      for (const child of Object.values(node)) {
        if (Array.isArray(child)) child.forEach(visitJS);
        else if (child && typeof child === "object") visitJS(child);
      }
    };
    visitJS(ast);
  }
  catch (e) { fail("JavaScript 语法错误：" + String(e).slice(0, 250)); }
  return {
    body_html: serialize(body), css_base64: Buffer.from(a.files["styles.css"]).toString("base64"),
    js_base64: Buffer.from(a.files["app.js"]).toString("base64"),
    digest: createHash("sha256").update(JSON.stringify({artifact:a,compiler_version:"1",sdk_version:"1"})).digest("hex"), compiler_version:"1", sdk_version:"1"
  };
}
function checkCSS(css: string) {
  let tree;
  try { tree = postcss.parse(css); } catch { fail("CSS 语法错误"); }
  tree.walkAtRules(rule => { if (["import","namespace","document"].includes(rule.name.toLowerCase())) fail("CSS 不支持外部规则"); });
  tree.walkDecls(decl => {
    if (["behavior", "-ms-behavior", "-moz-binding"].includes(decl.prop.toLowerCase())) {
      fail("CSS 不支持主动属性：" + decl.prop);
    }
    valueParser(decl.value).walk(node => {
      if (node.type === "function" && node.value.toLowerCase() === "expression") {
        fail("CSS 不支持主动函数 expression()");
      }
      if (node.type === "function" && node.value.toLowerCase() === "url") {
        const url = valueParser.stringify(node.nodes).replace(/^['"]|['"]$/g, "").trim();
        if (!/^data:image\/(?:png|jpeg|gif|webp);base64,/i.test(url) && !/^#[\w-]+$/.test(url)) fail("CSS 不支持外部 URL");
      }
    });
  });
}
export function csp(origin: string): string {
  return "sandbox allow-scripts allow-pointer-lock; default-src 'none'; script-src data:; style-src 'unsafe-inline' data:; img-src data: blob:; connect-src 'none'; font-src 'none'; media-src 'none'; worker-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors " + origin + ";";
}
export function documentFor(compiled: Compiled, config: object): string {
  const values: Record<string,string> = {BODY_HTML: compiled.body_html, CSS_BASE64: compiled.css_base64,
    RUNTIME_BASE64: Buffer.from(runtime).toString("base64"), CONFIG_BASE64: Buffer.from(JSON.stringify({...config, js_base64: compiled.js_base64})).toString("base64")};
  return template.replace(/\{\{([A-Z0-9_]+)\}\}/g, (_, key) => values[key]);
}
