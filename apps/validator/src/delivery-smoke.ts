import type {Frame} from "playwright";
import {sampleSlideNavigation} from "./slides-check.js";

export type PreviewKind = "web" | "game" | "slides";
type SmokeResult = {status:"observed" | "unconfirmed" | "issue"; action?:string; diagnostic?:string};

const buttons = 'button:visible:enabled,[role="button"]:visible:not([aria-disabled="true"])';
const startName = /^(?:开始(?:游戏|冒险|挑战|比赛|闯关)?|进入游戏|开玩|start(?: game)?|play(?: now)?)$/i;
const nonGameplay = new RegExp(startName.source + "|暂停|继续|设置|静音|重开|重置|退出|返回|帮助|说明|pause|resume|settings|mute|restart|reset|quit|help","i");

/** A timeout or an unfamiliar UI provides no evidence of a broken interaction. */
export async function deliverySmoke(frame: Frame, kind: PreviewKind, budgetMs: number): Promise<SmokeResult> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<SmokeResult>(resolve => {
    timer = setTimeout(() => resolve({status:"unconfirmed"}), budgetMs);
  });
  try {
    return await Promise.race([exercise(frame,kind), deadline]);
  } catch {
    return {status:"unconfirmed"};
  } finally {
    clearTimeout(timer);
  }
}

async function exercise(frame: Frame, kind: PreviewKind): Promise<SmokeResult> {
  if (kind === "slides") return sampleSlideNavigation(frame);

  const page = frame.page();
  const selector = kind === "game" ? "[data-game-phase]" : "main";
  const snapshot = () => frame.evaluate(selector => {
    const root = document.querySelector(selector) ?? document.body;
    return {
      phase: root.getAttribute("data-game-phase"),
      text: (root as HTMLElement).innerText.replace(/\b\d{1,2}:\d{2}(?:\.\d+)?\b|\b\d+\s*(?:s\b|秒)/gi,"").trim().slice(0,1800),
    };
  },selector);
  const controls = frame.locator(buttons);
  let started = false;
  if (kind === "game") {
    const start = frame.locator("[data-game-start]:visible:enabled").or(frame.getByRole("button",{name:startName}).and(controls));
    if (await start.count() === 1) {
      const before = await snapshot();
      await start.click({timeout:650});
      await page.waitForTimeout(300);
      const after = await snapshot();
      started = before.phase !== after.phase || before.text !== after.text;
      // Countdown and custom UI can be ambiguous. Keep trying a single action.
    }
  }

  const candidates = kind === "game"
    ? controls.and(frame.locator(':not([data-game-start],[data-game-pause],[data-game-resume],[data-game-restart])')).filter({hasNotText:nonGameplay})
    : controls;
  const preferred = candidates.and(frame.locator(kind === "game" ? '[data-game-active="true"],[data-game-input]' : "main *"));
  const mainAction = (await preferred.count() ? preferred : candidates).first();
  const before = await snapshot();
  if (await mainAction.count()) {
    await mainAction.click({timeout:650});
  } else if (kind === "game") {
    const canvas = frame.locator("canvas:visible").first();
    if (!await canvas.count()) return started ? {status:"observed",action:"start"} : {status:"unconfirmed"};
    await canvas.click({timeout:650});
    await page.keyboard.press("ArrowUp",{delay:240});
    await page.waitForTimeout(300);
    // Animation and a running HUD can change independently of the input.
    return started ? {status:"observed",action:"start"} : {status:"unconfirmed",action:"canvas"};
  } else {
    return {status:"unconfirmed"};
  }
  await page.waitForTimeout(300);
  const after = await snapshot();
  if (before.phase !== after.phase || before.text !== after.text) return {status:"observed",action:"button"};
  return started ? {status:"observed",action:"start"} : {status:"unconfirmed",action:"button"};
}
