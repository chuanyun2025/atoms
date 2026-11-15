import { chromium } from "playwright";
import { randomBytes } from "node:crypto";
import { csp, documentFor, type Compiled } from "./compiler.js";
import { ValidationDiagnostic } from "./diagnostic.js";
import { checkSlidePreview, SLIDES_NAVIGATION } from "./slides-check.js";
import { checkGame, GAME_PLAY } from "./game-check.js";
import {checkFps,FPS_CHECK} from "./fps-check.js";
import {checkRace,RACE_CHECK} from "./race-check.js";
import type {InputCheck} from "./input-checks.js";
import {smokeGame} from "./game-smoke.js";

class BrowserUnavailable extends Error {}

export async function probe(compiled: Compiled, origin: string, behaviorCheck?: typeof SLIDES_NAVIGATION | typeof GAME_PLAY, gameReplay: string[] = [], experienceCheck?:typeof FPS_CHECK | typeof RACE_CHECK, gameChecks:InputCheck[] = [], requireWebgl=false, gameSmoke=false,allowUnconfirmedInput=false, options:{startupOnly?:boolean;lightweight3d?:boolean}={}) {
  const instance_id = randomBytes(16).toString("hex"), channel_nonce = randomBytes(24).toString("hex");
  const candidate = origin + "/__atoms_candidate";
  const parent = origin + "/__atoms_parent";
  const html = documentFor(compiled, {app_origin:origin, instance_id, channel_nonce, read_only:false});
  let browser;
  try { browser = await chromium.launch({headless:true, chromiumSandbox:true, args:["--disable-dev-shm-usage","--use-angle=swiftshader","--enable-unsafe-swiftshader"],
    env:{PATH:process.env.PATH||"/usr/bin:/bin",HOME:"/tmp",LANG:"C.UTF-8"}}); }
  catch { throw new BrowserUnavailable("隔离浏览器无法启动，请检查 Chromium 系统沙箱配置"); }
  try {
    // Software-rendered 3D needs a smaller buffer even for a generic game check.
    const gameViewport = options.lightweight3d || gameSmoke || Boolean(experienceCheck) || requireWebgl;
    const context = await browser.newContext({serviceWorkers:"block",
      viewport:gameViewport?{width:960,height:640}:{width:1280,height:800},
      deviceScaleFactor:gameViewport ? 0.4 : 1});
    if (requireWebgl) await context.addInitScript(()=>{
      const drawn=new WeakSet<HTMLCanvasElement>();
      Object.defineProperty(window,"atomsHasDrawnWebgl",{value:(canvas:HTMLCanvasElement)=>drawn.has(canvas)});
      for(const prototype of [WebGLRenderingContext.prototype,WebGL2RenderingContext.prototype]) {
        for(const name of ["drawArrays","drawElements","drawArraysInstanced","drawElementsInstanced"]) {
          const methods=prototype as unknown as Record<string,((...args:unknown[])=>void)|undefined>;
          const original=methods[name];
          if (!original) continue;
          methods[name]=function(this:WebGLRenderingContext,...args:unknown[]){
            original.apply(this,args);
            if (this.canvas instanceof HTMLCanvasElement) drawn.add(this.canvas);
          };
        }
      }
    });
    const issues: string[] = [], blocked: string[] = [];
    await context.routeWebSocket(/.*/, ws => ws.close());
    await context.route("**/*", async route => {
      const request = route.request();
      if (request.url() === parent && request.isNavigationRequest()) return route.fulfill({contentType:"text/html", body:'<!doctype html><html><body style="margin:0"></body></html>'});
      if (request.url() === candidate && request.isNavigationRequest()) return route.fulfill({contentType:"text/html", headers:{"Content-Security-Policy":csp(origin)}, body:html});
      blocked.push(request.url().slice(0,200)); await route.abort();
    });
    const page = await context.newPage();
    page.on("pageerror", e => issues.push(e.message.slice(0,600)));
    await page.goto(parent);
    const runtimeErrors = async () => {
      const reported = await page.evaluate(() => (window as unknown as {previewErrors?: string[]}).previewErrors ?? []);
      return [...new Set([...issues, ...reported])];
    };
    const ready = await page.evaluate(({candidate,instance_id,channel_nonce}) => {
      const errors: string[] = [];
      let values: Record<string, unknown> = Object.create(null);
      Object.defineProperty(window, "previewErrors", {value: errors});
      return new Promise<boolean>(resolve => {
        const iframe = document.createElement("iframe");
        iframe.style.cssText = "display:block;width:100%;height:100vh;border:0";
        iframe.sandbox.add("allow-scripts","allow-pointer-lock"); iframe.src = candidate;
        const timer = setTimeout(() => resolve(false), 6000);
        iframe.onload = () => {
          const channel = new MessageChannel();
          channel.port1.onmessage = ({data}) => {
            if (data.instance_id !== instance_id || data.protocol_version !== 1) return;
            if (data.type === "storage.set") {
              const next = Object.assign(Object.create(null),values,{[data.payload.key]:data.payload.value});
              if (Object.keys(next).length > 128 || new TextEncoder().encode(JSON.stringify(next)).length > 65536) {
                channel.port1.postMessage({instance_id,message_id:data.message_id,ok:false,error:"项目业务数据最多 128 项、总计 64 KiB"});
                return;
              }
              values = next;
            }
            if (data.type === "storage.remove") delete values[data.payload.key];
            if (data.type === "runtime.error") {
              if (errors.length < 20) errors.push(String(data.payload.message).slice(0,600));
            }
            channel.port1.postMessage({instance_id,message_id:data.message_id,ok:true});
            if (data.type === "runtime.ready") setTimeout(() => { clearTimeout(timer); resolve(true); },350);
          };
          iframe.contentWindow!.postMessage({type:"atoms.init",instance_id,channel_nonce,values,read_only:false},"*",[channel.port2]);
        };
        document.body.appendChild(iframe);
      });
    }, {candidate,instance_id,channel_nonce});
    const launchErrors = await runtimeErrors();
    if (launchErrors.length) {
      throw new ValidationDiagnostic("PREVIEW_RUNTIME_ERROR",launchErrors.join("; "),{subject:launchErrors[0]});
    }
    if (!ready) throw new ValidationDiagnostic("PREVIEW_STARTUP_TIMEOUT","应用启动超时，预览未收到就绪事件");
    if (options.startupOnly) return {ready:true, acceptance:"startup" as const, sandbox_enabled:true};

    const frame = page.frames().find(f => f.url() === candidate);
    const visible = frame ? await frame.locator("body").innerText({timeout:1000}) : "";
    const interactive = frame ? await frame.locator("button,input,select,textarea,a,summary,[role=button]").count() : 0;
    if (!visible.trim() && interactive === 0 && !await frame?.locator("canvas:visible,img:visible,svg:visible").count()) throw new Error("页面没有可见内容或交互控件");
    if (behaviorCheck === SLIDES_NAVIGATION) {
      if (!frame) throw new Error("幻灯片预览已离开应用页面");
      await checkSlidePreview(frame);
      if (issues.length) throw new Error(issues.join("; "));
    }
    if (compiled.compiler_version === "2" && !behaviorCheck && frame) {
      const controls = frame.getByRole("button").and(frame.locator(":visible:enabled"));
      for (const control of (await controls.all()).slice(0, 2)) {
        // Menus and overlays can change which controls are available. Only actual runtime errors block delivery.
        await control.click({timeout:600}).catch(() => {});
        await page.waitForTimeout(200);
      }
    }
    let experience;
    let race;
    let gameplay;
    let smoke;
    try {
      if (behaviorCheck === GAME_PLAY) {
        if (!frame) throw new Error("游戏预览已离开应用页面");
        if (gameSmoke) smoke=await smokeGame(frame,gameChecks,requireWebgl,allowUnconfirmedInput);
        else if (experienceCheck === FPS_CHECK) experience = await checkFps(frame,gameChecks);
        else {
          const isRace=experienceCheck===RACE_CHECK;
          gameplay = await checkGame(frame,gameReplay,experienceCheck||requireWebgl?2200:800,false,isRace?[]:gameChecks,requireWebgl);
          if (isRace) race = await checkRace(frame,gameChecks);
        }
      }
    } catch (error) {
      const errors = await runtimeErrors();
      if (errors.length) throw new Error(errors.join("; "));
      throw error;
    }
    let mobileOverflow = 0;
    if (compiled.compiler_version === "2" && frame && !gameSmoke) {
      await page.setViewportSize({width:390,height:844});
      mobileOverflow=await frame.evaluate(() => document.documentElement.scrollWidth-document.documentElement.clientWidth);
    }
    const errors = await runtimeErrors();
    if (errors.length) throw new Error(errors.join("; "));
    const viewport=frame?{text:(await frame.locator("body").innerText()).slice(0,4000),canvas_count:await frame.locator("canvas").count()}:undefined;
    return {ready:true, interactive_elements:interactive, blocked_requests:blocked.length, sandbox_enabled:true,viewport,
      ...(mobileOverflow > 4 ? {mobile_overflow_px:mobileOverflow} : {}),
      ...(experience ? {experience_check:FPS_CHECK,fps:experience} : {}),
      ...(race ? {experience_check:RACE_CHECK,race} : {}),
      ...(gameplay ? {gameplay} : {}),
      ...(smoke ? {gameplay:smoke} : {}),
      ...(gameplay?.webgl || smoke?.webgl ? {webgl:true} : {}),
      ...(!gameSmoke && gameChecks.length ? {game_input_checks:gameplay?.checks?.length??experience?.checks?.length??race?.checks?.length??0} : {}),
      ...(gameReplay.length ? {game_replay_steps:gameplay?.replay_steps??0} : {}),
      ...(behaviorCheck ? {behavior_check:behaviorCheck} : {})};
  } finally { await browser.close(); }
}

if (process.argv.includes("--child")) {
  const chunks: Buffer[] = []; let size = 0;
  for await (const part of process.stdin) { const chunk=Buffer.from(part);size+=chunk.length;if(size>32*1024*1024)process.exit(2);chunks.push(chunk); }
  const text=Buffer.concat(chunks).toString("utf8");
  try {
    const {compiled,origin,behaviorCheck,gameReplay,experienceCheck,gameChecks,requireWebgl,gameSmoke,allowUnconfirmedInput,startupOnly,lightweight3d} = JSON.parse(text);
    const report = await probe(compiled, origin, behaviorCheck, gameReplay,experienceCheck,gameChecks,requireWebgl,gameSmoke,allowUnconfirmedInput,{startupOnly,lightweight3d});
    process.stdout.write(JSON.stringify({ok:true,report}));
  } catch (e) {
    process.stdout.write(JSON.stringify(e instanceof ValidationDiagnostic ? e.response() :
      {ok:false,error:e instanceof BrowserUnavailable ? e.message : "隔离浏览器检查未完成",code:"browser_unavailable"}));
    process.exitCode = 1;
  }
}
