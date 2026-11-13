import { useEffect, useRef, useState } from "react";
import { Race, type DriveInput } from "./game/engine";
import { RaceView } from "./game/view";
import { course } from "./game/track";
import { GameHud, timeLabel } from "./components/GameHud";
import "./styles.css";

const controls: Record<string,DriveInput> = {KeyW:"gas",ArrowUp:"gas",KeyS:"brake",ArrowDown:"brake",KeyA:"left",ArrowLeft:"left",KeyD:"right",ArrowRight:"right",ShiftLeft:"boost",ShiftRight:"boost"};

export default function App() {
  const game = useRef(new Race());
  const surface = useRef<HTMLDivElement>(null);
  const screenOffset = useRef(0);
  const [,refresh] = useState(0);
  const [best,setBest] = useState<number | null>(null);
  const race = game.current;
  const publish = () => refresh(value=>value+1);
  const start = () => { game.current = new Race(); game.current.phase="playing"; publish(); };
  const pause = () => { game.current.pause(); publish(); };
  const resume = () => { game.current.phase="playing"; publish(); };
  const input = (name:DriveInput,down:boolean) => game.current.setInput(name,down);

  useEffect(()=>{
    if (!surface.current) return;
    const view = new RaceView(surface.current);
    const storage = (window as Window & {atoms?:{storage?:{get:(key:string)=>unknown;set:(key:string,value:number)=>void;flush:()=>Promise<unknown>}}}).atoms?.storage;
    const saveKey="track-best-"+course.id;
    let record=storage?.get(saveKey);
    if (typeof record==="number") setBest(record);
    let frame = 0, previous = 0, publishAt = 0;
    function loop(now:number) {
      const state = game.current, previousPhase=state.phase;
      const dt = previous ? Math.min(0.1,(now-previous)/1000) : 1/60;
      previous=now;
      state.step(dt);
      screenOffset.current=view.draw(state,dt);
      if (state.phase!==previousPhase || now-publishAt>=55 && state.phase==="playing") {
        publishAt=now; publish();
      }
      if (previousPhase==="playing" && state.phase==="won" && (typeof record!=="number"||state.seconds<record)) {
        record=state.seconds; setBest(state.seconds);
        storage?.set(saveKey,state.seconds); storage?.flush().catch(()=>{});
      }
      frame=requestAnimationFrame(loop);
    }
    function key(event:KeyboardEvent) {
      if (event.type==="keydown" && event.code==="Escape" && !event.repeat && game.current.phase==="playing") {
        event.preventDefault(); pause(); return;
      }
      const name=controls[event.code];
      if (!name) return;
      if(game.current.phase==="playing") event.preventDefault();
      input(name,event.type==="keydown");
    }
    function visibility(){if(document.hidden)pause();}
    window.addEventListener("keydown",key); window.addEventListener("keyup",key);
    window.addEventListener("blur",pause); document.addEventListener("visibilitychange",visibility);
    frame=requestAnimationFrame(loop);
    return ()=>{
      cancelAnimationFrame(frame); view.dispose();
      window.removeEventListener("keydown",key); window.removeEventListener("keyup",key);
      window.removeEventListener("blur",pause); document.removeEventListener("visibilitychange",visibility);
    };
  },[]);

  return <main className={`race ${race.boosting?"boosting":""}`} data-game-phase={race.phase} data-game-actions={race.actions}
    data-race-view="chase" data-race-speed={race.speed.toFixed(2)} data-race-distance={race.distance.toFixed(2)}
    data-race-lateral={race.lateral.toFixed(2)} data-race-collected={race.collected} data-race-impacts={race.impacts}
    data-race-energy={race.energy.toFixed(2)} data-race-checkpoint={race.checkpoint}
    data-playtest-screen-x={screenOffset.current.toFixed(4)} data-playtest-distance={race.distance.toFixed(3)}>
    <div className="race-surface" ref={surface}/>
    <GameHud race={race} pause={pause} input={input}/>
    {race.phase!=="playing" && <div className="race-overlay"><section className="race-menu">
      <span className="track-name">{course.circuit} · 计时赛</span>
      <h1>{race.phase==="ready"?course.title:race.phase==="paused"?"比赛已暂停":"冲线完成"}</h1>
      {race.phase==="ready" && <><p>绕开路障，收集氮气，依次通过检查点冲线。</p><p className="keys">W / ↑ 加速　S / ↓ 刹车　A D 转向　Shift 氮气</p></>}
      {race.phase==="won" && <p>用时 {timeLabel(race.seconds)} · 收集 {race.collected} 个氮气补给</p>}
      {best!==null && <p>个人最佳 {timeLabel(best)}</p>}
      <div className="race-menu-buttons">
        {race.phase==="ready" && <button data-game-start onClick={start}>发车 ↗</button>}
        {race.phase==="paused" && <button data-game-resume onClick={resume}>继续驾驶</button>}
        {race.phase!=="ready" && <button data-game-restart onClick={start}>重新发车</button>}
      </div>
    </section></div>}
  </main>;
}
