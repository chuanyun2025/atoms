import {useEffect,useRef,useState} from "react";
import {ArrowDown,ArrowLeft,ArrowRight,ArrowUp,Pause,Play,RotateCcw} from "lucide-react";

const faces=["☀","☾","✦","♄","☄","❋"];
function shuffledCards() {
  const cards=[...faces,...faces];
  for (let i=cards.length-1;i>0;i--) {
    const j=Math.floor(Math.random()*(i+1));
    [cards[i],cards[j]]=[cards[j],cards[i]];
  }
  return cards;
}

export function MemoryDemo() {
  const [cards,setCards]=useState(shuffledCards);
  const [open,setOpen]=useState<number[]>([]);
  const [matched,setMatched]=useState<number[]>([]);
  const [moves,setMoves]=useState(0);
  useEffect(()=>{
    if (open.length!==2) return;
    const pair=cards[open[0]]===cards[open[1]];
    const timer=window.setTimeout(()=>{
      if (pair) setMatched(previous=>[...previous,...open]);
      setOpen([]);
    },pair?280:720);
    return ()=>window.clearTimeout(timer);
  },[cards,open]);
  function flip(index:number) {
    if (open.length===2 || open.includes(index) || matched.includes(index)) return;
    if (open.length===1) setMoves(value=>value+1);
    setOpen(previous=>[...previous,index]);
  }
  function reset() {
    setCards(shuffledCards());
    setOpen([]);
    setMatched([]);
    setMoves(0);
  }
  return <div className="sample-memory">
    <div className="sample-game-heading">
      <span>{matched.length===cards.length?"配对完成":"翻两张牌，找出相同星象"}</span>
      <strong aria-live="polite">步数 {moves} · 配对 {matched.length/2} / {faces.length}</strong>
    </div>
    <div className="memory-grid">
      {cards.map((face,index)=>{
        const revealed=open.includes(index)||matched.includes(index);
        return <button type="button" key={index} className={revealed?"revealed":""}
          aria-label={"牌 "+(index+1)+(revealed?" "+face:"")} aria-pressed={revealed}
          disabled={matched.includes(index)} onClick={()=>flip(index)}>
          {revealed?face:"✧"}
        </button>;
      })}
    </div>
    <button className="sample-reset" type="button" onClick={reset}><RotateCcw size={14}/>重新洗牌</button>
  </div>;
}

const size=12;
const directions={
  ArrowUp:{x:0,y:-1,label:"向上",Icon:ArrowUp},
  ArrowDown:{x:0,y:1,label:"向下",Icon:ArrowDown},
  ArrowLeft:{x:-1,y:0,label:"向左",Icon:ArrowLeft},
  ArrowRight:{x:1,y:0,label:"向右",Icon:ArrowRight},
};
type Direction=keyof typeof directions;
function newSnake() {
  return {body:[{x:4,y:5},{x:3,y:5},{x:2,y:5}],food:{x:7,y:5},direction:"ArrowRight" as Direction,score:0};
}

export function SnakeDemo() {
  const [snake,setSnake]=useState(newSnake);
  const [phase,setPhase]=useState<"ready"|"playing"|"paused"|"over"|"won">("ready");
  const world=useRef(snake);
  const pending=useRef<Direction>("ArrowRight");
  const board=useRef<HTMLDivElement>(null);
  function move(key:Direction) {
    const current=directions[world.current.direction];
    const next=directions[key];
    if (next.x+current.x!==0 || next.y+current.y!==0) pending.current=key;
  }
  function start() {
    if (phase!=="paused") {
      world.current=newSnake();
      pending.current=world.current.direction;
      setSnake(world.current);
    }
    setPhase("playing");
  }
  useEffect(()=>{
    if (phase!=="playing") return;
    board.current?.focus({preventScroll:true});
    const pause=()=>setPhase("paused");
    const onVisibility=()=>{if (document.hidden) pause()};
    window.addEventListener("blur",pause);
    document.addEventListener("visibilitychange",onVisibility);
    const timer=window.setInterval(()=>{
      const state=world.current;
      const direction=pending.current;
      const movement=directions[direction];
      const head={x:state.body[0].x+movement.x,y:state.body[0].y+movement.y};
      const eats=head.x===state.food.x && head.y===state.food.y;
      const remaining=eats?state.body:state.body.slice(0,-1);
      if (head.x<0 || head.x>=size || head.y<0 || head.y>=size || remaining.some(cell=>cell.x===head.x && cell.y===head.y)) {
        setPhase("over");
        return;
      }
      const body=[head,...remaining];
      const free=eats?Array.from({length:size*size},(_,i)=>({x:i%size,y:Math.floor(i/size)}))
        .filter(cell=>!body.some(part=>part.x===cell.x && part.y===cell.y)):[];
      const food=eats && free.length?free[Math.floor(Math.random()*free.length)]:state.food;
      world.current={body,food,direction,score:state.score+(eats?1:0)};
      setSnake(world.current);
      if (eats && free.length===0) setPhase("won");
    },220);
    return ()=>{
      window.clearInterval(timer);
      window.removeEventListener("blur",pause);
      document.removeEventListener("visibilitychange",onVisibility);
    };
  },[phase]);
  return <div className="sample-snake">
    <div className="sample-game-heading"><span>收集网格中的能量</span><strong aria-live="polite">得分 {snake.score}</strong></div>
    <div className="snake-board" ref={board} tabIndex={0} aria-label="贪吃蛇游戏区域，使用方向键控制"
      onKeyDown={event=>{
        if (phase==="playing" && Object.hasOwn(directions,event.key)) {
          event.preventDefault();
          move(event.key as Direction);
        }
      }}>
      {snake.body.map((cell,index)=><i key={index} aria-hidden="true" className={index===0?"snake-head":"snake-segment"} style={{left:cell.x/size*100+"%",top:cell.y/size*100+"%"}}/>)}
      <i className="snake-food" aria-hidden="true" style={{left:snake.food.x/size*100+"%",top:snake.food.y/size*100+"%"}}/>
      {phase!=="playing" && <div className="snake-overlay">
        {phase==="over" && <span>本局结束</span>}{phase==="won" && <span>完成挑战</span>}
        <button type="button" onClick={start}><Play size={14}/>{phase==="paused"?"继续游戏":phase==="ready"?"开始游戏":"再玩一次"}</button>
      </div>}
    </div>
    <div className="sample-toolbar">
      {(Object.keys(directions) as Direction[]).map(key=>{
        const {Icon,label}=directions[key];
        return <button type="button" key={key} disabled={phase!=="playing"} aria-label={label} onClick={()=>move(key)}><Icon size={16}/></button>;
      })}
      <button type="button" disabled={phase!=="playing"} aria-label="暂停贪吃蛇" onClick={()=>setPhase("paused")}><Pause size={15}/></button>
    </div>
  </div>;
}
