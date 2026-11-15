import http from "node:http";
import { spawn } from "node:child_process";
import { timingSafeEqual } from "node:crypto";
import { fileURLToPath } from "node:url";
import { compile } from "./compiler.js";
import { compileReact } from "./react-compiler.js";
import { checkSandboxContract } from "./sandbox-contract.js";
import { ValidationDiagnostic } from "./diagnostic.js";
const token = process.env.SERVICE_TOKEN || "";
if (token.length < 24) throw new Error("SERVICE_TOKEN is required");
let busy = false;
class BrowserProbeUnavailable extends Error {}
function authorized(header: string | undefined) {
  const actual = Buffer.from(header || ""), expected = Buffer.from("Bearer " + token);
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}
const server = http.createServer(async (req,res) => {
  const reply = (status: number, value: object) => {
    if (res.destroyed) return;
    res.writeHead(status,{"Content-Type":"application/json","Cache-Control":"no-store"});
    res.end(JSON.stringify(value));
  };
  if (req.url === "/health/live") return reply(200,{status:"ok"});
  if (req.url !== "/internal/validate" || req.method !== "POST") return reply(404,{error:"not_found"});
  if (!authorized(req.headers.authorization)) return reply(401,{error:"unauthorized"});
  if (busy) return reply(429,{error:"validator_busy"});
  busy = true;
  try {
    const chunks: Buffer[] = []; let size = 0;
    for await (const chunk of req) { const part=Buffer.from(chunk);size+=part.length; if(size>32*1024*1024)return reply(413,{error:"request_too_large"});chunks.push(part); }
    const input = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    const lightweight3d = input.lightweight_3d === true;
    const previewKind = input.preview_kind;
    if (previewKind !== undefined && !["web","game","slides"].includes(previewKind)) return reply(400,{error:"unsupported_preview_kind"});
    const react = input.artifact?.schema_version==="2";
    const compiled = react ? await compileReact(input.artifact) : compile(input.artifact);
    if (!react) checkSandboxContract(input.artifact.files);
    const origin = new URL(input.app_origin).origin;
    if (origin !== process.env.APP_ORIGIN) throw new Error("APP_ORIGIN mismatch");
    if (res.destroyed) return;
    const result = await new Promise<any>((resolve,reject) => {
      const child = spawn(process.execPath,[fileURLToPath(new URL("./probe.js",import.meta.url)),"--child"],{stdio:["pipe","pipe","pipe"],detached:process.platform!=="win32",
        env:{PATH:process.env.PATH,HOME:"/tmp",LANG:"C.UTF-8",PLAYWRIGHT_BROWSERS_PATH:process.env.PLAYWRIGHT_BROWSERS_PATH}});
      let stdout = "", stderr = "", settled = false;
      const interrupt = (message:string) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (process.platform !== "win32") { try { process.kill(-child.pid!,"SIGKILL"); } catch {} } else child.kill("SIGKILL");
        reject(new BrowserProbeUnavailable(message));
      };
      const onDisconnect = () => interrupt("浏览器检查请求已结束");
      const timer = setTimeout(() => interrupt("浏览器检查超时"),lightweight3d ? 60000 : 12000);
      res.once("close",onDisconnect);
      child.stdout.on("data", b => { if (stdout.length<32000) stdout+=b; });
      child.stderr.on("data", b => { if (stderr.length<2000) stderr+=b; });
      child.on("error",() => interrupt("无法启动浏览器检查进程"));
      child.stdin.on("error",() => interrupt("无法传输浏览器检查内容"));
      child.on("close",() => {
        res.off("close",onDisconnect);
        clearTimeout(timer); if (settled) return; settled=true;
        try { resolve(JSON.parse(stdout)); } catch { reject(new BrowserProbeUnavailable("隔离浏览器进程未正常完成")); }
      });
      child.stdin.end(JSON.stringify({compiled,origin,startupOnly:true,lightweight3d}));
    });
    if (result.code === "browser_unavailable") return reply(503,result);
    return reply(200,result.ok ? {ok:true,compiled,report:result.report} : result);
  } catch (e) {
    if (e instanceof ValidationDiagnostic) return reply(200,e.response());
    if (!(e instanceof BrowserProbeUnavailable)) console.error("Validator failed internally",e);
    return reply(503,{ok:false,error:e instanceof BrowserProbeUnavailable ? e.message : "校验服务暂不可用",code:"validator_unavailable"});
  }
  finally { busy=false; }
});
server.requestTimeout = 16000;
server.listen(9000,"0.0.0.0");
