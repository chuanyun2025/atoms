import type { HudState, Phase } from "./../game/engine";

interface Props {
  phase: Phase;
  hud: HudState;
  actions: number;
  onStart: () => void;
  onPause: () => void;
  onResume: () => void;
  onRestart: () => void;
  onFire: () => void;
  onReload: () => void;
  onTurn: (dx: number, dy: number) => void;
  onMoveDown: (key: string) => void;
  onMoveUp: (key: string) => void;
}

export default function GameHud({
  phase,
  hud,
  actions,
  onStart,
  onPause,
  onResume,
  onRestart,
  onFire,
  onReload,
  onTurn,
  onMoveDown,
  onMoveUp,
}: Props) {
  const playing = phase === "playing";
  const holdProps = (key: string) => ({
    onPointerDown: () => onMoveDown(key),
    onPointerUp: () => onMoveUp(key),
    onPointerLeave: () => onMoveUp(key),
    onPointerCancel: () => onMoveUp(key),
  });
  return (
    <>
      <div className="hud-top">
        <div className="hp-block">
          <span className="label">生命</span>
          <div className="hp-bar">
            <div className="hp-fill" style={{ width: `${(hud.hp / hud.maxHp) * 100}%` }} />
          </div>
          <span className="value">{hud.hp}</span>
        </div>
        <div className="kills-block">
          <span>击杀 {hud.kills}/{hud.totalEnemies}</span>
          <span className="muted">命中 {hud.hits}/{hud.shots}</span>
        </div>
      </div>

      <div className="ammo-block">
        <span className={hud.ammo === 0 ? "empty" : ""}>{hud.ammo}</span>
        <span className="slash">/ {hud.magSize}</span>
        {hud.reloading && <span className="reload-tip">装填中…</span>}
      </div>

      {playing && (
        <div className="crosshair">
          <span />
        </div>
      )}
      {hud.message && <div className="msg">{hud.message}</div>}

      {playing && (
        <div className="touch-controls">
          <div className="dpad">
            <button
              data-game-action="primary"
              className="pad up"
              {...holdProps("KeyW")}
              aria-label="前进"
            >
              ▲
            </button>
            <button className="pad left" {...holdProps("KeyA")} aria-label="左移">
              ◀
            </button>
            <button className="pad right" {...holdProps("KeyD")} aria-label="右移">
              ▶
            </button>
            <button className="pad down" {...holdProps("KeyS")} aria-label="后退">
              ▼
            </button>
          </div>
          <div className="turn-pad">
            <button className="pad" onClick={() => onTurn(0.16, 0)} aria-label="向左看">
              ⟲
            </button>
            <button className="pad" onClick={() => onTurn(-0.16, 0)} aria-label="向右看">
              ⟳
            </button>
            <button className="pad" onClick={() => onTurn(0, 0.1)} aria-label="向上看">
              ↑
            </button>
            <button className="pad" onClick={() => onTurn(0, -0.1)} aria-label="向下看">
              ↓
            </button>
          </div>
          <div className="action-pad">
            <button className="fire-btn" data-fps-fire onClick={onFire}>
              射击
            </button>
            <button className="reload-btn" data-fps-reload onClick={onReload}>
              换弹
            </button>
          </div>
        </div>
      )}

      {playing && (
        <button className="pause-btn" data-game-pause onClick={onPause} aria-label="暂停">
          ⏸
        </button>
      )}

      {(phase === "ready" || phase === "paused" || phase === "won" || phase === "lost") && (
        <div className="overlay">
          <div className="panel">
            {phase === "ready" && (
              <>
                <h1>仓库突围</h1>
                <p>消灭仓库中全部 4 个敌人。</p>
                <p className="small desktop-controls">WASD 移动 · 鼠标瞄准 · 左键开火 · R 换弹 · Esc 暂停</p>
                <p className="small mobile-controls">方向键移动 · 拖动画面瞄准 · 点击射击或换弹</p>
                <button data-game-start className="primary-btn" onClick={onStart}>
                  开始战斗
                </button>
              </>
            )}
            {phase === "paused" && (
              <>
                <h1>已暂停</h1>
                <p className="small">
                  生命 {hud.hp} · 击杀 {hud.kills}/{hud.totalEnemies} · 动作 {actions}
                </p>
                <button data-game-resume className="primary-btn" onClick={onResume}>
                  继续
                </button>
                <button data-game-restart className="ghost-btn" onClick={onRestart}>
                  重开
                </button>
              </>
            )}
            {phase === "won" && (
              <>
                <h1 className="win">战斗胜利</h1>
                <p>
                  击杀 {hud.kills}/{hud.totalEnemies} · 命中 {hud.hits}/{hud.shots} · 剩余生命 {hud.hp}
                </p>
                <button data-game-restart className="primary-btn" onClick={onRestart}>
                  再来一局
                </button>
              </>
            )}
            {phase === "lost" && (
              <>
                <h1 className="lose">战斗失败</h1>
                <p>
                  击杀 {hud.kills}/{hud.totalEnemies} · 命中 {hud.hits}/{hud.shots}
                </p>
                <button data-game-restart className="primary-btn" onClick={onRestart}>
                  重新开始
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
