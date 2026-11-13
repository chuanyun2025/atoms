import type {Frame} from "playwright";
import {checkInputs,OppositeInputError,type InputCheck} from "./input-checks.js";

export const GAME_PLAY = "game-play-v1";
const root = "[data-game-phase]";
class ReplayLostError extends Error {}

export async function releasePointerLock(frame:Frame) {
  // Pointer lock redirects native clicks to the canvas. Release it before using
  // HUD controls, just as a player does when leaving mouse-look mode.
  await frame.evaluate(() => {
    if (document.pointerLockElement) document.exitPointerLock();
  });
  await frame.waitForFunction(() => !document.pointerLockElement,undefined,{timeout:1500});
}

function clickReason(error: unknown): string {
  const lines = String(error).split("\n").map(line=>line.trim());
  const reason = lines.find(line=>/intercepts pointer events|is not enabled|strict mode violation/.test(line));
  return "：" + (reason ?? lines.filter(line=>line.startsWith("-")).slice(-3).join(" ")).slice(0,450);
}

export async function checkGame(frame: Frame, replay: string[], timeout=800, fps=false, checks:InputCheck[] = [], requireWebgl=false) {
  const game = frame.locator(root);
  if (await game.count() !== 1 || !await game.isVisible()) {
    throw new Error("游戏需要一个可见的 data-game-phase 容器");
  }

  async function state(allowed: string[], action: string, actions?: number) {
    await frame.waitForFunction(({root,allowed,actions}) => {
      const container = document.querySelector(root);
      return allowed.includes(container?.getAttribute("data-game-phase") ?? "") &&
        (actions === undefined || container?.getAttribute("data-game-actions") === String(actions));
    }, {root,allowed,actions}, {timeout: Math.max(1600,timeout),polling:80}).catch(async () => {
      const actual = await game.evaluate(element=>({phase:element.getAttribute("data-game-phase"),
        actions:element.getAttribute("data-game-actions")}));
      if (actual.phase && allowed.includes(actual.phase) && (actions===undefined || actual.actions===String(actions))) return;
      throw new Error(action + "后，预期游戏状态 " + allowed.join("/") + "，实际为 " + (actual.phase ?? "缺失") +
        (actions === undefined ? "" : "，预期本局动作数 " + actions + "，实际 " + (actual.actions ?? "缺失")));
    });
  }

  async function click(control: string, action: string) {
    const button = frame.locator("button[data-game-" + control + "]:visible:enabled");
    const actionTimeout=control==="start"?5000:Math.max(timeout,1800);
    await button.first().waitFor({state:"visible",timeout:actionTimeout}).catch(()=>{
      throw new Error(action + "需要一个可见且可用的 data-game-" + control + " 按钮");
    });
    // Skip Playwright's animation-frame stability wait. The native click
    // still has to reach the visible control and change the game phase.
    if (await button.count()===1) {
      await button.click({timeout:actionTimeout,force:true}).catch(error => { throw new Error(action + "按钮无法操作" + clickReason(error)); });
      return;
    }
    for (const candidate of await button.all()) {
      try { await candidate.click({timeout:600}); return; }
      catch { /* An overlay can cover another control with the same action. */ }
    }
    throw new Error(action + "没有可点击的 data-game-" + control + " 按钮");
  }

  async function pause(action: string) {
    if (await frame.evaluate(()=>Boolean(document.pointerLockElement))) {
      await frame.page().keyboard.press("Escape");
      await releasePointerLock(frame);
    }
    if (await game.getAttribute("data-game-phase")==="playing") await click("pause",action);
    await state(["paused"],action);
  }

  await state(["ready","playing"],"打开游戏",0);
  if (await game.getAttribute("data-game-phase")==="ready") await click("start","开始");
  await state(["playing"],"开始",0);
  if (requireWebgl) {
    await frame.waitForFunction(()=>[...document.querySelectorAll("canvas")].some(canvas=>{
      if (canvas.width<40 || canvas.height<40 || !canvas.getBoundingClientRect().width) return false;
      const probe=window as unknown as {atomsHasDrawnWebgl?:(canvas:HTMLCanvasElement)=>boolean};
      return probe.atomsHasDrawnWebgl?.(canvas)===true;
    }),undefined,{timeout:5000}).catch(()=>{throw new Error("游戏开局未呈现实际 WebGL 画面");});
  }
  if (fps) {
    await releasePointerLock(frame);
    if (await game.getAttribute("data-game-phase")==="paused") await click("resume","恢复鼠标锁定后的游戏");
    await state(["playing"],"恢复浏览器交互",0);
  }
  const actions = frame.locator("button[data-game-action]:enabled:visible");
  const primary = frame.locator('button[data-game-action="primary"]:enabled:visible');
  const fire=frame.locator("button[data-fps-fire]:enabled:visible");
  const replayStart=frame.locator(`button[data-game-input="${replay[0]}"]:enabled:visible`);
  const options = fps && await fire.count()===1 ? fire : await primary.count()===1 ? primary : replay.length ? replayStart : actions;
  const count = Math.min(await options.count(),6);
  let observedAction: { control: string; actions: number; visible_feedback: string } | undefined;
  let actionError:unknown;
  let visibleResponse=false;

  async function readAction(control: string) {
    return game.evaluate((element, control) => ({
      control, actions: Number(element.getAttribute("data-game-actions")),
      visible_feedback: (element as HTMLElement).innerText.slice(0, 600),
    }), control);
  }

  async function observeAction(control: string, wait: number, feedbackDelay=0) {
    await frame.waitForFunction(selector => {
      const value = document.querySelector(selector)?.getAttribute("data-game-actions") ?? "";
      return /^[1-9]\d*$/.test(value);
    }, root, {timeout: wait});
    if (feedbackDelay) await frame.waitForTimeout(feedbackDelay);
    return readAction(control);
  }

  const checked=[];
  const supplementalFailures:{id:string;message:string}[]=[];
  function recordFailure(id:string,error:unknown) {
    supplementalFailures.push({id,message:(error instanceof Error?error.message:String(error)).slice(0,800)});
  }
  for (const [index,check] of checks.entries()) {
    try {
      if (index>0 && check.fresh_start) {
        await frame.goto(frame.url(),{waitUntil:"load",timeout:5000});
        await state(["ready","playing"],"重开",0);
        if (await game.getAttribute("data-game-phase")==="ready") await click("start","开始下一项试玩");
        await state(["playing"],"开始下一项试玩",0);
        // Wait for the new round to publish its first rendered gameplay state.
        await frame.evaluate(()=>new Promise<void>(resolve=>{
          const fallback=setTimeout(resolve,250);
          requestAnimationFrame(()=>requestAnimationFrame(()=>{clearTimeout(fallback);resolve();}));
        }));
      }
      checked.push(...await checkInputs(frame,[check]));
      if (!observedAction && check.change!=="unchanged") {
        observedAction=await readAction(check.label);
      }
    } catch (error) {
      if (error instanceof OppositeInputError) throw error;
      recordFailure(`input:${check.signal}:${check.change}:${check.key??check.control??check.pointer}`,error);
    }
  }
  const responsive=Boolean(observedAction);
  async function feedbackSnapshot() {
    return (await game.innerText()).replace(/\b\d{1,2}:\d{2}(?:\.\d+)?\b/g,"").trim();
  }

  // Desktop controls can be entirely keyboard-driven. Run real inputs in
  // the focused frame instead of requiring mobile buttons at desktop width.
  if (!observedAction && !replay.length && !fps) {
    const keyboard = frame.page().keyboard;
    for (const key of ["ArrowUp", "w", "ArrowRight", "Space"]) {
      try {
        const before=await feedbackSnapshot();
        await keyboard.down(key);
        observedAction = await observeAction(key, 280, 220);
        visibleResponse=(await feedbackSnapshot())!==before;
        break;
      } catch (error) {
        actionError = error;
      } finally {
        await keyboard.up(key);
      }
    }
  }

  for (let i = 0; i < count && !observedAction; i++) {
    try {
      const button = options.nth(i);
      const label = await button.evaluate(element => (element.getAttribute("aria-label") || element.textContent || "").trim().slice(0, 100));
      const before=await feedbackSnapshot();
      // Software WebGL can delay animation frames used by Playwright's layout
      // stability check. Native clicks still must change real gameplay state.
      await button.click({timeout:fps?5000:Math.max(450,timeout),force:fps});
      observedAction = await observeAction(label, Math.max(350,timeout));
      visibleResponse=(await feedbackSnapshot())!==before;
    } catch (error) {
      // A direction can be blocked by the starting map. Try another real control.
      actionError=error;
    }
  }
  if (!observedAction) throw new Error(supplementalFailures[0]?.message ?? ("试玩时，实际键盘或画面操作未触发游戏动作，当前状态 "+
    await game.getAttribute("data-game-phase")+"，动作数 "+await game.getAttribute("data-game-actions")+clickReason(actionError)));

  const lifecycle:{start:boolean;pause?:boolean;resume?:boolean;restart?:boolean}={start:true};
  const hasPause=await frame.locator("button[data-game-pause]:visible:enabled").count()>0 ||
    await frame.evaluate(()=>Boolean(document.pointerLockElement));
  if (hasPause && await game.getAttribute("data-game-phase")==="playing") {
    let step="pause";
    try {
      await pause("暂停");
      lifecycle.pause=true;
      const paused = Number(await game.getAttribute("data-game-actions",{timeout}));
      step="resume";
      await click("resume","继续");
      await state(["playing"],"继续",paused);
      lifecycle.resume=true;
      step="pause";
      await pause("再次暂停");
    } catch (error) { recordFailure(`lifecycle:${step}`,error); }
  }
  if (await frame.locator("button[data-game-restart]:visible:enabled").count()) {
    try {
      await click("restart","重开");
      await state(["ready","playing"],"重开",0);
      lifecycle.restart=true;
    } catch (error) { recordFailure("lifecycle:restart",error); }
  }

  const report={...observedAction, lifecycle, webgl:requireWebgl, checks:checked, supplemental_failures:supplementalFailures,
    core_playable:responsive||visibleResponse,replay_steps:0};
  if (!replay.length) return report;
  try {
    if (!lifecycle.restart) {
      await frame.goto(frame.url());
      await state(["ready","playing"],"重新打开通关回放",0);
    }
    if (await game.getAttribute("data-game-phase",{timeout}) === "ready") {
      await click("start","开始通关回放");
    }
    await state(["playing"],"开始通关回放",0);
    for (const [index,action] of replay.entries()) {
      const button = frame.locator('button[data-game-input="' + action + '"]:enabled:visible');
      await button.click({timeout:650}).catch(error => {
        throw new Error("通关回放第 " + (index+1) + " 步无法点击 " + action + "，检查关卡状态和控件 ID" + clickReason(error));
      });
      if (await game.getAttribute("data-game-phase",{timeout}) === "lost") {
        throw new ReplayLostError("通关回放在第 " + (index+1) + " 步失败，请核对资源预算与关卡路线");
      }
      report.replay_steps=index+1;
    }
    await state(["won"],"通关回放结束");
    report.core_playable=true;
  } catch (error) {
    if (error instanceof ReplayLostError) throw error;
    recordFailure("replay:completion",error);
  }
  return report;
}
