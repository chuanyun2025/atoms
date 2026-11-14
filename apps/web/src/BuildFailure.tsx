import {AlertCircle,ArrowUpRight,LoaderCircle,RotateCcw} from "lucide-react";
import type {Message} from "./api";

const causes:Record<string,string>={
  VALIDATION_FAILED:"预览检查未通过，无法交付可运行的版本。",
  AGENT_RESPONSE_INVALID:"模型没有返回可用的构建计划。",
  MODEL_CONNECTION:"暂时连不上模型服务。",
  MODEL_NETWORK:"模型连接中断，生成未能完成。",
  MODEL_RATE_LIMIT:"模型服务暂时限流，请稍后重试。",
  PROVIDER_RATE_LIMIT:"模型服务繁忙，请稍后重试。",
  VALIDATOR_UNAVAILABLE:"预览检查服务暂时不可用。",
  QUEUE_TIMEOUT:"排队超时，生成服务未领取任务。",
  TIMEOUT:"任务超过执行时限。",
  WORKER_LOST:"生成服务连接中断。",
  WORKER_STOPPED:"生成服务已停止。",
};

export default function BuildFailure({message,hasVersion,stale,disabled,sending,onRetry,onEdit}:{
  message:Message;hasVersion:boolean;stale:boolean;disabled:boolean;sending:boolean;onRetry:()=>void;onEdit:()=>void;
}){
  const validation=message.run_error_code==="VALIDATION_FAILED" || message.run_error_code==="AGENT_RESPONSE_INVALID";
  const interrupted=message.run_status==="interrupted";
  const title=validation?"这次还没生成可用版本":interrupted?"这次构建已中断":"这次构建没有完成";
  const code=message.run_error_code??"";
  const cause=code==="MODEL_TIMEOUT"?message.content:causes[code]??message.content;
  return <section className="build-failure" data-testid="build-failure" aria-label="构建需要继续处理">
    <div className="failure-title"><AlertCircle size={16}/><strong>{title}</strong></div>
    {cause&&<p className="failure-cause">{cause}</p>}
    <p>{hasVersion?"你可以继续使用当前版本。":"你的需求已保存。"}{message.has_candidate?"可以从已有进度继续，无需重新填写。":"可以直接重新生成。"}</p>
    <div className="failure-actions">
      {!stale&&<button className="continue-button" disabled={disabled||sending} onClick={onRetry}>{sending?<LoaderCircle className="spin" size={14}/>:<RotateCcw size={14}/>} {message.has_candidate?"继续修复":"重新生成"}</button>}
      <button className="failure-edit" disabled={sending} onClick={onEdit}>{stale?"基于当前版本修改":"调整需求"}<ArrowUpRight size={12}/></button>
    </div>
    <small>{stale?"项目已有更新，请基于当前版本继续构建。":"继续时按实际生成用量扣积分。"}</small>
    {cause!==message.content&&<details><summary>查看问题详情</summary><pre>{message.content}</pre></details>}
  </section>
}
