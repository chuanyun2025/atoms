export type Platform = { x: number; y: number; w: number };
export type EnemySpawn = { x: number; floor: number; fast?: boolean };

export const width = 720;
export const height = 420;
export const ground: Platform = { x: 0, y: 398, w: width };

export const levels: { name: string; sky: string; platforms: Platform[]; enemies: EnemySpawn[] }[] = [
  {
    name: "灯塔下层", sky: "#122941",
    platforms: [{ x: 80, y: 312, w: 228 }, { x: 372, y: 226, w: 256 }],
    enemies: [{ x: 220, floor: 0 }, { x: 545, floor: 0 }, { x: 190, floor: 1 }],
  },
  {
    name: "冰晶升降井", sky: "#263055",
    platforms: [{ x: 86, y: 310, w: 178 }, { x: 360, y: 311, w: 269 }, { x: 247, y: 223, w: 242 }],
    enemies: [{ x: 200, floor: 0, fast: true }, { x: 472, floor: 2 }, { x: 560, floor: 2, fast: true }, { x: 339, floor: 3 }],
  },
  {
    name: "极光塔顶", sky: "#153d48",
    platforms: [{ x: 110, y: 318, w: 468 }, { x: 400, y: 233, w: 220 }, { x: 230, y: 148, w: 244 }],
    enemies: [{ x: 435, floor: 0 }, { x: 250, floor: 1, fast: true }, { x: 395, floor: 1 }, { x: 520, floor: 2, fast: true }, { x: 380, floor: 3 }],
  },
];
