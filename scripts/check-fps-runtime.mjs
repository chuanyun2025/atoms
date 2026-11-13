import assert from "node:assert/strict";
import {readFile,readdir} from "node:fs/promises";
import {fileURLToPath} from "node:url";
import {resolve,relative} from "node:path";
import {compileReact} from "../apps/validator/dist/react-compiler.js";
import {probe} from "../apps/validator/dist/probe.js";
import {FPS_CHECK} from "../apps/validator/dist/fps-check.js";

// Uses local source and Chromium; no provider calls or project writes.
const directory=fileURLToPath(new URL("../apps/api/atoms/game_references/first-person",import.meta.url));
const files={};
for(const entry of await readdir(directory,{recursive:true,withFileTypes:true})){
  if(!entry.isFile())continue;
  const path=resolve(entry.parentPath,entry.name);
  files[relative(directory,path).replaceAll("\\","/")]=await readFile(path,"utf8");
}
const compiled=await compileReact({schema_version:"2",title:"FPS 引擎验收",summary:"参考工程",files});
const report=await probe(compiled,"http://localhost:8082","game-play-v1",[],FPS_CHECK);
for(const feature of ["webgl","movement","look","hit","reload","pointer_lock","left_click","enemy_tracers","escape_pause","blur_pause","restart"]) {
  assert.equal(report.fps?.[feature],true,feature);
}
assert.ok(report.fps.color_samples>=6);
assert.equal(report.sandbox_enabled,true);
console.log(JSON.stringify(report,null,2));

// Exercise the real enemy and player fire paths against a thin wall right in
// front of the enemy, inside the distance the old muzzle offset skipped.
const coverCase = await compileReact({schema_version:"2",title:"掩体验收",summary:"实心薄墙阻断双方射击",files:{...files,
  "src/App.tsx": `import {useEffect,useRef,useState} from "react";
import {FpsGame} from "./game/fps";
export default function App(){
  const mount=useRef(null);
  const [result,setResult]=useState("验证中");
  useEffect(()=>{
    const game=new FpsGame(mount.current);
    try {
      game.phase="playing";
      game.addBox(0,1.25,3.2,3,2.5,0.06,0xffffff);
      const hp=game.hp, ammo=game.ammo;
      game.enemyFire(game.enemies[0]);
      const [tracer]=game.enemyTracers;
      if(game.hp!==hp || !tracer || tracer.mesh.geometry.parameters.depth>0.21) {
        throw new Error("近处薄墙没有挡住敌方伤害或曳光");
      }
      game.publicFire();
      if(game.ammo!==ammo-1 || game.hits!==0) throw new Error("玩家射击穿透了同一块掩体");
      setResult("双方射击被薄墙挡住");
    } finally {game.dispose();}
  },[]);
  return <main><div ref={mount}/><p>{result}</p></main>;
}
`,
}});
const coverReport=await probe(coverCase,"http://localhost:8082");
assert.match(coverReport.viewport?.text??"",/双方射击被薄墙挡住/);
console.log("Thin cover blocked both shots and clipped the tracer");

// Reproduce the reported regressions independently using real browser input.
const enginePath="src/game/fps.ts";
const engine=files[enginePath].replaceAll("\r\n","\n");
for(const regression of [
  {before: 'document.pointerLockElement === canvas || e.target === canvas',
   after: 'e.buttons === 1 && (document.pointerLockElement === canvas || e.target === canvas)',
   message: /不按鼠标键移动时视角没有转动/},
  {before: 'this.enemyTracers.push({ mesh: tracer, time: 0.30 });',
   after: 'this.disposeTracer(tracer);', message: /没有同时观察到敌人开火/},
  {before: 'private onBlur = () => {\n    this.gamePause();',
   after: 'private onBlur = () => {\n    throw new TypeError("this.pause is not a function");', message: /this\.pause is not a function/},
]) {
  assert.ok(engine.includes(regression.before));
  const changed={...files,[enginePath]:engine.replace(regression.before,regression.after)};
  const candidate=await compileReact({schema_version:"2",title:"FPS 回归检查",summary:"参考工程",files:changed});
  await assert.rejects(probe(candidate,"http://localhost:8082","game-play-v1",[],FPS_CHECK),regression.message);
  console.log(`Rejected regression: ${regression.message.source}`);
}
