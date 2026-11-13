import type { Race, DriveInput } from "../game/engine";
import { course, gates, length } from "../game/track";

export const timeLabel = (seconds: number) => `${Math.floor(seconds/60)}:${(seconds%60).toFixed(2).padStart(5,"0")}`;

export function GameHud({race, pause, input}:{race:Race;pause:()=>void;input:(name:DriveInput, down:boolean)=>void}) {
  return <>
    <header className="race-top"><div><span className="track-name">{course.circuit}</span><strong>{course.title}</strong></div>
      <div className="sector"><b>{race.checkpoint}/{gates.length}</b><small>检查点</small></div>
      {race.phase === "playing" && <button data-game-pause onClick={pause} aria-label="暂停比赛">Ⅱ</button>}
    </header>
    <div className="race-progress"><div style={{width:`${race.distance/length*100}%`}}/></div>
    <div className="race-bottom"><div className="speed"><strong>{Math.round(race.speed*5.7)}</strong><small>KM/H</small></div>
      <div className="elapsed"><b>{timeLabel(race.seconds)}</b><small>比赛用时</small></div>
      <div className="energy"><small>氮气 · {Math.round(race.energy)}%</small><progress value={race.energy} max={100}/></div>
    </div>
    {race.phase === "playing" && race.noticeTime>0 && <div className="race-notice" role="status">{race.notice}</div>}
    {race.phase === "playing" && <div className="race-touch">
      {([["left","左转","←"],["right","右转","→"],["brake","刹车","刹车"],["gas","油门","油门"],["boost","氮气","氮气"]] as const).map(([key,label,caption])=><button key={key} aria-label={label}
        data-game-action={key==="gas"?"primary":key}
        onPointerDown={event=>{event.currentTarget.setPointerCapture(event.pointerId);input(key,true);}}
        onLostPointerCapture={()=>input(key,false)} onPointerUp={()=>input(key,false)}>{caption}</button>)}
    </div>}
  </>;
}
