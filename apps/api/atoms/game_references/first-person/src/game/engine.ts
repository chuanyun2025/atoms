import * as THREE from "three";

/**
 * 引擎共享类型与常量，供 fps.ts（渲染/规则）与 HUD 使用。
 * 真实状态由 FpsGame 持有，这里仅定义协议与固定参数，避免重复实现。
 */

export type Phase = "ready" | "playing" | "paused" | "won" | "lost";

export interface HudState {
  hp: number;
  maxHp: number;
  ammo: number;
  magSize: number;
  kills: number;
  totalEnemies: number;
  shots: number;
  hits: number;
  reloading: boolean;
  x: number;
  z: number;
  yaw: number;
  pitch: number;
  message: string;
  enemyShots: number;
  enemyTracers: number;
}

export const MAG_SIZE = 24;
export const ENEMY_COUNT = 4;
export const RELOAD_TIME = 1.15;
export const FIRE_INTERVAL = 0.13;
export const PLAYER_RADIUS = 0.42;
export const EYE_HEIGHT = 1.62;
export const ENEMY_HP = 100;
export const BULLET_DAMAGE = 45;

export const INITIAL_HUD: HudState = {
  hp: 100,
  maxHp: 100,
  ammo: MAG_SIZE,
  magSize: MAG_SIZE,
  kills: 0,
  totalEnemies: ENEMY_COUNT,
  shots: 0,
  hits: 0,
  reloading: false,
  x: 0,
  z: 11,
  yaw: 0,
  pitch: -0.04,
  message: "",
  enemyShots: 0,
  enemyTracers: 0,
};

/** 玩家出生位置（与设计一致，正前方 8 米处有可见敌人）。 */
export const SPAWN = new THREE.Vector3(0, 0, 11);

/** 敌人初始位置：第一个位于视线前方约 8 米，保证第一枪能命中。 */
export const ENEMY_SPAWNS: Array<[number, number]> = [
  [0, 3],
  [-8, -6],
  [8.5, -4.5],
  [-2.5, 8],
];
