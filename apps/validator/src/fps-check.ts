import type {Frame} from "playwright";
import {checkInputs,type InputCheck} from "./input-checks.js";

export const FPS_CHECK = "fps-3d-v2";
const gameSelector = "[data-game-phase]";
const canvasSelector = "canvas[data-fps-viewport]";

function readRendering() {
  const canvas = document.querySelector<HTMLCanvasElement>("canvas[data-fps-viewport]");
  const gl = canvas?.getContext("webgl2");
  if (!canvas || !gl || gl.isContextLost()) return 0;
  const {width, height} = canvas;
  if (!width || !height || width * height > 4_000_000) return 0;
  const pixels = new Uint8Array(width * height * 4);
  gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
  const colors = new Set<number>();
  for (const x of [0.16, 0.33, 0.5, 0.67, 0.84]) {
    for (const y of [0.2, 0.4, 0.6, 0.8]) {
      const left = Math.floor(width * x);
      const top = Math.floor(height * y);
      for (let row = top; row < Math.min(top + 8, height); row++) {
        for (let column = left; column < Math.min(left + 8, width); column++) {
          const index = (row * width + column) * 4;
          colors.add((pixels[index] << 16) | (pixels[index + 1] << 8) | pixels[index + 2]);
        }
      }
    }
  }
  return colors.size;
}

