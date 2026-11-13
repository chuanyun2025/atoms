import assert from "node:assert/strict";
import {readFile,readdir} from "node:fs/promises";
import {fileURLToPath} from "node:url";
import {resolve,relative} from "node:path";
import {compileReact} from "../apps/validator/dist/react-compiler.js";
import {probe} from "../apps/validator/dist/probe.js";
import {RACE_CHECK} from "../apps/validator/dist/race-check.js";

const directory=fileURLToPath(new URL("../apps/api/atoms/game_references/track-racing",import.meta.url));
const files={};
for(const entry of await readdir(directory,{recursive:true,withFileTypes:true})) {
  if(!entry.isFile()) continue;
  const path=resolve(entry.parentPath,entry.name);
  files[relative(directory,path).replaceAll("\\","/")]=await readFile(path,"utf8");
}
const compiled=await compileReact({schema_version:"2",title:"跟车赛道验收",summary:"验证一场赛道竞速",files});
const declared=[
  {label:"按 A 向左换道",key:"a",hold_ms:320,signal:"screen-x",change:"decrease",min_delta:0.02},
  {label:"按 D 向右换道",key:"d",hold_ms:320,signal:"screen-x",change:"increase",min_delta:0.02},
  {label:"按 W 向前推进",key:"w",hold_ms:400,signal:"distance",change:"increase",min_delta:0.1},
];
const report=await probe(compiled,"http://localhost:8082","game-play-v1",[],RACE_CHECK,declared);
assert.equal(report.game_input_checks,declared.length);
const track="src/game/track.ts";
const timeTrial=files[track].replace(/export const features = \[[\s\S]*?\] as const;/,"export const features = [] as const;");
assert.notEqual(timeTrial,files[track]);
const timeTrialCompiled=await compileReact({schema_version:"2",title:"无道具计时赛",summary:"验证驾驶与计时",files:{...files,[track]:timeTrial}});
const flexible=await probe(timeTrialCompiled,"http://localhost:8082","game-play-v1",[],undefined,[
  {...declared[2]},
  {...declared[0],with_key:"w",fresh_start:true},
],true);
assert.equal(flexible.webgl,true);
assert.equal(flexible.game_input_checks,2);
assert.equal(report.race?.camera,"chase");
for(const feature of ["webgl","accelerate","steer","brake","boost"]) assert.equal(report.race?.[feature],true);
for(const outcome of ["checkpoint","pickups","collisions","energy"]) assert.ok(report.race?.[outcome]>0);
const [right,left]=report.race.steering;
assert.ok(Number(right.after)>Number(right.before));
assert.ok(Number(left.after)<Number(left.before));

const reversed=files[track].replace("new Vector3(-heading.z, 0, heading.x)","new Vector3(heading.z, 0, -heading.x)");
assert.notEqual(reversed,files[track]);
const broken=await compileReact({schema_version:"2",title:"反向控制回归",summary:"模拟横向基向量反转",files:{...files,[track]:reversed}});
await assert.rejects(probe(broken,"http://localhost:8082","game-play-v1",[],RACE_CHECK),/D 向画面右侧换道/);
console.log(JSON.stringify(report,null,2));
