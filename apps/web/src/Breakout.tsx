import {useCallback,useEffect,useRef,useState} from "react";
import {Gamepad2,Heart,Pause,Play,RotateCcw,X} from "lucide-react";

type Phase = "ready" | "playing" | "paused" | "won" | "lost";
const width = 720;
const height = 252;
const paddleWidth = 98;
const paddleY = height - 20;
const radius = 5;
const colors = ["#9b9beb","#f0aabf","#f5c593","#8fcfc8"];
const clamp = (n:number,min:number,max:number) => Math.min(max,Math.max(min,n));

function newRound() {
  return {
    phase: "ready" as Phase,
    paddle: width/2,
    ball: {x:width/2,y:paddleY-8,vx:130,vy:-216},
    bricks: Array.from({length:32},(_,index)=>({
      x:48+(index%8)*79,y:19+Math.floor(index/8)*19,color:colors[Math.floor(index/8)],hit:false,
    })),
    points:0,
    lives:3,
  };
}
type Round = ReturnType<typeof newRound>;

function step(round:Round,delta:number) {
  const ball=round.ball;
  const previousY=ball.y;
  ball.x+=ball.vx*delta;
  ball.y+=ball.vy*delta;
  if (ball.x<=radius || ball.x>=width-radius) {
    ball.x=clamp(ball.x,radius,width-radius);
    ball.vx=ball.x===radius?Math.abs(ball.vx):-Math.abs(ball.vx);
  }
  if (ball.y<=radius) {
    ball.y=radius;
    ball.vy=Math.abs(ball.vy);
  }
  const brick=round.bricks.find(item=>!item.hit && ball.x+radius>=item.x &&
    ball.x-radius<=item.x+71 && ball.y+radius>=item.y && ball.y-radius<=item.y+12);
  if (brick) {
    brick.hit=true;
    round.points+=1;
    if (previousY+radius<=brick.y || previousY-radius>=brick.y+12) ball.vy*=-1;
    else ball.vx*=-1;
    if (round.points===round.bricks.length) return "won";
  }
  if (ball.vy>0 && previousY+radius<=paddleY && ball.y+radius>=paddleY &&
      Math.abs(ball.x-round.paddle)<=paddleWidth/2+radius) {
    const offset=clamp((ball.x-round.paddle)/(paddleWidth/2),-1,1);
    const speed=Math.min(420,Math.hypot(ball.vx,ball.vy)*1.045);
    ball.y=paddleY-radius;
    ball.vx=speed*Math.sin(offset*1.02);
    ball.vy=-speed*Math.cos(offset*1.02);
  }
  if (ball.y>height+radius) {
    round.lives-=1;
    if (!round.lives) return "lost";
    round.ball={x:round.paddle,y:paddleY-9,vx:round.lives===2?-130:130,vy:-216};
    return "paused";
  }
}

function paint(ctx:CanvasRenderingContext2D,round:Round) {
  ctx.clearRect(0,0,width,height);
  for (const brick of round.bricks) {
    if (brick.hit) continue;
    ctx.fillStyle=brick.color;
    ctx.beginPath();
    ctx.roundRect(brick.x,brick.y,71,12,4);
    ctx.fill();
    ctx.fillStyle="#ffffff60";
    ctx.fillRect(brick.x+5,brick.y+2,61,1);
  }
  const paddle=ctx.createLinearGradient(round.paddle-paddleWidth/2,0,round.paddle+paddleWidth/2,0);
  paddle.addColorStop(0,"#ef9b91");
  paddle.addColorStop(.53,"#ad8ee8");
  paddle.addColorStop(1,"#5379df");
  ctx.fillStyle=paddle;
  ctx.beginPath();
  ctx.roundRect(round.paddle-paddleWidth/2,paddleY,paddleWidth,8,4);
  ctx.fill();
  ctx.fillStyle="#6551bb";
  ctx.beginPath();
  ctx.arc(round.ball.x,round.ball.y,radius,0,Math.PI*2);
  ctx.fill();
}

