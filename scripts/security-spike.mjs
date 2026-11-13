// Run via stdin in the validator container. No network/model credentials are printed.
import {compile} from "/app/apps/validator/dist/compiler.js";
import {probe} from "/app/apps/validator/dist/probe.js";
const artifact={schema_version:"1",title:"隔离检查",summary:"验证隔离边界",files:{
  "index.html":"<main><h1>隔离检查</h1><button>测试</button></main>","styles.css":"body{color:green}",
  "app.js":[
    "(async()=>{let denied=false;try{void parent.document.body}catch{denied=true}if(!denied)throw Error('父页面DOM未隔离');",
    "denied=false;try{localStorage.setItem('probe','x')}catch{denied=true}if(!denied)throw Error('原生存储未隔离');",
    "let connected=false;try{await fetch('https://example.com/private',{credentials:'include'});connected=true}catch{}if(connected)throw Error('外部fetch未阻止');",
    "const opened=await new Promise(resolve=>{try{const ws=new WebSocket('wss://example.com');ws.onopen=()=>{ws.close();resolve(true)};ws.onerror=()=>resolve(false);ws.onclose=()=>resolve(false);setTimeout(()=>resolve(false),200)}catch{resolve(false)}});if(opened)throw Error('WebSocket未阻止');",
    "document.querySelector('h1').textContent='隔离检查通过';})();"
  ].join("")
}};
const report=await probe(compile(artifact),process.env.APP_ORIGIN);
if(!report.ready||!report.sandbox_enabled)throw Error("sandbox failed");
console.log("DOM/storage/fetch/WebSocket isolation: PASS");
const bad={...artifact,files:{...artifact.files,"app.js":"while(true){}"}};
const started=Date.now();
const result=await fetch("http://localhost:9000/internal/validate",{method:"POST",headers:{"Content-Type":"application/json","Authorization":"Bearer "+process.env.SERVICE_TOKEN},body:JSON.stringify({artifact:bad,app_origin:process.env.APP_ORIGIN})}).then(r=>r.json());
if(result.ok||Date.now()-started>15000)throw Error("watchdog failed");
console.log("Infinite-loop process watchdog: PASS ("+(Date.now()-started)+"ms)");
const good=await fetch("http://localhost:9000/internal/validate",{method:"POST",headers:{"Content-Type":"application/json","Authorization":"Bearer "+process.env.SERVICE_TOKEN},body:JSON.stringify({artifact,app_origin:process.env.APP_ORIGIN})}).then(r=>r.json());
if(!good.ok)throw Error("Validator did not recover after watchdog");
console.log("Validator recovery after hard kill: PASS");
