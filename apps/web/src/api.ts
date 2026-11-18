export type ProjectKind="web"|"game"|"slides"|"video";
export type Project={id:string;title:string;kind:ProjectKind;slide_template_id:string|null;revision:number;current_version_id:string|null;active_run_id:string|null;created_at:number;updated_at:number};
export type VideoMedia={asset_id:string;image_asset_id:string|null;model:string;resolution:string;duration:number;audio:boolean};
export type Version={id:string;project_id:string;number:number;title:string;summary:string;created_at:number;parent_version_id:string|null;source_run_id:string;artifact?:{schema_version:"1"|"2"|"3";files:Record<string,string>;media?:VideoMedia}};
export type Run={id:string;project_id:string;prompt:string;status:string;stage:string;error_code:string|null;error_message:string|null;result_version_id:string|null;created_at:number;event_seq?:number;workspace?:{source_revision:number;has_preview:boolean;preview_digest?:string|null}|null};
export type RunSource={schema_version:"1"|"2";files:Record<string,string>};
export type Message={id:string;role:string;content:string;run_id:string;created_at:number;run_status?:string;run_error_code?:string;run_prompt?:string;run_base_version_id?:string|null;model_calls?:number;has_candidate?:boolean;retry_of_run_id?:string|null};
export type PasscodeStatus={id:string;label:string;status:"active"|"exhausted"|"expired"|"revoked";budget:string;spent:string;held:string;remaining:string;remaining_units:number;bypass_daily_budget:boolean;allow_video:boolean;expires_at:number|null};
export type PublicGuardrails={daily_budget_enabled:boolean;daily_budget_credits:string;daily_remaining_credits:string;daily_budget_reached:boolean;reset_at:number;reset_label:string;public_video_enabled:boolean;video_unlocked:boolean;passcode:PasscodeStatus|null};
export type Capabilities={model_configured:boolean;worker_available:boolean;model:string|null;read_only:boolean;scope:string;video_configured?:boolean;video_model?:string;video_resolution?:string;guardrails?:PublicGuardrails};
export type InspectorTaskPlan={
  experience?:string;
  rendering?:string;
  requirements?:string[];
  visual_direction?:string;
  enhancements?:string[];
  game_genre?:string;
  scene_direction?:string;
  mechanics?:{
    initial_state?:string;
    actions?:{input:string;when:string;effects:string[]}[];
    invariants?:string[];
    end_condition?:string|null;
    restart?:string|null;
    examples?:{setup:string;action:string;expected:string}[];
  };
};
export type RunInspector={
  run_id:string;
  project_kind:ProjectKind;
  status:string;
  stage:string;
  version_number:number|null;
  elapsed_seconds:number|null;
  task_plan:InspectorTaskPlan|null;
  validation:{
    ready:boolean;
    acceptance:string|null;
    sandbox_enabled:boolean;
    schema_version:string|null;
    compiler_version:string|null;
    sdk_version:string|null;
    file_count:number;
    static_contract:string;
    generation_skill:{kind?:string;revision?:string}|null;
    website_starter:string|null;
    slide_renderer:string|null;
  }|null;
  repairs:{
    seq:number;
    round:number;
    label:string;
    strategy:string;
    diagnostic:{code?:string;category?:string;file?:string;line?:number;column?:number;subject?:string;occurrences?:number};
    created_at:number;
  }[];
  billing:{
    calls:{
      attempt:number;
      role:"planning"|"generation"|"repair";
      status:string;
      input_tokens:number|null;
      output_tokens:number|null;
      settled_units:number;
      settled_credits:string;
      reserved_credits:string;
      error_code:string|null;
    }[];
    media_calls:{
      purpose:string;
      status:string;
      actual_provider_credits:number|null;
      settled_units:number;
      settled_credits:string;
      error_code:string|null;
    }[];
    total_input_tokens:number;
    total_output_tokens:number;
    total_settled_units:number;
    total_settled_credits:string;
  };
};
type Session={visitor_id:string;csrf_token:string};
let session:Promise<Session>|undefined;
export class ApiError extends Error {
  constructor(message:string,public status:number,public code:string){super(message)}
}
export function bootstrap():Promise<Session>{
  if(!session) session=fetch("/api/v1/session",{method:"POST",headers:{"Content-Type":"application/json","X-App-Request":"atoms"},body:"{}"})
    .then(async r=>{if(!r.ok) throw new Error("无法建立会话，请检查服务并刷新");return r.json()})
    .catch(e=>{session=undefined;throw e});
  return session;
}
export async function api<T>(path:string,method="GET",body?:unknown,headers:Record<string,string>={}):Promise<T>{
  const auth=await bootstrap();
  const response=await fetch("/api/v1"+path,{method,headers:{"Content-Type":"application/json","X-App-Request":"atoms","X-CSRF-Token":auth.csrf_token,...headers},body:body===undefined?undefined:JSON.stringify(body)});
  if(!response.ok){
    const data=await response.json().catch(()=>({}));
    if(response.status===401) session=undefined;
    const detail=data.detail;
    throw new ApiError(typeof detail?.message==="string"?detail.message:response.status===422?"输入内容不符合要求，请检查后重试":"请求失败，请稍后重试",response.status,detail?.code||"request_failed");
  }
  return response.json();
}
export async function publicGet<T>(path:string):Promise<T>{
  const response=await fetch("/api/v1"+path,{headers:{"X-App-Request":"atoms"}});
  if(!response.ok){
    const data=await response.json().catch(()=>({}));
    const detail=data.detail;
    throw new ApiError(typeof detail?.message==="string"?detail.message:"请求失败，请稍后重试",response.status,detail?.code||"request_failed");
  }
  return response.json();
}
export function key(){return crypto.randomUUID()}
export const date=(time:number)=>new Date(time*1000).toLocaleString("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"});
export const active=(run?:Run)=>!!run&&["pending","running"].includes(run.status);