export default function Breakout({collapsed=false,suspended=false,example=false}:{
  collapsed?:boolean;suspended?:boolean;example?:boolean;
}) {
  const round=useRef(newRound());
  const canvas=useRef<HTMLCanvasElement>(null);
  const court=useRef<HTMLDivElement>(null);
  const [phase,setPhase]=useState<Phase>("ready");
  const [folded,setFolded]=useState(false);
  const [stats,setStats]=useState({points:0,lives:3});
  const setRoundPhase=useCallback((value:Phase)=>{
    round.current.phase=value;
    setPhase(value);
  },[]);
  const pause=useCallback(()=>{
    if (round.current.phase==="playing") setRoundPhase("paused");
  },[setRoundPhase]);

  useEffect(()=>{
    const onVisibility=()=>{if (document.hidden) pause()};
    document.addEventListener("visibilitychange",onVisibility);
    window.addEventListener("blur",pause);
    return ()=>{
      document.removeEventListener("visibilitychange",onVisibility);
      window.removeEventListener("blur",pause);
    };
  },[pause]);

  useEffect(()=>{
    if (collapsed || suspended) pause();
    if (collapsed) setFolded(true);
  },[collapsed,suspended,pause]);

  useEffect(()=>{
    const ctx=canvas.current?.getContext("2d");
    if (!ctx || collapsed || suspended) return;
    paint(ctx,round.current);
    if (phase!=="playing") return;
    let previous=0;
    let frame=0;
    function tick(time:number) {
      const state=round.current;
      if (state.phase!=="playing" || !ctx) return;
      let remaining=previous?Math.min((time-previous)/1000,.032):0;
      previous=time;
      const points=state.points,lives=state.lives;
      while (remaining>0) {
        const delta=Math.min(remaining,1/180);
        const result=step(state,delta);
        if (result) {
          setRoundPhase(result);
          break;
        }
        remaining-=delta;
      }
      if (points!==state.points || lives!==state.lives) setStats({points:state.points,lives:state.lives});
      paint(ctx,state);
      if (state.phase==="playing") frame=requestAnimationFrame(tick);
    }
    frame=requestAnimationFrame(tick);
    return ()=>cancelAnimationFrame(frame);
  },[phase,collapsed,suspended,setRoundPhase]);

  useEffect(()=>{
    if (phase==="playing" && !collapsed) court.current?.focus({preventScroll:true});
  },[phase,collapsed]);

  function play() {
    if (phase!=="paused") {
      round.current=newRound();
      setStats({points:0,lives:3});
    }
    setFolded(false);
    setRoundPhase("playing");
  }

  function move(x:number) {
    if (round.current.phase!=="playing") return;
    round.current.paddle=clamp(x,paddleWidth/2,width-paddleWidth/2);
  }

  const status=phase==="won"?"全部砖块已清除":phase==="lost"?"本局结束":phase==="paused"?"已暂停":"";
  const backgroundTarget=!example&&phase!=="playing"&&
    <button type="button" className="breakout-background-target" onClick={play}
      aria-label={phase==="paused"?"继续打砖块":phase==="lost"||phase==="won"?"重新开始打砖块":"开始打砖块"}/>;
  if (collapsed || (!example && (phase==="ready" || folded))) return backgroundTarget;

  return <>
    {backgroundTarget}
    <section className={"breakout "+(example?"breakout-example":"breakout-hero")} aria-label="打砖块试玩" data-phase={phase}>
    <div className="breakout-hud">
      <span><Gamepad2 size={15}/> 得分 <b data-testid="breakout-score">{stats.points} / 32</b></span>
      <span aria-label={"剩余 "+stats.lives+" 次机会"} className="breakout-lives">
        {[0,1,2].map(i=><Heart key={i} size={15} fill={i<stats.lives?"currentColor":"none"} className={i<stats.lives?"":"spent"} aria-hidden="true"/>)}
      </span>
      {!example && <span className="breakout-status" aria-live="polite">{status}</span>}
      <div className="breakout-actions">
        {phase==="playing" && <button type="button" onClick={pause} aria-label="暂停游戏"><Pause size={16}/></button>}
        {!example && <button type="button" onClick={()=>setRoundPhase("ready")} aria-label="结束试玩"><X size={17}/></button>}
      </div>
    </div>
    <div className="breakout-court" ref={court} tabIndex={phase==="playing"?0:-1} aria-label="游戏区域，左右方向键移动，空格暂停"
      onPointerDown={event=>{
        if (event.target!==canvas.current || phase!=="playing") return;
        event.currentTarget.focus({preventScroll:true});
        if (event.pointerType!=="mouse") event.currentTarget.setPointerCapture(event.pointerId);
        const bounds=event.currentTarget.getBoundingClientRect();
        move((event.clientX-bounds.left)*width/bounds.width);
      }}
      onPointerMove={event=>{
        if (phase!=="playing" || (event.pointerType!=="mouse" && !event.currentTarget.hasPointerCapture(event.pointerId))) return;
        const bounds=event.currentTarget.getBoundingClientRect();
        move((event.clientX-bounds.left)*width/bounds.width);
      }}
      onKeyDown={event=>{
        if (event.target!==event.currentTarget || phase!=="playing") return;
        if (event.key==="ArrowLeft" || event.key==="ArrowRight") {
          event.preventDefault();
          move(round.current.paddle+(event.key==="ArrowLeft"?-32:32));
        }
        if (event.code==="Space" || (!example && event.key==="Escape")) {
          event.preventDefault();
          pause();
        }
      }}>
      <canvas ref={canvas} width={width} height={height} aria-hidden="true"/>
      {example && phase!=="playing" && <div className="breakout-overlay">
        <span>{status||"用挡板接住小球，打掉所有砖块"}</span>
        <button type="button" onClick={play}>
          {phase==="lost" || phase==="won"?<RotateCcw size={14}/>:<Play size={14}/>}
          {phase==="paused"?"继续游戏":phase==="ready"?"开始游戏":"再玩一次"}
        </button>
      </div>}
    </div>
    {example && <span className="breakout-hint">移动鼠标、拖动或用方向键控制挡板</span>}
    </section>
  </>;
}
