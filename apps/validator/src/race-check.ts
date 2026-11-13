import type {Frame} from "playwright";
import {checkInputs,type InputCheck} from "./input-checks.js";

export const RACE_CHECK = "race-track-v1";
const root = '[data-race-view="chase"][data-game-phase]';

export async function checkRace(frame: Frame, checks: InputCheck[] = []) {
  const game = frame.locator(root);
  if (await game.count() !== 1) throw new Error("赛道赛车需要真实跟车模式和驾驶状态");
  if (await game.getAttribute("data-game-phase") === "ready") {
    await frame.locator("button[data-game-start]:visible").click({timeout:5000,force:true});
  }
  const canvas = frame.locator("canvas[data-race-viewport]");
  await canvas.waitFor({state:"visible",timeout:5000});
  const glReady = await canvas.evaluate(element=>{
    const canvas=element as HTMLCanvasElement;
    const gl=canvas.getContext("webgl2");
    return !!gl && !gl.isContextLost() && canvas.width>100 && canvas.height>100;
  });
  if (!glReady) throw new Error("跟车赛车预览需要真实 WebGL 画布");

  async function stats() {
    return game.evaluate(element=>{
      const number=(key:string)=>{
        const raw=element.getAttribute("data-race-"+key);
        if(raw===null || raw==="" || !Number.isFinite(Number(raw))) throw new Error("赛车缺少实际状态 data-race-"+key);
        return Number(raw);
      };
      return {speed:number("speed"),distance:number("distance"),lateral:number("lateral"),
        collected:number("collected"),impacts:number("impacts"),energy:number("energy"),checkpoint:number("checkpoint")};
    });
  }

  const initial=await stats();
  const keyboard=frame.page().keyboard;
  await keyboard.down("w");
  let driven;
  let steering;
  try {
    await frame.waitForFunction(({root, initial})=>{
      const game=document.querySelector(root);
      const get=(key:string)=>Number(game?.getAttribute("data-race-"+key));
      return get("distance")>initial.distance+1 && get("speed")>0 && get("checkpoint")>initial.checkpoint &&
        get("collected")>initial.collected && get("energy")>initial.energy && get("impacts")>initial.impacts;
    },{root,initial},{timeout:23000,polling:125});
    driven=await stats();
    await keyboard.down("Shift");
    try {
      await frame.waitForFunction(({root,energy})=>Number(document.querySelector(root)?.getAttribute("data-race-energy"))<energy-0.5,
        {root,energy:driven.energy},{timeout:3500,polling:80});
    } finally { await keyboard.up("Shift"); }
    steering=await checkInputs(frame,[
      {label:"D 向画面右侧换道",key:"d",hold_ms:620,signal:"screen-x",change:"increase",min_delta:0.025},
      {label:"A 向画面左侧换道",key:"a",hold_ms:720,signal:"screen-x",change:"decrease",min_delta:0.025},
    ]);
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("实际试玩")) throw error;
    throw new Error("赛道实测未完成推进、补给、撞击、检查点或氮气消耗。确保首段有实际补给与减速路障，按 Shift 可消耗氮气");
  } finally { await keyboard.up("w"); }

  const speed=(await stats()).speed;
  await keyboard.down("s");
  try {
    await frame.waitForFunction(({root,speed})=>Number(document.querySelector(root)?.getAttribute("data-race-speed"))<speed-0.7,
      {root,speed},{timeout:3500,polling:80});
  } catch { throw new Error("赛车按 S 后没有减速"); }
  finally { await keyboard.up("s"); }

  const declared=[];
  for (const check of checks) {
    // Steering needs forward motion. Preserve the rest of the designer's inputs as written.
    const steeringInput=check.signal==="screen-x";
    if (steeringInput) await keyboard.down("w");
    try { declared.push(...await checkInputs(frame,[check])); }
    finally { if (steeringInput) await keyboard.up("w"); }
  }

  return {webgl:true, camera:"chase", accelerate:true, steer:true, steering, brake:true, boost:true,
    checkpoint:driven.checkpoint, pickups:driven.collected, collisions:driven.impacts, energy:driven.energy,
    ...(declared.length?{checks:declared}:{})};
}
