export type Point = { x: number; y: number };
export type Enemy = { progress: number; speed: number; hp: number; reward: number; damage: number };
export type Tower = Point & { range: number; damage: number; interval: number; cooldown: number; cost: number };
export type Wave = { time: number; nextSpawn: number; enemies: Enemy[]; gold: number; lives: number };
export type Spawn = { at: number; hp: number; speed: number; reward: number; damage: number };

// progress counts route segments. Store a route with comparable segment lengths, or use your own distance sampler.
export function position(route: Point[], progress: number): Point {
  const segment = Math.min(route.length - 2, Math.floor(progress));
  const amount = Math.min(1, progress - segment);
  const from = route[segment], to = route[segment + 1];
  return { x: from.x + (to.x - from.x) * amount, y: from.y + (to.y - from.y) * amount };
}

export function buildTower(wave: Wave, towers: Tower[], tower: Tower, buildSites: Point[]): boolean {
  const atSite = (p: Point) => p.x === tower.x && p.y === tower.y;
  if (!buildSites.some(atSite) || towers.some(atSite) || wave.gold < tower.cost) return false;
  wave.gold -= tower.cost;
  towers.push({ ...tower, cooldown: 0 });
  return true;
}

export function tickWave(wave: Wave, towers: Tower[], route: Point[], spawns: Spawn[], dt: number) {
  if (wave.lives <= 0) return { ended: true, lost: true };
  wave.time += dt;
  while (wave.nextSpawn < spawns.length && spawns[wave.nextSpawn].at <= wave.time) {
    const spawn = spawns[wave.nextSpawn++];
    wave.enemies.push({ ...spawn, progress: 0 });
  }
  for (const enemy of wave.enemies) enemy.progress += enemy.speed * dt;
  for (const tower of towers) {
    tower.cooldown = Math.max(0, tower.cooldown - dt);
    if (tower.cooldown) continue;
    let target: Enemy | undefined;
    for (const enemy of wave.enemies) {
      if (enemy.hp <= 0 || enemy.progress >= route.length - 1) continue;
      const point = position(route, enemy.progress);
      if (Math.hypot(point.x - tower.x, point.y - tower.y) <= tower.range &&
          (!target || enemy.progress > target.progress)) target = enemy;
    }
    if (target) {
      target.hp -= tower.damage;
      tower.cooldown = tower.interval;
    }
  }
  wave.enemies = wave.enemies.filter(enemy => {
    if (enemy.hp <= 0) wave.gold += enemy.reward;
    else if (enemy.progress >= route.length - 1) wave.lives = Math.max(0, wave.lives - enemy.damage);
    else return true;
    return false;
  });
  const lost = wave.lives <= 0;
  return { ended: lost || (wave.nextSpawn === spawns.length && !wave.enemies.length), lost };
}
