import type {Frame} from "playwright";
import type {InputCheck} from "./input-checks.js";

const startName=/^(?:开始(?:游戏|冒险|挑战|比赛|闯关)?|进入游戏|开玩|start(?: game)?|play(?: now)?)$/i;
const auxiliary=/暂停|继续|设置|音效|静音|重开|重置|重新|退出|返回|帮助|说明|pause|resume|settings|mute|restart|reset|quit|help/i;
const controls='button:visible:enabled,[role="button"]:visible:not([aria-disabled="true"])';
const activeControls='button[data-game-active="true"]:visible:enabled,[role="button"][data-game-active="true"]:visible:not([aria-disabled="true"])';

export async function smokeGame(frame:Frame, hints:InputCheck[], requireWebgl:boolean,allowUnconfirmedInput=false) {
  const page=frame.page();
  const phase=()=>frame.evaluate(()=>document.querySelector("[data-game-phase]")?.getAttribute("data-game-phase")??null);
  const start=frame.locator("[data-game-start]:visible:enabled").or(frame.getByRole("button",{name:startName}).and(frame.locator(controls)));
  const unconfirmed = async () => ({
    core_playable:false, input:"unconfirmed", status:"runnable_input_unconfirmed",
    webgl:requireWebgl, visible_feedback:(await frame.locator("body").innerText({timeout:1500})).slice(0,600),
  });
  const initialPhase=await phase();
  if (initialPhase==="ready" || !initialPhase && await start.count()) {
    let clicked = false;
    for (const candidate of (await start.all()).slice(0, 2)) {
      try {
        await candidate.click({timeout:1800});
        clicked = true;
        break;
      } catch { /* The control may be animating, obscured or already replaced. */ }
    }
    if (!clicked && await phase()==="ready") {
      await page.keyboard.press("Enter");
      if (await phase()==="ready") await page.keyboard.press("Space");
    }
    if (initialPhase==="ready" && await phase()==="ready") {
      try {
        await frame.waitForFunction(()=>document.querySelector("[data-game-phase]")?.getAttribute("data-game-phase")!=="ready",
          undefined,{timeout:2500,polling:100});
      } catch (error) {
        if (!(error instanceof Error) || error.name !== "TimeoutError") throw error;
        if (!clicked && allowUnconfirmedInput && !requireWebgl) return unconfirmed();
        throw new Error(clicked ? "点击开始后游戏仍停在开始界面" : "未能触发游戏开始操作");
      }
    }
  }
  if (requireWebgl) {
    await frame.waitForFunction(()=>[...document.querySelectorAll("canvas")].some(canvas=>{
      const probe=window as unknown as {atomsHasDrawnWebgl?:(canvas:HTMLCanvasElement)=>boolean};
      return canvas.getBoundingClientRect().width>0 && probe.atomsHasDrawnWebgl?.(canvas)===true;
    }),undefined,{timeout:3000}).catch(()=>{throw new Error("游戏开局未呈现实际 WebGL 画面");});
  }

  async function snapshot() {
    return frame.evaluate(()=>{
      const root=document.querySelector("[data-game-phase]")??document.body;
      const text=(root as HTMLElement).innerText.replace(/\b\d{1,2}:\d{2}(?:\.\d+)?\b|\b\d+\s*(?:s\b|秒)/gi,"").trim().slice(0,1800);
      const state=[...root.attributes].filter(({name})=>name.startsWith("data-playtest-") &&
        !/time|clock|elapsed|remaining|frame|tick|cooldown/.test(name)).map(({name,value})=>[name,value]);
      const counter=root.getAttribute("data-game-actions");
      const actions=counter!==null && counter.trim()!=="" && Number.isFinite(Number(counter)) && Number(counter)>=0 ? Number(counter) : null;
      return {text,state:JSON.stringify(state),actions,phase:root.getAttribute("data-game-phase")};
    });
  }

  async function canvasSample() {
    return frame.evaluate(()=>{
      const canvas=[...document.querySelectorAll("canvas")].find(item=>item.getBoundingClientRect().width>0);
      if (!canvas || !canvas.width || !canvas.height) return null;
      const sample=document.createElement("canvas");
      sample.width=sample.height=48;
      sample.getContext("2d")?.drawImage(canvas,0,0,48,48);
      return sample.toDataURL();
    }).catch(()=>null);
  }

  const keys=[...new Map([...[
    "Space","ArrowRight","ArrowUp","w","d","Enter",
  ].map(key=>({key,hold_ms:140,with_key:null})),...hints.filter(h=>h.key)].map(h=>[h.key,h])).values()];
  const deadline=Date.now()+7000;
  let buttonIndex=0;
  for (let round=0;Date.now()<deadline && round<24;round++) {
    const active=frame.locator(activeControls).first();
    const playable=frame.locator(controls).filter({hasNotText:auxiliary}).and(frame.locator(
      ':not([data-game-start],[data-game-pause],[data-game-resume],[data-game-restart])'));
    const count=await playable.count();
    const button=await active.count()?active:count?playable.nth(buttonIndex%count):null;
    const key=keys[(button?Math.floor(round/2):round)%keys.length];
    const canvas=frame.locator("canvas:visible").first();
    const locked=await frame.evaluate(()=>Boolean(document.pointerLockElement));
    const canvasVisible=await canvas.isVisible();
    const baseline=await snapshot();
    // A real game-action counter avoids synchronous pixel readback from a live WebGL frame.
    const first=canvasVisible && baseline.actions===null ? await canvasSample() : null;
    if (first || !baseline.actions) await page.waitForTimeout(65);
    const idle=first && await canvasSample()===first ? first : null;
    const before=await snapshot();
    try {
      let input:string;
      if (!locked && button && round%2===0) {
        buttonIndex++;
        await button.click({timeout:330,delay:45});
        input="button";
      } else if (round%4===0 && canvasVisible) {
        if (locked) { await page.mouse.down(); await page.mouse.up(); }
        else await canvas.click({timeout:330});
        input="pointer";
      } else {
        if (key.with_key) await page.keyboard.down(key.with_key);
        try {
          await page.keyboard.down(key.key!);
          await page.waitForTimeout(Math.min(280,Math.max(80,key.hold_ms)));
        } finally {
          await page.keyboard.up(key.key!);
          if (key.with_key) await page.keyboard.up(key.with_key);
        }
        input="keyboard";
      }
      await page.waitForTimeout(85);
      const after=await snapshot();
      const stillPlaying=!after.phase || after.phase==="playing";
      const pixels=idle?await canvasSample():null;
      const actionCounted=after.actions!==null && before.actions!==null && after.actions>before.actions;
      const visibleChange=baseline.text===before.text && after.text!==before.text ||
        baseline.state===before.state && after.state!==before.state || pixels!==null && pixels!==idle;
      if (actionCounted || after.phase==="won" && before.phase!=="won" || stillPlaying && visibleChange) {
        await page.waitForTimeout(300);
        return {core_playable:true,input,webgl:requireWebgl,visible_feedback:after.text.slice(0,600)};
      }
    } catch { /* A transient or covered target does not imply a broken game. */ }
  }
  if (allowUnconfirmedInput) {
    return unconfirmed();
  }
  throw new Error("游戏能打开，但未观察到键盘、鼠标或画面控件触发实际操作。检查开局可操作性和玩法反馈。");
}
