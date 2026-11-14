export type ProjectKind="web"|"game"|"slides"|"video";
export type Project={id:string;title:string;kind:ProjectKind;slide_template_id:string|null;revision:number;current_version_id:string|null;active_run_id:string|null;created_at:number;updated_at:number};
export type VideoMedia={asset_id:string;image_asset_id:string|null;model:string;resolution:string;duration:number;audio:boolean};
export type Version={id:string;project_id:string;number:number;title:string;summary:string;created_at:number;parent_version_id:string|null;source_run_id:string;artifact?:{schema_version:"1"|"2"|"3";files:Record<string,string>;media?:VideoMedia}};
export type Run={id:string;project_id:string;prompt:string;status:string;stage:string;error_code:string|null;error_message:string|null;result_version_id:string|null;created_at:number;workspace?:{source_revision:number;has_preview:boolean}|null};
export type RunSource={schema_version:"1"|"2";files:Record<string,string>};
export type Message={id:string;role:string;content:string;run_id:string;created_at:number;run_status?:string;run_error_code?:string;run_prompt?:string;run_base_version_id?:string|null;model_calls?:number;has_candidate?:boolean;retry_of_run_id?:string|null};
export type Capabilities={model_configured:boolean;worker_available:boolean;model:string|null;read_only:boolean;scope:string;video_configured?:boolean;video_model?:string;video_resolution?:string};
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
export function key(){return crypto.randomUUID()}
export const date=(time:number)=>new Date(time*1000).toLocaleString("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"});
export const active=(run?:Run)=>!!run&&["pending","running"].includes(run.status);
