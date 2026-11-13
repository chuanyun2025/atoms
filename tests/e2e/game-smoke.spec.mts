import {test,expect} from "@playwright/test";
import {compileReact} from "../../apps/validator/dist/react-compiler.js";
import {probe} from "../../apps/validator/dist/probe.js";

test("开局按钮被遮挡时只记录输入未确认，点击送达但开局失效时仍报错",async()=>{
  const files={"index.html":'<main data-game-phase="ready"><button data-game-start>开始游戏</button><div class="cover"></div></main>',
    "styles.css":".cover{position:fixed;inset:0;z-index:5}","app.js":"void 0;"};
  const {compile}=await import("../../apps/validator/dist/compiler.js");
  const artifact={schema_version:"1",title:"开始测试",summary:"测试开始按钮",files};
  const report=await probe(compile(artifact),"http://localhost:8082","game-play-v1",[],undefined,[],false,true,true);
  expect(report.gameplay).toMatchObject({core_playable:false,status:"runnable_input_unconfirmed"});
  await expect(probe(compile({...artifact,files:{...files,"styles.css":".cover{display:none}"}}),
    "http://localhost:8082","game-play-v1",[],undefined,[],false,true,true)).rejects.toThrow(/点击开始后游戏仍停在开始界面/);
});

test("纯画布游戏可通过真实点击响应完成通用验收",async()=>{
  const compiled=await compileReact({schema_version:"2",title:"画布交互",summary:"测试纯画布输入",files:{
    "src/App.tsx":`import {useEffect,useRef,useState} from "react";
      import settings from './game/settings.json';
      export default function App(){
        const surface=useRef<HTMLCanvasElement>(null);
        const [position,setPosition]=useState(20);
        useEffect(()=>{
          const context=surface.current!.getContext('2d')!;
          context.clearRect(0,0,320,180);context.fillStyle=settings.color;context.fillRect(position,30,30,30);
        },[position]);
        return <canvas ref={surface} width={320} height={180} onPointerDown={()=>setPosition(value=>value+40)}/>;
      }`,
    "src/styles.css":"body{margin:0}canvas{display:block}",
    "src/game/settings.json":'{"color":"red"}',
  }});
  const report=await probe(compiled,"http://localhost:8082","game-play-v1",[],undefined,[],false,true);
  expect(report.gameplay).toMatchObject({core_playable:true,input:"pointer"});
});

test("操作后异步抛出的运行错误会阻止交付",async()=>{
  const compiled=await compileReact({schema_version:"2",title:"运行错误",summary:"测试运行异常捕获",files:{
    "src/App.tsx":`import {useState} from "react";
      import settings from './game/settings.json';
      export default function App(){
        const [count,setCount]=useState(0);
        return <button onClick={()=>{setCount(count+1);setTimeout(()=>{throw new Error(settings.error)},30)}}>操作 {count}</button>;
      }`,
    "src/styles.css":"body{margin:0}",
    "src/game/settings.json":'{"error":"input handler failed"}',
  }});
  await expect(probe(compiled,"http://localhost:8082","game-play-v1",[],undefined,[],false,true,true))
    .rejects.toThrow(/input handler failed/);
});
