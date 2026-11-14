import {useEffect,useState} from "react";
import {Check,ChevronDown,LoaderCircle} from "lucide-react";

const stages:Record<string,string>={
  accepted:"等待生成服务", read_context:"读取需求与项目上下文", researching:"查找同类游戏和玩法资料",
  planning:"规划实现方案", plan_ready:"构建计划已整理", generating:"正在生成代码", repairing:"修正上一版发现的问题",
  validating:"检查生成内容", source_ready:"源码已可查看", browser_check:"启动应用并检查交互",
  validator_wait:"等待校验服务恢复", preview_ready:"临时预览已可体验", reviewing:"复核玩法和交互",
  committing:"保存新版本",
};

type ProgressEvent={id:number;kind:string;message?:string;summary?:string;items?:string[]};
const terminals=["completed","failed","interrupted"];

export function useRunProgress(runId:string|undefined, onUpdate:(kind:string)=>void){
  const [record,setRecord]=useState<{runId:string;events:ProgressEvent[]}>();
  useEffect(()=>{
    if(!runId)return;
    const source=new EventSource("/api/v1/runs/"+runId+"/events");
    const receive=(event:Event)=>{
      const item=event as MessageEvent<string>;
      const kind=item.type;
      if(terminals.includes(kind)){
        source.close();
      }else{
        const id=Number(item.lastEventId);
        const payload=JSON.parse(item.data);
        const next={id,kind,message:payload.message,summary:payload.summary,items:payload.items};
        setRecord(previous=>{
          const events=previous?.runId===runId?previous.events:[];
          if(events.some(entry=>entry.id===id))return previous;
          return {runId,events:[...events,next]};
        });
      }
      onUpdate(kind);
    };
    for(const kind of [...Object.keys(stages),...terminals])source.addEventListener(kind,receive);
    return()=>source.close();
  },[runId,onUpdate]);
  return record?.runId===runId?record?.events??[]:[];
}

export default function RunProgress({events,stage,busy,onCode,onPreview}:{events:ProgressEvent[];stage?:string;busy:boolean;onCode?:()=>void;onPreview?:()=>void}){
  const latest=events.at(-1);
  const label=latest?.kind==="validating"&&latest.message?.startsWith("重新检查")?"复查保留的代码":
    stages[latest?.kind??stage??""]??"等待生成服务";
  const plan=[...events].reverse().find(event=>event.kind==="plan_ready");
  const steps=events.filter((event,index)=>events[index-1]?.kind!==event.kind);
  const latestSource=[...steps].reverse().find(event=>event.kind==="source_ready");
  if(!busy&&!steps.length)return null;
  return <section className="run-progress" aria-label="构建进度">
    {busy&&<div className="run-progress-current" role="status"><LoaderCircle size={15} className="spin"/>{label}</div>}
    {busy&&plan&&<div className="run-plan"><p>{plan.summary}</p>{!!plan.items?.length&&<ul>{plan.items.map((item,index)=><li key={index}>{item}</li>)}</ul>}</div>}
    {!!steps.length&&<details className="run-progress-details" key={busy?"active":"finished"} open={busy||undefined}>
      <summary>构建记录<ChevronDown size={14}/></summary>
      <ol>{steps.map((event,index)=>{
        const inProgress=busy&&index===steps.length-1;
        return <li key={event.id}><span className="run-step-icon">{inProgress?<span/>:<Check size={11}/>}</span>
          <div><span>{stages[event.kind]}</span>
            {!busy&&event.kind==="plan_ready"&&<div className="run-plan">
              {event.summary&&<p>{event.summary}</p>}
              {!!event.items?.length&&<ul>{event.items.map((item,index)=><li key={index}>{item}</li>)}</ul>}
            </div>}
            {busy&&event===latestSource&&onCode&&<button type="button" onClick={onCode}>查看代码</button>}
            {busy&&event.kind==="preview_ready"&&onPreview&&<button type="button" onClick={onPreview}>打开预览</button>}
          </div></li>;
      })}</ol>
    </details>}
  </section>;
}