export async function checkFps(frame: Frame, checks: InputCheck[] = []) {
  const page = frame.page();
  const game = frame.locator(gameSelector);
  const canvas = frame.locator(canvasSelector);

  async function phase(expected: string, locked: boolean) {
    await frame.waitForFunction(({expected, locked, gameSelector, canvasSelector}) => {
      const canvas = document.querySelector(canvasSelector);
      return document.querySelector(gameSelector)?.getAttribute("data-game-phase") === expected &&
        (locked ? !!canvas && document.pointerLockElement === canvas : !document.pointerLockElement);
    }, {expected, locked, gameSelector, canvasSelector}, {timeout: 5000}).catch(() => {
      throw new Error(`FPS 未进入 ${expected} 状态或鼠标锁定状态不正确，请核对开始、Esc、失焦和继续处理`);
    });
  }

  async function control(name: string) {
    await frame.locator(`button[data-game-${name}]:visible`).click({timeout: 10000, force: true});
  }

  async function stats() {
    return game.evaluate(element => {
      const get = (name: string) => {
        const value = element.getAttribute(`data-fps-${name}`);
        if (value === null || value === "" || !Number.isFinite(Number(value))) {
          throw new Error(`FPS 缺少真实状态 data-fps-${name}`);
        }
        return Number(value);
      };
      return {x: get("x"), z: get("z"), yaw: get("yaw"), shots: get("shots"), ammo: get("ammo"),
        hits: get("hits"), hp: get("hp"), enemyShots: get("enemy-shots"), tracers: get("enemy-tracers")};
    });
  }

  await phase("ready", false);
  const initial = await stats();
  await control("start");
  await phase("playing", true);
  await canvas.waitFor({state: "visible", timeout: 5000});
  let colors = await frame.evaluate(readRendering);
  const deadline = Date.now() + 5000;
  while (colors < 6 && Date.now() < deadline) {
    await frame.waitForTimeout(100);
    colors = await frame.evaluate(readRendering);
  }
  if (colors < 6) throw new Error("FPS 预览缺少有实际内容的 WebGL 场景");

  const before = await stats();
  if (before.shots !== 0 || before.hits !== 0) throw new Error("FPS 开始按钮意外触发了射击");
  // Pointer lock routes the native click to the canvas. A shot can miss in
  // a playable level, so check the control independently of target placement.
  await page.mouse.down({button: "left"});
  await page.mouse.up({button: "left"});
  await frame.waitForFunction(({shots, ammo, gameSelector}) => {
    const game = document.querySelector(gameSelector);
    return Number(game?.getAttribute("data-fps-shots")) === shots + 1 &&
      Number(game?.getAttribute("data-fps-ammo")) === ammo - 1;
  }, {...before, gameSelector}, {timeout: 5000, polling: 80}).catch(async () => {
    const after = await stats();
    if (after.shots !== before.shots + 1 || after.ammo !== before.ammo - 1) {
      throw new Error(`FPS 左键未独立开火并消耗一发弹药（射击 ${before.shots} → ${after.shots}，弹药 ${before.ammo} → ${after.ammo}）`);
    }
  });
  await page.keyboard.press("r");
  await frame.waitForFunction(({ammo, gameSelector}) => Number(document.querySelector(gameSelector)?.getAttribute("data-fps-ammo")) === ammo,
    {ammo: before.ammo, gameSelector}, {timeout: 11500, polling: 80}).catch(async () => {
    const {ammo} = await stats();
    if (ammo !== before.ammo) throw new Error(`FPS 按 R 后弹匣未恢复（实际 ${ammo}，预期 ${before.ammo}）`);
  });

  const hitObserved = (await stats()).hits > before.hits;
  await frame.waitForFunction(gameSelector => {
    const game = document.querySelector(gameSelector);
    return Number(game?.getAttribute("data-fps-enemy-shots")) > 0 &&
      Number(game?.getAttribute("data-fps-enemy-tracers")) > 0;
  }, gameSelector, {timeout: 9000, polling: 75}).catch(() => {
    throw new Error("FPS 没有同时观察到敌人开火和在场的弹道效果");
  });
  await frame.waitForFunction(({gameSelector, hp}) => Number(document.querySelector(gameSelector)?.getAttribute("data-fps-hp")) < hp,
    {gameSelector, hp: initial.hp}, {timeout: 5000}).catch(() => {
    throw new Error("FPS 在开阔位置未观察到敌方攻击造成伤害");
  });

  const position = await stats();
  await page.keyboard.down("w");
  try {
    await frame.waitForFunction(({x, z, gameSelector}) => {
      const game = document.querySelector(gameSelector);
      return Math.hypot(Number(game?.getAttribute("data-fps-x")) - x, Number(game?.getAttribute("data-fps-z")) - z) > 0.12;
    }, {...position, gameSelector}, {timeout: 3000});
  } catch {
    throw new Error("FPS 按 W 后玩家在世界里的位置没有移动");
  } finally {
    await page.keyboard.up("w");
  }

  const beforeLook = await stats();
  const box = await canvas.boundingBox();
  if (!box) throw new Error("FPS 画布尺寸无效");
  await page.mouse.move(box.x + box.width * 0.58, box.y + box.height * 0.5, {steps: 3});
  const waitForLook = (timeout: number) => frame.waitForFunction(({yaw, gameSelector}) =>
    Math.abs(Number(document.querySelector(gameSelector)?.getAttribute("data-fps-yaw")) - yaw) > 0.03,
  {yaw: beforeLook.yaw, gameSelector}, {timeout});
  let lookInput: "native_mouse" | "relative_pointer_event" = "native_mouse";
  try {
    await waitForLook(1800);
  } catch {
    // Headless Linux can lock the pointer while dropping relative movement
    // from absolute automation coordinates. Exercise the same input handler.
    lookInput = "relative_pointer_event";
    await canvas.evaluate(element => {
      const movement = {bubbles: true, movementX: 72, movementY: 0, buttons: 0};
      element.dispatchEvent(new PointerEvent("pointermove", {...movement, pointerType: "mouse"}));
      element.dispatchEvent(new MouseEvent("mousemove", movement));
    });
  }
  await waitForLook(3000).catch(() => {
    throw new Error("FPS 不按鼠标键移动时视角没有转动，请检查鼠标锁定和 movementX/movementY");
  });
  if ((await stats()).shots !== beforeLook.shots) throw new Error("FPS 移动鼠标时误触发了开火");
  const checked=checks.length?await checkInputs(frame,checks):[];

  await page.keyboard.press("Escape");
  await phase("paused", false);
  const paused = await stats();
  await page.keyboard.press("w");
  await page.keyboard.press("r");
  if (JSON.stringify(await stats()) !== JSON.stringify(paused)) throw new Error("FPS 暂停期间仍在推进游戏状态");

  await control("resume");
  await phase("playing", true);
  await page.evaluate(() => {
    const outside = document.createElement("button");
    outside.style.position = "fixed";
    outside.style.left = "-100px";
    document.body.append(outside);
    outside.focus({preventScroll: true});
    outside.remove();
  });
  await phase("paused", false);
  await control("restart");
  await phase("ready", false);
  const reset = await stats();
  if (reset.shots || reset.hits || reset.enemyShots || reset.tracers || reset.ammo !== initial.ammo || reset.hp !== initial.hp) {
    throw new Error("FPS 重开没有重置本局的生命、弹药和弹道状态");
  }

  return {webgl: true, color_samples: colors, movement: true, look: true, look_input: lookInput, hit: hitObserved, reload: true,
    pointer_lock: true, left_click: true, enemy_tracers: true, escape_pause: true, blur_pause: true, restart: true,
    ...(checked.length?{checks:checked}:{})};
}
