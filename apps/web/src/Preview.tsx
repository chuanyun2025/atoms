import {useEffect,useRef,useState} from "react";
import {AlertCircle,LoaderCircle} from "lucide-react";
import {api} from "./api";
type Ticket={url:string;instance_id:string;channel_nonce:string;read_only:boolean};
type State={revision:number;values:Record<string,unknown>};
type Message={protocol_version:number;instance_id:string;message_id:string;type:string;payload:Record<string,unknown>};
type PreviewProps={reload:number;phone:boolean;onSaved:(s:string)=>void}&(
  {pid:string;vid:string;exampleId?:never}|{exampleId:string;pid?:never;vid?:never}
);
// Example progress stays in this browser tab and never touches the author's project.
const exampleStates=new Map<string,State>();
export default function Preview({pid,vid,exampleId,reload,phone,onSaved}:PreviewProps){
  const [ticket,setTicket]=useState<Ticket>(),[error,setError]=useState(""),[ready,setReady]=useState(false);
  const snapshot=useRef<State|undefined>(undefined),frame=useRef<HTMLIFrameElement>(null),port=useRef<MessagePort|undefined>(undefined),disposed=useRef(false),timer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined);
  const savedRef=useRef(onSaved); savedRef.current=onSaved;
  useEffect(()=>{
    let cancelled=false;
    disposed.current=false;setTicket(undefined);setError("");setReady(false);savedRef.current("加载中");
    const load=exampleId
      ? Promise.all([api<Ticket>("/examples/"+exampleId+"/preview-ticket"),Promise.resolve(exampleStates.get(exampleId)??{revision:0,values:{}})])
      : Promise.all([api<Ticket>("/projects/"+pid+"/versions/"+vid+"/preview-ticket","POST",{}),api<State>("/projects/"+pid+"/app-state")]);
    load
      .then(([next,state])=>{if(!cancelled){snapshot.current=state;setTicket(next)}}).catch(e=>{if(!cancelled)setError(e.message)});
    timer.current=setTimeout(()=>{if(!cancelled)setError(previous=>previous||"预览加载超时，请重新加载");},10000);
    return ()=>{cancelled=true;disposed.current=true;clearTimeout(timer.current);port.current?.close();port.current=undefined};
  },[pid,vid,exampleId,reload]);
  const init=()=>{
    if(!ticket||!frame.current?.contentWindow||!snapshot.current) return;
    port.current?.close();
    const channel=new MessageChannel();port.current=channel.port1;
    const alive=()=>!disposed.current&&port.current===channel.port1;
    let queue=Promise.resolve(),count=0,windowStart=Date.now(),blocked=false;
    const ids=new Set<string>();
    const state=snapshot.current;
    channel.port1.onmessage=({data:message}:{data:Message})=>{
      if(!alive()||blocked||!message||message.protocol_version!==1||message.instance_id!==ticket.instance_id||
         typeof message.message_id!=="string"||message.message_id.length>100||ids.has(message.message_id)||
         !message.payload||typeof message.payload!=="object") return;
      if(Date.now()-windowStart>1000){count=0;windowStart=Date.now()}
      if(++count>100||ids.size>5000){blocked=true;setError("预览发送了过多消息，请重新加载");channel.port1.close();return}
      ids.add(message.message_id);
      queue=queue.then(async()=>{
        if(!alive()) return;
        const respond=(ok:boolean,error?:string)=>{if(alive())channel.port1.postMessage({instance_id:ticket.instance_id,message_id:message.message_id,ok,error})};
        try{
          if(JSON.stringify(message).length>40000) throw new Error("数据请求过大");
          if(message.type==="runtime.ready"){clearTimeout(timer.current);setReady(true);savedRef.current(ticket.read_only?"历史只读":"已保存");respond(true);return}
          if(message.type==="runtime.error"){setError(String(message.payload.message||"应用运行错误").slice(0,1200));respond(true);return}
          if(message.type==="storage.flush"){if(blocked)throw new Error("数据尚未保存");respond(true);return}
          if(!["storage.set","storage.remove"].includes(message.type)) throw new Error("不支持的预览消息");
          if(ticket.read_only) throw new Error("历史版本为只读，恢复后可以保存业务数据");
          if(typeof message.payload.key!=="string"||!/^[A-Za-z0-9_.:-]{1,64}$/.test(message.payload.key)||["__proto__","prototype","constructor"].includes(message.payload.key)) throw new Error("存储键无效");
          savedRef.current("保存中");
          if(exampleId){
            if(message.type==="storage.set") state.values[message.payload.key]=message.payload.value;
            else delete state.values[message.payload.key];
            state.revision++;
            exampleStates.set(exampleId,state);
            savedRef.current("已保存");respond(true);return;
          }
          const result=await api<State>("/projects/"+pid+"/app-state","PATCH",{
            expected_revision:state.revision,version_id:vid,set:message.type==="storage.set"?{[message.payload.key]:message.payload.value}:{},
            remove:message.type==="storage.remove"?[message.payload.key]:[]
          });
          state.revision=result.revision;state.values=result.values;
          if(!alive())return;
          savedRef.current("已保存");respond(true);
        }catch(e){
          if(!alive())return;
          const text=(e as Error).message;savedRef.current("未保存");respond(false,text);setError(text);
        }
      });
    };
    frame.current.contentWindow.postMessage({type:"atoms.init",instance_id:ticket.instance_id,channel_nonce:ticket.channel_nonce,values:state.values,read_only:ticket.read_only},"*",[channel.port2]);
  };
  return <div className={"preview-surface "+(phone?"phone":"")} data-testid="preview-surface">
    {ticket&&<iframe key={ticket.instance_id} ref={frame} src={ticket.url} sandbox="allow-scripts allow-pointer-lock" referrerPolicy="no-referrer" title="应用预览" onLoad={init}/>}
    {!ready&&!error&&<div className="preview-loading"><LoaderCircle className="spin" size={22}/><span>正在启动应用预览</span></div>}
    {error&&<div className="preview-error" role="alert"><AlertCircle size={17}/><span>{error}</span></div>}
  </div>
}
