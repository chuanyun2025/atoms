import { useEffect, useRef, useState } from "react";
import { createGame, enterStage, tick, type Game } from "./game/engine";
import { ground, height, levels, width } from "./game/levels";

const bindings: Record<string,string> = {
  ArrowLeft:"left", KeyA:"left", ArrowRight:"right", KeyD:"right",
  ArrowUp:"jump", Space:"jump", KeyZ:"throw", KeyX:"kick",
};
const controls = [["left","向左","←"],["right","向右","→"],["jump","跳跃","跳"],["throw","雪球","投"],["kick","推球","推"]];
const hud = (game: Game) => ({
  level: game.level, lives: game.lives, score: game.score, streak: game.streak, phase: game.phase,
  enemies: game.enemies.filter(enemy=>!enemy.defeated).length,
});

function draw(ctx: CanvasRenderingContext2D, game: Game) {
  const level=levels[game.level];
  ctx.fillStyle=level.sky;
  ctx.fillRect(0,0,width,height);
  ctx.fillStyle="#c7f0f6";
  for(let i=0;i<44;i++) {
    const size=i%9===0?3:1;
    ctx.fillRect((i*149+30)%width,(i*61+8)%360,size,size);
  }
  ctx.fillStyle="#0c2238";
  ctx.beginPath();
  ctx.moveTo(0,height);
  for(let i=0;i<=12;i++) ctx.lineTo(i*60,265+(i%2)*46+((i*41)%70));
  ctx.lineTo(width,height);
  ctx.fill();
  for(const floor of [ground,...level.platforms]) {
    ctx.fillStyle="#386d89";
    ctx.fillRect(floor.x,floor.y,floor.w,17);
    ctx.fillStyle="#b8e8e8";
    ctx.fillRect(floor.x,floor.y,floor.w,5);
  }
  for(const enemy of game.enemies) {
    if(enemy.defeated) continue;
    ctx.fillStyle=enemy.rolling?"#fff":enemy.frozen?"#a2e9f0":enemy.hits?"#c295dd":enemy.speed>60?"#ffab7c":"#b79bea";
    ctx.beginPath();
    ctx.arc(enemy.x,enemy.y,enemy.rolling||enemy.frozen?14:12,0,Math.PI*2);
    ctx.fill();
    ctx.fillStyle=enemy.rolling||enemy.frozen?"#488ba5":"#271b48";
    ctx.fillRect(enemy.x-6,enemy.y-3,3,4);
    ctx.fillRect(enemy.x+3,enemy.y-3,3,4);
    if(enemy.frozen) {
      ctx.fillStyle="#80d5eb";
      ctx.fillRect(enemy.x-12,enemy.y-20,24*(enemy.frozen/5),3);
    }
  }
  ctx.fillStyle="#d6fcff";
  for(const shot of game.shots) {
    ctx.beginPath(); ctx.arc(shot.x,shot.y,5,0,Math.PI*2); ctx.fill();
  }
  const {x,y,direction,immunity}=game.player;
  ctx.globalAlpha=immunity>0 && Math.floor(immunity*13)%2===0?0.55:1;
  ctx.fillStyle="#edfdfc";
  ctx.beginPath(); ctx.arc(x,y+4,11,0,Math.PI*2); ctx.arc(x,y-8,8,0,Math.PI*2); ctx.fill();
  ctx.fillStyle="#f2ad63"; ctx.fillRect(x-10,y-2,20,4);
  ctx.fillStyle="#163449"; ctx.fillRect(x+direction*3,y-10,3,3);
  ctx.globalAlpha=1;
}

export default function App() {
  const canvas=useRef<HTMLCanvasElement>(null);
  const game=useRef(createGame());
  const keys=useRef(new Set<string>());
  const [status,setStatus]=useState(()=>hud(game.current));

  useEffect(()=>{
    const ctx=canvas.current?.getContext("2d");
    if(!ctx) return;
    let previous=0, frame=0, lastStatus="";
    const keyDown=(event: KeyboardEvent)=>{
      const action=bindings[event.code];
      if(!action||event.target instanceof HTMLButtonElement&&event.code==="Space") return;
      event.preventDefault();
      keys.current.add(action);
    };
    const keyUp=(event: KeyboardEvent)=>{keys.current.delete(bindings[event.code]);};
    const clear=()=>keys.current.clear();
    function update(now: number) {
      const pressed=keys.current;
      tick(game.current,{move:Number(pressed.has("right"))-Number(pressed.has("left")),
        jump:pressed.has("jump"),throw:pressed.has("throw"),kick:pressed.has("kick")},Math.min((now-(previous||now))/1000,0.025));
      previous=now;
      draw(ctx!,game.current);
      const next=hud(game.current);
      const stamp=JSON.stringify(next);
      if(stamp!==lastStatus) {lastStatus=stamp;setStatus(next);}
      frame=requestAnimationFrame(update);
    }
    frame=requestAnimationFrame(update);
    window.addEventListener("keydown",keyDown);
    window.addEventListener("keyup",keyUp);
    window.addEventListener("blur",clear);
    return ()=>{
      cancelAnimationFrame(frame);
      window.removeEventListener("keydown",keyDown);
      window.removeEventListener("keyup",keyUp);
      window.removeEventListener("blur",clear);
    };
  },[]);

  function start() {
    keys.current.clear();
    if(game.current.phase==="next") game.current.level++;
    else game.current=createGame();
    enterStage(game.current);
    canvas.current?.focus();
  }

  const playing=status.phase==="playing";
  const action=status.phase==="ready"?"开始游戏":status.phase==="next"?"进入下一关":"再来一局";
  return <main data-game-phase={status.phase} data-game-actions={status.score}>
    <header><div><p>极夜巡逻</p><h1>极光雪球</h1></div><span>{status.level+1} / {levels.length}　{levels[status.level].name}</span></header>
    <div className="hud"><span>剩余敌人 <b>{status.enemies}</b></span><span>分数 <b>{status.score}</b></span><span>生命 <b>{status.lives}</b></span>{status.streak>0&&<span>连锁 ×{status.streak}</span>}</div>
    <div className="field">
      <canvas ref={canvas} width={width} height={height} tabIndex={0} aria-label="极光塔平台关卡"/>
      {!playing&&<div className="overlay">
        <strong>{status.phase==="won"?"极光塔已清理":status.phase==="lost"?"巡逻结束":status.phase==="next"?"本关清场":"登上极光塔"}</strong>
        <button type="button" data-game-start={status.phase==="ready"?"":undefined} onClick={start}>{action}</button>
      </div>}
    </div>
    <p className="guide">← → 移动 · 空格跳跃 · Z 投雪球 · X 近身推球。冻住敌人后，把雪球推向同一层的其他敌人。</p>
    <div className="controls">{controls.map(([id,label,symbol])=><button type="button" aria-label={label} key={id}
      onPointerDown={event=>{event.currentTarget.setPointerCapture(event.pointerId);keys.current.add(id);}}
      onPointerUp={()=>keys.current.delete(id)} onLostPointerCapture={()=>keys.current.delete(id)}>{symbol}</button>)}</div>
  </main>;
}
