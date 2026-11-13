import {AlertCircle,ArrowUpRight,LoaderCircle,RotateCcw} from "lucide-react";
import type {Message} from "./api";

export default function BuildFailure({message,hasVersion,stale,disabled,sending,onRetry,onEdit}:{
  message:Message;hasVersion:boolean;stale:boolean;disabled:boolean;sending:boolean;onRetry:()=>void;onEdit:()=>void;
}){
  const validation=message.run_error_code==="VALIDATION_FAILED" || message.run_error_code==="AGENT_RESPONSE_INVALID";
  const interrupted=message.run_status==="interrupted";
  const title=validation?"这次还没生成可用版本":interrupted?"这次构建已中断":"这次构建没有完成";
  return <section className="build-failure" data-testid="build-failure" aria-label="构建需要继续处理">
    <div className="failure-title"><AlertCircle size={16}/><strong>{title}</strong></div>
    <p>{hasVersion?"你可以继续使用当前版本。":"你的需求已保存。"}{message.has_candidate?"可以从已有进度继续，无需重新填写。":"可以直接重新生成。"}</p>
    <div className="failure-actions">
      {!stale&&<button className="continue-button" disabled={disabled||sending} onClick={onRetry}>{sending?<LoaderCircle className="spin" size={14}/>:<RotateCcw size={14}/>} {message.has_candidate?"继续修复":"重新生成"}</button>}
      <button className="failure-edit" disabled={sending} onClick={onEdit}>{stale?"基于当前版本修改":"调整需求"}<ArrowUpRight size={12}/></button>
    </div>
    <small>{stale?"项目已有更新，请基于当前版本继续构建。":"继续时按实际生成用量扣积分。"}</small>
    {!validation&&<details><summary>查看问题详情</summary><pre>{message.content}</pre></details>}
  </section>
}
