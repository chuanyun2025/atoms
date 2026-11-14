import type {Frame} from "playwright";
import {checkInputs,validInputChecks,type InputCheck} from "./input-checks.js";

const path = "src/game/playtest.json";
const root = "[data-game-phase]";

export function readGamePlaytest(files: Record<string, unknown> | undefined, required: boolean): InputCheck[] | undefined {
  const source = files?.[path];
  if (source === undefined && !required) return;
  if (typeof source !== "string" || source.length > 4096) throw new Error("请提供简短的 " + path + "，描述从开局执行的连续试玩");
  let checks: unknown;
  try { checks = JSON.parse(source)?.checks; }
  catch { throw new Error(path + " 必须是有效的 JSON"); }
  if (!Array.isArray(checks) || checks.length < 2 || checks.length > 3) {
    throw new Error(path + " 的 checks 需要 2 至 3 个连续操作");
  }
  const normalized = checks.map((check, index) => {
    const step = {hold_ms:0, min_delta:0.01, ...check};
    if (step.change === "equals" && (typeof step.value === "number" || typeof step.value === "boolean")) {
      step.value = String(step.value);
    }
    if (!validInputChecks([step]) || step.fresh_start) {
      throw new Error(path + " 第 " + (index+1) + " 项格式无效：指定一个输入、signal 和 change；仅 equals 提供 value");
    }
    return step as InputCheck;
  });
  if (normalized.filter(check => check.change !== "unchanged").length < 2) {
    throw new Error(path + " 至少两项应观察到实际玩法状态变化");
  }
  return normalized;
}

export async function runGamePlaytest(frame: Frame, checks: InputCheck[]) {
  const game = frame.locator(root);
  if (await game.count() !== 1 || !await game.isVisible()) throw new Error("连续试玩需要一个可见的 data-game-phase 游戏根节点");
  const start = frame.locator("[data-game-start]:visible:enabled");
  const phase = await game.getAttribute("data-game-phase");
  if (phase !== "playing" && await start.count() === 1) {
    await start.click({timeout:1500}).catch(() => { throw new Error("连续试玩无法点击开局按钮"); });
    await frame.waitForFunction(root => document.querySelector(root)?.getAttribute("data-game-phase") === "playing",
      root,{timeout:4200}).catch(() => { throw new Error("点击开始后，游戏未进入可操作状态"); });
  }
  if (!await frame.evaluate(() => document.hasFocus())) {
    await game.evaluate(element => {
      if (!element.hasAttribute("tabindex")) element.setAttribute("tabindex","-1");
      (element as HTMLElement).focus({preventScroll:true});
    });
  }
  const evidence = [];
  for (const [index,check] of checks.entries()) {
    try {
      // Let the prior input finish rendering before taking the next baseline.
      if (index > 0) await frame.waitForTimeout(100);
      evidence.push(...await checkInputs(frame,[check],true));
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      throw new Error("连续试玩第 " + (index+1) + " 步「" + check.label + "」失败：" + detail.slice(0,900));
    }
  }
  return {status:"observed" as const,action:"gameplay_sequence",steps:evidence.map(step=>({
    ...step,before:step.before.slice(0,160),after:step.after.slice(0,160),
  }))};
}
