import {lazy,Suspense,useEffect,useState} from "react";
import {AlertCircle,ArrowRight,CheckCircle2,Code2,Eye,History,LoaderCircle,Wrench} from "lucide-react";
import {publicGet} from "./api";
import {modes} from "./creationModes";
import Breakout from "./Breakout";
import breakoutRaw from "./Breakout.tsx?raw";
import OrbitCourier from "./game-examples/OrbitCourier";
import orbitRaw from "./game-examples/OrbitCourier.tsx?raw";
import TidalFlight from "./game-examples/TidalFlight";
import tidalRaw from "./game-examples/TidalFlight.tsx?raw";
import {MemoryDemo,SnakeDemo} from "./game-examples/MiniArcade";
import miniArcadeRaw from "./game-examples/MiniArcade.tsx?raw";
import Preview from "./Preview";
import {type StudioExample} from "./studioExamples";

const Code=lazy(()=>import("./Code"));
const emptyEdits:Record<string,string>={};
const publishedSourceCache=new Map<string,Record<string,string>>();

function builtinSourceFiles(example:StudioExample):Record<string,string>|undefined {
  switch (example.id) {
    case "breakout":
      return {"src/App.tsx":breakoutRaw};
    case "orbit":
      return {"src/App.tsx":orbitRaw};
    case "tidal":
      return {"src/App.tsx":tidalRaw};
    case "memory":
    case "snake":
      return {"src/App.tsx":miniArcadeRaw};
    default:
      return undefined;
  }
}

export default function ExamplePreview({example}:{example:StudioExample}) {
  if(example.publishedExample) return <div className="published-example-preview">
    <Preview exampleId={example.publishedExample} reload={0} phone={false} onSaved={()=>{}}/>
  </div>;
  switch (example.id) {
    case "breakout": return <Breakout example/>;
    case "memory": return <MemoryDemo/>;
    case "snake": return <SnakeDemo/>;
    case "orbit": return <OrbitCourier/>;
    case "tidal": return <TidalFlight/>;
  }
}

type ShowcaseView="preview"|"source"|"story";

