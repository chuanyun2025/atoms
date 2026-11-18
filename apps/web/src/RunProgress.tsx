import {useEffect,useState} from "react";
import {Check,ChevronDown,LoaderCircle} from "lucide-react";
import InspectorDrawer from "./InspectorPanel";

const stages:Record<string,string>={
  accepted:"等待生成服务", pending:"等待生成服务", read_context:"读取需求与项目上下文", researching:"查找同类游戏和玩法资料",
  planning:"规划实现方案", plan_ready:"构建计划已整理", generating:"正在生成代码", repairing:"修正上一版发现的问题",
  validating:"检查生成内容", source_ready:"源码已可查看", browser_check:"检查预览能否启动",
  validator_wait:"等待校验服务恢复，随后复查已有草稿", model_wait:"等待模型服务恢复", preview_ready:"临时预览已可体验", reviewing:"复核玩法和交互",
  committing:"保存新版本",
};

type ProgressEvent={id:number;kind:string;message?:string;summary?:string;items?:string[];diagnostic?:{file?:string;line?:number}};
const terminals=["completed","failed","interrupted"];
const detailedStages=new Set(["repairing","model_wait","validator_wait"]);
type Connection="connected"|"reconnecting";

export function useRunProgress(runId:string|undefined, onUpdate:(kind:string)=>void){
  const [record,setRecord]=useState<{runId:string;events:ProgressEvent[];connection?:Connection}>();
  useEffect(()=>{
    if(!runId)return;
    const source=new EventSource("/api/v1/runs/"+runId+"/events");
    let finished=false;
    const updateConnection=(connection:Connection)=>{
      if(finished)return;
      setRecord(previous=>({
        runId,events:previous?.runId===runId?previous.events:[],connection,
      }));
    };
    source.onopen=()=>updateConnection("connected");
    source.onerror=()=>updateConnection("reconnecting");
    const receive=(event:Event)=>{
      const item=event as MessageEvent<string>;
      const kind=item.type;
      if(terminals.includes(kind)){
        finished=true;
        source.close();
      }else{
        const id=Number(item.lastEventId);
        const payload=JSON.parse(item.data);
        const next={id,kind,message:payload.message,summary:payload.summary,items:payload.items,diagnostic:payload.diagnostic};
        setRecord(previous=>{
          const events=previous?.runId===runId?previous.events:[];
          if(events.some(entry=>entry.id===id))return previous;
          return {runId,events:[...events,next],connection:previous?.runId===runId?previous.connection:undefined};
        });
      }
      onUpdate(kind);
    };
    for(const kind of [...Object.keys(stages),...terminals])source.addEventListener(kind,receive);
    return()=>{finished=true;source.close()};
  },[runId,onUpdate]);
  return record?.runId===runId?record:undefined;
}

export default function RunProgress({runId,events,stage,eventSeq,connection,busy,onCode,onPreview}:{runId?:string;events:ProgressEvent[];stage?:string;eventSeq?:number;connection?:Connection;busy:boolean;onCode?:()=>void;onPreview?:()=>void}){
  const latest=events.at(-1);
  const snapshotAhead=!!stage&&(eventSeq!==undefined?eventSeq>(latest?.id??0):connection==="reconnecting");
  const current=snapshotAhead?stage:latest?.kind??stage;
  const label=!snapshotAhead&&latest?.kind==="validating"&&latest.message?.startsWith("重新检查")?"复查保留的代码":
    !snapshotAhead&&latest&&detailedStages.has(latest.kind)&&latest.message?latest.message:stages[current??""]??"正在获取任务状态";
  const plan=[...events].reverse().find(event=>event.kind==="plan_ready");
  const steps=events.filter((event,index)=>events[index-1]?.kind!==event.kind);
  const latestSource=[...steps].reverse().find(event=>event.kind==="source_ready");
  if(!busy&&!steps.length)return null;
  return <section className="run-progress" aria-label="构建进度">
    {busy&&<div className="run-progress-current" role="status"><LoaderCircle size={15} className="spin"/>{label}</div>}
    {busy&&!snapshotAhead&&latest?.diagnostic?.file&&<p className="run-connection">
      {latest.diagnostic.file}{latest.diagnostic.line!==undefined?" · 第 "+latest.diagnostic.line+" 行":""}
    </p>}
    {busy&&connection==="reconnecting"&&<p className="run-connection" role="status">实时连接已断开，正在重新连接。任务状态会定时刷新。</p>}
    {busy&&plan&&<div className="run-plan"><p>{plan.summary}</p>{!!plan.items?.length&&<ul>{plan.items.map((item,index)=><li key={index}>{item}</li>)}</ul>}</div>}
    {!!steps.length&&<details className="run-progress-details" key={busy?"active":"finished"} open={busy||undefined}>
      <summary>构建记录<ChevronDown size={14}/></summary>
      <ol>{steps.map((event,index)=>{
        const inProgress=busy&&!snapshotAhead&&index===steps.length-1;
        return <li key={event.id}><span className="run-step-icon">{inProgress?<span/>:<Check size={11}/>}</span>
          <div><span>{detailedStages.has(event.kind)?event.message??stages[event.kind]:stages[event.kind]}</span>
            {!busy&&event.kind==="plan_ready"&&<div className="run-plan">
              {event.summary&&<p>{event.summary}</p>}
              {!!event.items?.length&&<ul>{event.items.map((item,index)=><li key={index}>{item}</li>)}</ul>}
            </div>}
            {busy&&event===latestSource&&onCode&&<button type="button" onClick={onCode}>查看代码</button>}
            {busy&&event.kind==="preview_ready"&&onPreview&&<button type="button" onClick={onPreview}>打开预览</button>}
          </div></li>;
      })}</ol>
    </details>}
    {runId&&<InspectorDrawer runId={runId} active={busy} variant="inline"/>}
  </section>;
}
