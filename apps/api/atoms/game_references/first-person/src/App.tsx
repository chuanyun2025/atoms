import { useEffect, useRef, useState } from "react";
import { FpsGame, createInitialHud } from "./game/fps";
import type { HudState, Phase } from "./game/engine";
import GameHud from "./components/GameHud";
import "./styles.css";

export default function App() {
  const mountRef = useRef<HTMLDivElement>(null);
  const gameRef = useRef<FpsGame | null>(null);
  const [phase, setPhase] = useState<Phase>("ready");
  const [hud, setHud] = useState<HudState>(createInitialHud);
  const [actions, setActions] = useState(0);

  useEffect(() => {
    if (!mountRef.current) return;
    const game = new FpsGame(mountRef.current);
    gameRef.current = game;
    game.onChange = (s) => {
      setHud(s);
      setPhase(game.phase);
      setActions(game.actions);
    };
    return () => {
      game.dispose();
      gameRef.current = null;
    };
  }, []);

  const start = () => gameRef.current?.gameStart();
  const pause = () => gameRef.current?.gamePause();
  const resume = () => gameRef.current?.gameResume();
  const restart = () => gameRef.current?.gameRestart();
  const fire = () => gameRef.current?.publicFire();
  const reload = () => gameRef.current?.publicReload();
  const turn = (dx: number, dy: number) => gameRef.current?.turn(dx, dy);
  const moveDown = (key: string) => gameRef.current?.setKey(key, true);
  const moveUp = (key: string) => gameRef.current?.setKey(key, false);

  return (
    <div
      className="game-root"
      data-game-phase={phase}
      data-game-actions={actions}
      data-fps-x={hud.x.toFixed(3)}
      data-fps-z={hud.z.toFixed(3)}
      data-fps-yaw={hud.yaw.toFixed(4)}
      data-fps-shots={hud.shots}
      data-fps-hits={hud.hits}
      data-fps-ammo={hud.ammo}
      data-fps-hp={hud.hp}
      data-fps-enemy-shots={hud.enemyShots}
      data-fps-enemy-tracers={hud.enemyTracers}
    >
      <div className="viewport" ref={mountRef} />
      <GameHud
        phase={phase}
        hud={hud}
        actions={actions}
        onStart={start}
        onPause={pause}
        onResume={resume}
        onRestart={restart}
        onFire={fire}
        onReload={reload}
        onTurn={turn}
        onMoveDown={moveDown}
        onMoveUp={moveUp}
      />
    </div>
  );
}
