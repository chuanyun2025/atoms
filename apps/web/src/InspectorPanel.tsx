import {useEffect,useRef,useState} from "react";
import {useQuery,useQueryClient} from "@tanstack/react-query";
import {ChevronDown,Cpu,LoaderCircle} from "lucide-react";
import {api,type RunInspector} from "./api";

const roleLabels:Record<string,string>={planning:"规划",generation:"生成",repair:"修复"};
const statusLabels:Record<string,string>={
  settled:"已结算",
  in_flight:"调用中",
  reserved:"预授权",
  released:"已释放",
  uncertain:"待核对",
};

function trimCredits(value:string) {
  return value.replace(/(\.\d*?[1-9])0+$/,"$1").replace(/\.000000$/,".00");
}

function InspectorBody({runId,active}:{runId:string;active:boolean}) {
  const client=useQueryClient();
  const prevActive=useRef(active);

  useEffect(()=>{
    if(prevActive.current&&!active){
      void client.invalidateQueries({queryKey:["run-inspector",runId]});
    }
    prevActive.current=active;
  },[active,runId,client]);

  const {data,isLoading,error}=useQuery({
    queryKey:["run-inspector",runId],
    queryFn:()=>api<RunInspector>("/runs/"+runId+"/inspector"),
    refetchInterval:active?4000:false,
  });

  return <div className="inspector-body">
    {isLoading&&<p className="inspector-muted" role="status"><LoaderCircle size={13} className="spin"/>正在读取底层执行记录…</p>}
    {error&&<p className="inline-error" role="alert">{(error as Error).message}</p>}
    {data&&<>
      <section className="inspector-section" aria-label="规划拆解">
        <h4>① Agent 规划拆解</h4>
        {data.task_plan?<>
          <div className="inspector-badges">
            {data.task_plan.experience&&<span>体验：{data.task_plan.experience}</span>}
            {data.task_plan.rendering&&<span>渲染：{data.task_plan.rendering}</span>}
            {data.task_plan.game_genre&&<span>品类：{data.task_plan.game_genre}</span>}
            {data.elapsed_seconds!==null&&<span>耗时：{data.elapsed_seconds}s</span>}
          </div>
          {data.task_plan.visual_direction&&<p className="inspector-text">{data.task_plan.visual_direction}</p>}
          {!!data.task_plan.requirements?.length&&<ul className="inspector-list">
            {data.task_plan.requirements.map((item,index)=><li key={index}>{item}</li>)}
          </ul>}
          {data.task_plan.mechanics&&<div className="inspector-mechanics">
            <strong>游戏规则状态机（GameMechanics）</strong>
            {data.task_plan.mechanics.initial_state&&<p>初始状态：{data.task_plan.mechanics.initial_state}</p>}
            {!!data.task_plan.mechanics.invariants?.length&&<p>核心不变量：{data.task_plan.mechanics.invariants.join("；")}</p>}
            {data.task_plan.mechanics.end_condition&&<p>胜负条件：{data.task_plan.mechanics.end_condition}</p>}
            {!!data.task_plan.mechanics.examples?.length&&<ul className="inspector-list">
              {data.task_plan.mechanics.examples.map((ex,index)=><li key={index}>样例：{ex.setup} → {ex.action} ⇒ {ex.expected}</li>)}
            </ul>}
          </div>}
        </>:<p className="inspector-muted">此任务未经过协调规划阶段（如模板直出或手动源码保存）。</p>}
      </section>

      <section className="inspector-section" aria-label="沙箱与浏览器校验">
        <h4>② 编译器 · 沙箱契约 · 浏览器验收</h4>
        {data.validation?<div className="inspector-kv-grid">
          <div><span>浏览器验收</span><strong className={data.validation.ready?"positive":""}>{data.validation.ready?"已就绪 ("+(data.validation.acceptance||"startup")+")":"未通过"}</strong></div>
          <div><span>静态契约</span><strong>{data.validation.static_contract}</strong></div>
          <div><span>编译器 / SDK</span><strong>v{data.validation.compiler_version||"-"} / v{data.validation.sdk_version||"-"}</strong></div>
          <div><span>文件模块数</span><strong>{data.validation.file_count} 个文件</strong></div>
          {data.validation.generation_skill?.kind&&<div><span>领域技能</span><strong>{data.validation.generation_skill.kind} ({data.validation.generation_skill.revision})</strong></div>}
          {data.validation.website_starter&&<div><span>基线脚手架</span><strong>{data.validation.website_starter}</strong></div>}
        </div>:<p className="inspector-muted">尚未生成编译与浏览器验收摘要。</p>}
      </section>

      <section className="inspector-section" aria-label="自动修复记录">
        <h4>③ 自动修复诊断记录</h4>
        {data.repairs.length?<ol className="inspector-repairs">
          {data.repairs.map(item=><li key={item.seq}>
            <div className="inspector-repair-head">
              <strong>第 {item.round} 轮</strong>
              {item.diagnostic.code&&<code>{item.diagnostic.code}</code>}
              {item.diagnostic.file&&<span>{item.diagnostic.file}{item.diagnostic.line?`:${item.diagnostic.line}`:""}</span>}
            </div>
            {item.diagnostic.subject&&<p className="inspector-subject">{item.diagnostic.subject}</p>}
            <p className="inspector-strategy">策略：{item.strategy}</p>
          </li>)}
        </ol>:<p className="inspector-muted">首轮校验一次通过，未触发自动修复。</p>}
      </section>

      <section className="inspector-section" aria-label="模型调用与微积分明细">
        <h4>④ 模型调用与微积分账单</h4>
        {data.billing.calls.length||data.billing.media_calls.length?<>
          <div className="inspector-calls">
            {data.billing.calls.map(call=><div key={call.attempt} className="inspector-call-row">
              <span>#{call.attempt} {roleLabels[call.role]||call.role}</span>
              <span>{statusLabels[call.status]||call.status}{call.error_code?` (${call.error_code})`:""}</span>
              <span>入 {(call.input_tokens??0).toLocaleString()} / 出 {(call.output_tokens??0).toLocaleString()} tok</span>
              <strong>{trimCredits(call.settled_credits)} 积分</strong>
            </div>)}
            {data.billing.media_calls.map((mc,index)=><div key={"m"+index} className="inspector-call-row">
              <span>媒体 ({mc.purpose})</span>
              <span>{statusLabels[mc.status]||mc.status}</span>
              <span>供应商用量 {mc.actual_provider_credits??"-"}</span>
              <strong>{trimCredits(mc.settled_credits)} 积分</strong>
            </div>)}
          </div>
          <div className="inspector-totals">
            <span>合计 Token：入 {data.billing.total_input_tokens.toLocaleString()} / 出 {data.billing.total_output_tokens.toLocaleString()}</span>
            <strong>实扣合计：{trimCredits(data.billing.total_settled_credits)} 积分</strong>
          </div>
        </>:<p className="inspector-muted">无付费模型调用（零积分消耗）。</p>}
      </section>
    </>}
  </div>;
}

export default function InspectorDrawer({
  runId,
  label="工程透视",
  active=false,
  variant="inline",
}:{
  runId?:string;
  label?:string;
  active?:boolean;
  variant?:"inline"|"panel";
}) {
  const [open,setOpen]=useState(false);

  useEffect(()=>{
    setOpen(false);
  },[runId]);

  if(!runId) return null;

  return <details className={"inspector-drawer inspector-"+variant} open={open}
    onToggle={event=>setOpen((event.currentTarget as HTMLDetailsElement).open)}>
    <summary>
      <span><Cpu size={13}/>{label}</span>
      <ChevronDown size={14}/>
    </summary>
    {open&&<InspectorBody runId={runId} active={active}/>}
  </details>;
}
