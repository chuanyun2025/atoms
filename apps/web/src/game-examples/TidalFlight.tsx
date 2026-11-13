import {useEffect,useRef,useState,type KeyboardEvent,type PointerEvent} from "react";
import {ArrowLeft,ArrowRight,Diamond,Shield} from "lucide-react";
import {advance,beaconGoal,drawFlight,height,newFlight,progress,section,segments,width,type Flight} from "./flight";
import "./game-examples.css";

export default function TidalFlight(){
  const canvas = useRef<HTMLCanvasElement>(null);
  const current = useRef<Flight>(newFlight());
  const target = useRef(width/2);
  const keys = useRef(new Set<string>());
  const [hud,setHud] = useState(newFlight);
  const bestKey = "atoms:tidal-flight:best";
  const [best,setBest] = useState(()=>{
    try{return Number(localStorage.getItem(bestKey))||0;}catch{return 0;}
  });
  const stage = section(hud.time);
  function steer(delta:number){target.current=Math.max(25,Math.min(width-25,target.current+delta));}
  function publish(flight:Flight){current.current=flight;setHud(flight);}
  function pause(){
    keys.current.clear();
    if(current.current.phase==="playing") publish({...current.current,phase:"paused"});
  }
  function play(){
    if(current.current.phase!=="paused"){current.current=newFlight();target.current=width/2;}
    keys.current.clear();
    publish({...current.current,phase:"playing"});
    canvas.current?.focus({preventScroll:true});
  }
  function restart(){keys.current.clear();target.current=width/2;publish(newFlight());}
  useEffect(()=>{
    const ctx=canvas.current?.getContext("2d");
    if(!ctx) return;
    drawFlight(ctx,current.current);
    if(hud.phase!=="playing") return;
    let frame=0,last=0,lastHud=0;
    const hidden=()=>{if(document.hidden) pause();};
    function tick(time:number){
      if(current.current.phase!=="playing") return;
      const dt=last?Math.min((time-last)/1000,.05):0;
      last=time;
      const direction=Number(keys.current.has("ArrowRight"))-Number(keys.current.has("ArrowLeft"));
      if(direction) steer(direction*dt*320);
      const next=advance(current.current,dt,target.current);
      current.current=next;
      drawFlight(ctx!,next);
      if(time-lastHud>=90||next.phase!=="playing"){setHud(next);lastHud=time;}
      if(next.phase==="playing") frame=requestAnimationFrame(tick);
    }
    window.addEventListener("blur",pause);
    document.addEventListener("visibilitychange",hidden);
    frame=requestAnimationFrame(tick);
    return ()=>{cancelAnimationFrame(frame);window.removeEventListener("blur",pause);document.removeEventListener("visibilitychange",hidden);};
  },[hud.phase]);
  useEffect(()=>{
    if(hud.phase!=="won"&&hud.phase!=="lost") return;
    if(hud.beacons>best){
      setBest(hud.beacons);
      try{localStorage.setItem(bestKey,String(hud.beacons));}catch{/* browser storage is optional for the example */}
    }
  },[hud.phase,hud.beacons,best]);
  function keyDown(event:KeyboardEvent){
    if(hud.phase!=="playing") return;
    if(event.key==="ArrowLeft"||event.key==="ArrowRight"){event.preventDefault();keys.current.add(event.key);}
    if(event.key==="Escape"){event.preventDefault();event.stopPropagation();pause();}
  }
  function aim(event:PointerEvent<HTMLCanvasElement>){
    if(current.current.phase!=="playing") return;
    const rect=event.currentTarget.getBoundingClientRect();
    target.current=(event.clientX-rect.left)/rect.width*width;
  }
  return <section className="tidal-game" onKeyDown={keyDown} onKeyUp={event=>keys.current.delete(event.key)}
    onBlur={event=>{if(!event.currentTarget.contains(event.relatedTarget)) keys.current.clear();}}>
    <header className="mission-header"><div><p className="mission-kicker">潮汐穿梭</p><h3>{segments[stage]}</h3></div>
      <span className="mission-sector">航段 {stage+1} / {segments.length}</span></header>
    <div className="mission-stats">
      <span><Shield size={17}/> 护盾 <b>{hud.shield}</b></span><span><Diamond size={16}/> 信标 <b>{hud.beacons} / {beaconGoal}</b></span>
      <span>本地最佳 <b>{best}</b></span>
    </div>
    <div className="tidal-board">
      <canvas ref={canvas} width={width} height={height} tabIndex={0} aria-label="飞行区域，方向键或拖动控制航向"
        onPointerDown={event=>{event.currentTarget.setPointerCapture(event.pointerId);aim(event);}} onPointerMove={aim}/>
      {hud.phase!=="playing"&&<div className="mission-overlay">
        <strong>{hud.phase==="ready"?"穿越潮汐航道":hud.phase==="paused"?"飞行暂停":hud.phase==="won"?"航线已完成":"本次飞行结束"}</strong>
        <p>{hud.phase==="ready"?"方向键或拖动领航，穿过三个航段，至少收集四枚信标。":hud.phase==="paused"?"继续时从当前航段恢复。":
          hud.phase==="won"?"成功护送 "+hud.beacons+" 枚信标回港。":hud.shield===0?"护盾耗尽，重新出发可尝试绕开浮石。":"抵达港口，但信标不足。"}</p>
        <div className="mission-overlay-actions">
          <button type="button" onClick={play}>{hud.phase==="ready"?"起飞":hud.phase==="paused"?"继续飞行":"再次起飞"}</button>
          {hud.phase==="paused"&&<button type="button" onClick={restart}>重置航程</button>}
        </div>
      </div>}
    </div>
    <div className="flight-progress"><progress aria-label="航程进度" max={100} value={progress(hud.time)}/><span>{progress(hud.time)}%</span></div>
    <div className="mission-input"><div aria-label="飞行方向">
      <button type="button" aria-label="左移" disabled={hud.phase!=="playing"} onClick={()=>steer(-95)}><ArrowLeft size={18}/></button>
      <button type="button" aria-label="右移" disabled={hud.phase!=="playing"} onClick={()=>steer(95)}><ArrowRight size={18}/></button>
    </div><button type="button" disabled={hud.phase!=="playing"} onClick={pause}>暂停飞行</button></div>
  </section>;
}
