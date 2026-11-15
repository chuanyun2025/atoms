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
  VALIDATOR_REJECTED:"预览检查服务拒绝了请求。",
  MODEL_AUTH:"模型服务认证失败，请联系管理员检查配置。",
  PROVIDER_NOT_CONFIGURED:"模型服务尚未配置，请联系管理员。",
  insufficient_credits:"可用积分不足，已有草稿可以继续查看。",
  QUEUE_TIMEOUT:"排队超时，生成服务未领取任务。",
  TIMEOUT:"任务超过执行时限。",
  WORKER_LOST:"生成服务连接中断。",
  WORKER_STOPPED:"生成服务已停止。",
};

function validationCause(code:string) {
  if (code==="ARTIFACT_REQUIREMENT") return "生成结果未符合项目要求。";
  if (code.startsWith("ARTIFACT_") || ["MODEL_EMPTY","MODEL_TRUNCATED","MODEL_PROTOCOL"].includes(code)) return "生成产物格式未通过检查。";
  if (code.startsWith("COMPILE_")) return "代码编译未通过。";
  if (code.startsWith("SANDBOX_")) return "代码未通过预览沙箱兼容检查。";
  if (code.startsWith("PREVIEW_")) return "应用预览启动失败。";
}

export default function BuildFailure({message,hasVersion,stale,disabled,sending,onRetry,onEdit,onPreview}:{
  message:Message;hasVersion:boolean;stale:boolean;disabled:boolean;sending:boolean;onRetry:()=>void;onEdit:()=>void;onPreview?:()=>void;
}){
  const acceptance=message.run_error_code==="ACCEPTANCE_FAILED" || message.run_error_code==="ACCEPTANCE_UNCONFIRMED";
  const interrupted=message.run_status==="interrupted";
  const code=message.run_error_code??"";
  const classified=validationCause(code);
  const validation=!!classified || acceptance || code==="VALIDATION_FAILED" || code==="AGENT_RESPONSE_INVALID";
  const stopped=code==="USER_STOPPED";
  const title=stopped?"已停止构建":validation?"这次还没生成可用版本":interrupted?"这次构建已中断":"这次构建没有完成";
  const cause=stopped?"":classified??causes[code]??message.content;
  return <section className="build-failure" data-testid="build-failure" aria-label="构建需要继续处理">
    <div className="failure-title"><AlertCircle size={16}/><strong>{title}</strong></div>
    {cause&&<p className="failure-cause">{cause}</p>}
    <p>{hasVersion?"你可以继续使用当前版本。":"你的需求已保存。"}{message.has_candidate?"可以从已有进度继续，无需重新填写。":"可以直接重新生成。"}</p>
    <div className="failure-actions">
      {!stale&&<button className="continue-button" disabled={disabled||sending} onClick={onRetry}>{sending?<LoaderCircle className="spin" size={14}/>:<RotateCcw size={14}/>} {message.has_candidate?(stopped?"继续构建":"继续修复"):"重新生成"}</button>}
      <button className="failure-edit" disabled={sending} onClick={onEdit}>{stale?"基于当前版本修改":"调整需求"}<ArrowUpRight size={12}/></button>
      {onPreview&&<button type="button" className="failure-edit" onClick={onPreview}>查看临时预览</button>}
    </div>
    <small>{stale?"项目已有更新，请基于当前版本继续构建。":"继续时按实际生成用量扣积分。"}</small>
    {!stopped&&(!validation||classified)&&cause!==message.content&&<details><summary>查看问题详情</summary><pre>{message.content}</pre></details>}
  </section>
}
