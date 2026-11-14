import { ground, levels, width } from "./levels";

const playerRadius = 13;
const enemyRadius = 13;
const freezeDuration = 5;
const jumpSpeed = 440;
const gravity = 850;
type Direction = -1 | 1;
type Input = { move: number; jump: boolean; throw: boolean; kick: boolean };
type Enemy = {
  x: number; y: number; floor: number; direction: Direction; speed: number;
  hits: number; frozen: number; rolling: number; defeated: boolean;
};
type Shot = { x: number; y: number; vx: number; time: number };

export function createGame() {
  return {
    level: 0, phase: "ready" as "ready" | "playing" | "next" | "won" | "lost",
    player: { x: 62, y: ground.y-playerRadius, vy: 0, grounded: true, direction: 1 as Direction, immunity: 0 },
    enemies: [] as Enemy[], shots: [] as Shot[],
    lives: 3, score: 0, streak: 0, cooldown: 0,
  };
}

export type Game = ReturnType<typeof createGame>;

export function enterStage(game: Game) {
  const level = levels[game.level];
  game.phase = "playing";
  Object.assign(game.player, { x: 62, y: ground.y-playerRadius, vy: 0, grounded: true, direction: 1, immunity: 0.8 });
  game.enemies = level.enemies.map(({ x, floor, fast }, index) => ({
    x, floor, y: ([ground, ...level.platforms][floor]).y-enemyRadius, direction: index%2===0?-1:1,
    speed: fast?86:52, hits: 0, frozen: 0, rolling: 0, defeated: false,
  }));
  game.shots = [];
  game.streak = 0;
  game.cooldown = 0;
}

const near = (a: {x:number;y:number}, b: {x:number;y:number}, distance: number) =>
  Math.hypot(a.x-b.x,a.y-b.y) < distance;

export function tick(game: Game, input: Input, dt: number) {
  if (game.phase!=="playing") return;
  const player = game.player;
  const platforms = [ground,...levels[game.level].platforms];
  player.immunity = Math.max(0,player.immunity-dt);
  game.cooldown = Math.max(0,game.cooldown-dt);
  if (input.move) player.direction = input.move<0?-1:1;
  player.x = Math.max(playerRadius,Math.min(width-playerRadius,player.x+input.move*218*dt));
  if (input.jump && player.grounded) player.vy=-jumpSpeed;
  const previousFeet=player.y+playerRadius;
  player.vy+=gravity*dt;
  player.y+=player.vy*dt;
  player.grounded=false;
  for (const floor of [...platforms].sort((a,b)=>a.y-b.y)) {
    if (player.vy<0 || previousFeet>floor.y || player.y+playerRadius<floor.y ||
        player.x<floor.x || player.x>floor.x+floor.w) continue;
    player.y=floor.y-playerRadius;
    player.vy=0;
    player.grounded=true;
    break;
  }

  if (input.throw && game.cooldown===0) {
    game.cooldown=0.21;
    game.shots.push({ x:player.x+player.direction*15, y:player.y, vx:player.direction*420, time:0.72 });
  }
  for (const shot of game.shots) {
    shot.time-=dt;
    shot.x+=shot.vx*dt;
    const target=game.enemies.find(enemy=>!enemy.defeated&&!enemy.frozen&&!enemy.rolling&&near(shot,enemy,17));
    if (target) {
      shot.time=0;
      if (++target.hits>=2) target.frozen=freezeDuration;
    }
  }
  game.shots=game.shots.filter(shot=>shot.time>0&&shot.x>0&&shot.x<width);

  if (input.kick) {
    const target=game.enemies.find(enemy=>!enemy.defeated&&enemy.frozen>0&&near(player,enemy,38));
    if (target) {
      target.frozen=0;
      target.rolling=player.direction*375;
      game.streak=0;
    }
  }
  for (const enemy of game.enemies) {
    if (enemy.defeated) continue;
    const floor=platforms[enemy.floor];
    if (enemy.rolling) {
      enemy.x+=enemy.rolling*dt;
      for (const target of game.enemies) {
        if (target===enemy||target.defeated||target.rolling||!near(enemy,target,30)) continue;
        target.defeated=true;
        game.score+=200+100*game.streak++;
      }
      if (enemy.x<floor.x || enemy.x>floor.x+floor.w) {
        if (enemy.floor===0) {
          enemy.defeated=true;
          game.score+=100;
        } else {
          const landing=platforms.reduce((best,platform,index)=>{
            const current=platforms[best];
            return platform.y>floor.y&&platform.y<current.y&&enemy.x>=platform.x&&enemy.x<=platform.x+platform.w?index:best;
          },0);
          enemy.floor=landing;
          enemy.y=platforms[landing].y-enemyRadius;
        }
      }
      continue;
    }
    if (enemy.frozen>0) {
      enemy.frozen=Math.max(0,enemy.frozen-dt);
      if (enemy.frozen===0) enemy.hits=0;
      continue;
    }
    enemy.x+=enemy.direction*enemy.speed*dt;
    const left=floor.x+enemyRadius, right=floor.x+floor.w-enemyRadius;
    if (enemy.x<=left || enemy.x>=right) {
      enemy.x=Math.max(left,Math.min(right,enemy.x));
      enemy.direction=enemy.x===left?1:-1;
    }
    if (!player.immunity && near(enemy,player,22)) {
      game.lives--;
      player.immunity=1.5;
    }
  }
  if (!game.lives) game.phase="lost";
  else if (game.enemies.every(enemy=>enemy.defeated)) game.phase=game.level+1===levels.length?"won":"next";
}
