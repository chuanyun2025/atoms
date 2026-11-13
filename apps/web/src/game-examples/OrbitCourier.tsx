import {useEffect,useRef,useState,type KeyboardEvent} from "react";
import {ArrowDown,ArrowLeft,ArrowRight,ArrowUp,BatteryCharging,Radio,RotateCcw} from "lucide-react";
import {loadSector,sectors,step,vectors,type Direction} from "./orbit";
import "./game-examples.css";

const controls = [
  ["ArrowUp","向上",ArrowUp],["ArrowLeft","向左",ArrowLeft],
  ["ArrowDown","向下",ArrowDown],["ArrowRight","向右",ArrowRight],
] as const;

export default function OrbitCourier(){
  const [mission,setMission] = useState(loadSector);
  const board = useRef<HTMLDivElement>(null);
  const sector = sectors[mission.index];
  function move(direction:Direction){setMission(current=>step(current,direction));}
  function play(){setMission(current=>({...current,phase:"playing"}));}
  function restart(){setMission(loadSector(mission.index,mission.previousMoves));}
  function pause(){setMission(current=>current.phase==="playing"?{...current,phase:"paused"}:current);}
  useEffect(()=>{
    if(mission.phase!=="playing") return;
    board.current?.focus({preventScroll:true});
    const hidden=()=>{if(document.hidden) pause();};
    window.addEventListener("blur",pause);
    document.addEventListener("visibilitychange",hidden);
    return ()=>{window.removeEventListener("blur",pause);document.removeEventListener("visibilitychange",hidden);};
  },[mission.phase]);
  function keys(event:KeyboardEvent){
    if(mission.phase==="playing" && Object.hasOwn(vectors,event.key)){
      event.preventDefault();
      move(event.key as Direction);
    }
    if(event.key==="Escape" && mission.phase==="playing"){event.preventDefault();event.stopPropagation();pause();}
  }
  return <section className="orbital-game" onKeyDown={keys}>
    <header className="mission-header">
      <div><p className="mission-kicker">轨道信使</p><h3>{sector.name}</h3></div>
      <span className="mission-sector">航区 {mission.index+1} / {sectors.length}</span>
    </header>
    <div className="mission-stats">
      <span><BatteryCharging size={17}/> 电量 <b>{mission.energy}</b></span>
      <span><Radio size={17}/> 信标 <b>{mission.relays} / {mission.required}</b></span>
      <span>步数 <b>{mission.moves}</b></span>
    </div>
    <div className="orbit-board" ref={board} tabIndex={0} aria-label="轨道地图，按方向键或使用下方按钮移动">
      <div className="orbit-grid" aria-hidden="true">{sector.map.flatMap((row,y)=>Array.from(row,(tile,x)=>{
        const used=mission.used.includes(x+":"+y);
        const item=tile==="#"?"wall":tile==="E"?"exit":tile==="*"&&!used?"relay":tile==="+"&&!used?"charge":tile==="~"?"storm":"floor";
        return <div key={x+":"+y} className={"orbit-cell "+item}>
          {mission.x===x&&mission.y===y?<i className="orbit-ship"/>:
            item==="relay"?"✦":item==="charge"?"+":item==="storm"?"≈":item==="exit"?"◎":null}
        </div>;
      }))}</div>
      {mission.phase!=="playing"&&<div className="mission-overlay">
        <strong>{mission.phase==="ready"?"接通信标":mission.phase==="paused"?"任务暂停":mission.phase==="clear"?"航区已通关":mission.phase==="won"?"全航区已通关":"电量耗尽"}</strong>
        <p>{mission.phase==="ready"?"用方向键或下方按钮移动。收齐 ✦ 后到达 ◎。":mission.phase==="won"?"累计 "+(mission.previousMoves+mission.moves)+" 步完成航线。":mission.message}</p>
        <div className="mission-overlay-actions">
          {(mission.phase==="ready"||mission.phase==="paused")&&<button type="button" onClick={play}>{mission.phase==="ready"?"开始任务":"继续任务"}</button>}
          {mission.phase==="clear"&&<button type="button" onClick={()=>setMission(loadSector(mission.index+1,mission.previousMoves+mission.moves))}>进入下一航区</button>}
          {(mission.phase==="paused"||mission.phase==="lost")&&<button type="button" onClick={restart}>重开本关</button>}
          {mission.phase==="won"&&<button type="button" onClick={()=>setMission(loadSector())}>重新出发</button>}
        </div>
      </div>}
    </div>
    <p className="mission-feedback" role="status">{mission.message}</p>
    <div className="mission-input">
      <div aria-label="方向控制">{controls.map(([key,label,Icon])=>
        <button type="button" key={key} aria-label={label} disabled={mission.phase!=="playing"} onClick={()=>move(key)}><Icon size={18}/></button>
      )}</div>
      <div><button type="button" disabled={mission.phase!=="playing"} onClick={pause}>暂停</button>
        <button type="button" aria-label="重置航区" onClick={restart}><RotateCcw size={16}/></button></div>
    </div>
  </section>;
}
