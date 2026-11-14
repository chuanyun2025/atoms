import type {Frame} from "playwright";

type InputCheck = {
  label: string;
  key?: string | null;
  with_key?: string | null;
  control?: string | null;
  pointer?: "primary" | null;
  hold_ms: number;
  fresh_start?: boolean;
  signal: string;
  change: "increase" | "decrease" | "unchanged" | "equals";
  min_delta: number;
  value?: string | null;
};

const selector = "[data-game-phase]";
const id = /^[a-z][a-z0-9_-]{0,39}$/;
const key = /^(?:[a-z0-9]|Arrow(?:Left|Right|Up|Down)|Space|Enter|Shift)$/;

export class OppositeInputError extends Error {}

export function validInputChecks(value: unknown): value is InputCheck[] {
  return Array.isArray(value) && value.length<=4 && value.every(check=>{
    if (!check || typeof check!=="object") return false;
    const keyInput=typeof check.key==="string" && key.test(check.key) && check.control==null;
    const buttonInput=typeof check.control==="string" && id.test(check.control) && check.key==null;
    const pointerInput=check.pointer==="primary" && check.key==null && check.control==null;
    return (pointerInput || check.pointer==null && (keyInput || buttonInput)) && Number.isInteger(check.hold_ms) && check.hold_ms>=0 && check.hold_ms<=1200 &&
      (check.with_key==null || keyInput && typeof check.with_key==="string" && key.test(check.with_key) && check.with_key!==check.key && check.hold_ms>0) &&
      (check.fresh_start===undefined || typeof check.fresh_start==="boolean") &&
      typeof check.label==="string" && check.label.length>0 && check.label.length<=360 &&
      typeof check.signal==="string" && id.test(check.signal) &&
      ["increase","decrease","unchanged","equals"].includes(check.change) &&
      typeof check.min_delta==="number" && check.min_delta>0 && check.min_delta<=1_000_000 &&
      (check.change==="equals" ? typeof check.value==="string" && check.value.length<=360 : check.value==null);
  });
}

export async function checkInputs(frame: Frame, checks: InputCheck[]) {
  const game=frame.locator(selector);
  const {keyboard,mouse}=frame.page();
  const evidence=[];
  for (const check of checks) {
    const attribute="data-playtest-"+check.signal;
    const initial=await frame.waitForFunction(({selector,attribute,change})=>{
      const value=document.querySelector(selector)?.getAttribute(attribute);
      if (value==null || (change!=="equals" && (value.trim()==="" || !Number.isFinite(Number(value))))) return false;
      return {value};
    },{selector,attribute,change:check.change},{timeout:1400,polling:25}).catch(()=>{
      throw new Error(`实际试玩「${check.label}」缺少状态 ${attribute}`);
    });
    const snapshot=await initial.jsonValue();
    await initial.dispose();
    if (!snapshot) throw new Error(`实际试玩「${check.label}」缺少状态 ${attribute}`);
    const before=snapshot.value;
    async function observe(timeout: number) {
      const result=await frame.waitForFunction(({selector,attribute,before,check})=>{
      const after=document.querySelector(selector)?.getAttribute(attribute);
      if (after==null) return false;
      if (check.change==="equals") return before!==after && after===check.value ? {after} : false;
      if (after.trim()==="" || !Number.isFinite(Number(after))) return false;
      const delta=Number(after)-Number(before);
      if (check.change==="increase" && delta>=check.min_delta || check.change==="decrease" && delta<=-check.min_delta ||
          check.change==="unchanged" && Math.abs(delta)<=check.min_delta) return {after};
      return false;
      },{selector,attribute,before,check},{timeout,polling:25});
      try { return await result.jsonValue(); }
      finally { await result.dispose(); }
    }

    let match: {after:string} | false = false;
    const button=frame.locator(`button[data-game-input="${check.control}"]:enabled:visible`);
    if (check.pointer && !await frame.evaluate(()=>Boolean(document.pointerLockElement))) {
      await frame.locator(`${selector} canvas:visible`).first().hover({timeout:1800});
    }
    if (check.hold_ms) {
      if (check.key) await keyboard.down(check.key);
      else {
        if (!check.pointer) await button.hover({timeout:1800});
        await mouse.down();
      }
      try {
        if (check.with_key) await keyboard.down(check.with_key);
        const duringHold=check.change==="unchanged" ? Promise.resolve(false as const) : observe(check.hold_ms).catch(()=>false as const);
        [match]=await Promise.all([duringHold,frame.waitForTimeout(check.hold_ms)]);
      } finally {
        if (check.with_key) await keyboard.up(check.with_key);
        if (check.key) await keyboard.up(check.key);
        else await mouse.up();
      }
    } else if (check.key) await keyboard.press(check.key);
    else if (check.pointer) {await mouse.down();await mouse.up();}
    else await button.click({timeout:1800,delay:80});

    if (check.change==="unchanged") await frame.waitForTimeout(250);
    match ||= await observe(1600).catch(async()=>{
      const after=await game.getAttribute(attribute);
      const input=check.key??check.control??check.pointer;
      const operation=check.hold_ms ? `按住 ${check.hold_ms}ms` : "短按";
      const message=`实际试玩「${check.label}」未达到 ${check.change}（${operation} ${input}），${check.signal} 从 ${before} 变为 ${after}`;
      const delta=after?.trim() ? Number(after)-Number(before) : NaN;
      if (check.signal.startsWith("screen-") && ((check.change==="increase" && delta<=-check.min_delta) ||
          (check.change==="decrease" && delta>=check.min_delta))) throw new OppositeInputError(message);
      throw new Error(message);
    });
    if (!match) throw new Error(`实际试玩「${check.label}」没有得到可读结果`);
    evidence.push({label:check.label,input:check.key??check.control??check.pointer,signal:check.signal,change:check.change,before,after:match.after});
  }
  return evidence;
}

export type {InputCheck};