export function ExampleShowcase({example,busy,onUsePrompt}:{example:StudioExample;busy:boolean;onUsePrompt:(prompt:string)=>void}) {
  const [view,setView]=useState<ShowcaseView>("preview");
  const [files,setFiles]=useState<Record<string,string>|undefined>(()=>
    example.publishedExample?publishedSourceCache.get(example.publishedExample):builtinSourceFiles(example));
  const [sourceError,setSourceError]=useState("");

  useEffect(()=>{
    setView("preview");
    setSourceError("");
    setFiles(example.publishedExample?publishedSourceCache.get(example.publishedExample):builtinSourceFiles(example));
  },[example]);

  useEffect(()=>{
    if(view!=="source"||!example.publishedExample||files)return;
    let cancelled=false;
    setSourceError("");
    publicGet<{files:Record<string,string>}>("/examples/"+example.publishedExample+"/source")
      .then(data=>{
        publishedSourceCache.set(example.publishedExample!,data.files);
        if(!cancelled)setFiles(data.files);
      })
      .catch(e=>{if(!cancelled)setSourceError((e as Error).message||"源码加载失败")});
    return ()=>{cancelled=true};
  },[view,example,files]);

  const story=example.buildStory;
  const storyCredits=story?.credits.replace(/(\.\d*?[1-9])0+$|\.0+$/,"$1");
  return <div className="example-showcase">
    <div className="example-showcase-bar">
      <div className="view-tabs" role="group" aria-label="示例查看模式">
        <button type="button" className={view==="preview"?"selected":""} aria-pressed={view==="preview"} onClick={()=>setView("preview")}><Eye size={14}/>交互预览</button>
        <button type="button" className={view==="source"?"selected":""} aria-pressed={view==="source"} onClick={()=>setView("source")}><Code2 size={14}/>只读源码</button>
        {story&&<button type="button" className={view==="story"?"selected":""} aria-pressed={view==="story"} onClick={()=>setView("story")}><History size={14}/>构建回放</button>}
      </div>
      <span className="example-zero-cost">本地静态快照 · 零积分消耗</span>
    </div>
    <div className="example-modal-content">
      <div className="example-interactive">
        {view==="preview"&&<ExamplePreview example={example}/>}
        {view==="source"&&<div className="example-source-view">
          {sourceError?<div className="inline-error" role="alert"><AlertCircle size={15}/>{sourceError}</div>
            :!files?<div className="preview-loading" role="status"><LoaderCircle size={18} className="spin"/>正在读取多文件源码…</div>
            :<Suspense fallback={<div className="preview-loading">正在加载代码查看器…</div>}>
              <Code files={files} edits={emptyEdits} editable={false} onEdit={()=>{}}/>
            </Suspense>}
        </div>}
        {view==="story"&&story&&<section className="build-story-view" aria-label="构建过程回放">
          <div className="build-story-metrics">
            <div><span>端到端耗时</span><strong>{story.elapsedSeconds.toFixed(1)}s</strong></div>
            <div><span>模型调用</span><strong>{story.modelCalls} 次</strong></div>
            <div><span>自动修复</span><strong>{story.repairRounds?story.repairRounds+" 轮":"一次通过"}</strong></div>
            <div><span>输入 / 输出 Token</span><strong>{story.inputTokens.toLocaleString()} / {story.outputTokens.toLocaleString()}</strong></div>
            <div><span>实扣积分</span><strong>{storyCredits} 积分</strong></div>
          </div>
          <div className="build-story-card">
            <h3>真实首轮输入提示词</h3>
            <p className="build-story-prompt">{story.originalPrompt}</p>
          </div>
          <div className="build-story-card">
            <h3>主 Agent 规划摘要</h3>
            <p>{story.planSummary}</p>
            {!!story.requirements.length&&<ul className="inspector-list">
              {story.requirements.map((req,idx)=><li key={idx}>{req}</li>)}
            </ul>}
            <div className="build-story-tags">
              <span className="story-stack-chip">{story.rendering}</span>
              {story.architecture.map(path=><code key={path}>{path}</code>)}
            </div>
          </div>
          <div className="build-story-card">
            <h3>规划 · 校验 · 自修复真实时间轴{story.runCount>1?`（含继续恢复共 ${story.runCount} 次任务）`:""}</h3>
            <ol className="build-story-timeline">
              {story.stages.map((step,index)=><li key={index} className={"story-step phase-"+step.phase}>
                <span className="story-step-icon">{step.diagnostic||step.phase==="repairing"?<Wrench size={13}/>:<CheckCircle2 size={13}/>}</span>
                <div>
                  <div className="story-step-head">
                    <strong>{step.label}</strong>
                    <span>{step.runIndex?`run#${step.runIndex} · `:""}{step.phase}</span>
                  </div>
                  <p>{step.detail}</p>
                  {step.diagnostic&&<div className="story-diagnostic">
                    <div><code>{step.diagnostic.code}</code>{step.diagnostic.location&&<span>{step.diagnostic.location}</span>}</div>
                    <p>{step.diagnostic.detail}</p>
                  </div>}
                </div>
              </li>)}
            </ol>
          </div>
        </section>}
      </div>
      <div className="example-modal-aside">
        <span className="studio-output">{modes[example.kind].output}</span>
        <p>{example.description}</p>
        {story?<div className="example-aside-meta">
          <span>真实耗时 {story.elapsedSeconds.toFixed(1)}s · {storyCredits} 积分</span>
          <span>{story.repairRounds?`含 ${story.repairRounds} 轮自动修复`:"首轮校验通过"}</span>
        </div>:<div className="example-aside-meta">
          <span>内置原生交互组件示例</span>
        </div>}
        <button type="button" className="studio-submit" disabled={busy} onClick={()=>onUsePrompt(example.prompt)}>使用此示例的提示词 <ArrowRight size={15}/></button>
      </div>
    </div>
  </div>;
}
