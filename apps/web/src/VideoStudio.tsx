import {useEffect,useRef,useState,type FormEvent} from "react";
import {Link} from "react-router-dom";
import {useQuery,useQueryClient} from "@tanstack/react-query";
import {ArrowLeft,Clapperboard,Download,ImagePlus,LoaderCircle,Play,Sparkles} from "lucide-react";
import {api,ApiError,key,type Project,type Version,type Message,type Capabilities} from "./api";
import {useCapabilities} from "./Studio";
import {useProjectCreation} from "./useProjectCreation";
import Preview from "./Preview";
import {openWalletDialog,useWallet} from "./Wallet";
import "./video.css";

type VideoInput={image_asset_id:string|null;duration:number;audio:boolean;prompt?:string};
type VideoDraft={prompt:string;dataUrl:string;imageAssetId?:string;duration:number;audio:boolean};
const mediaUrl=(pid:string,id:string)=>`/api/v1/projects/${pid}/media/${id}`;

function unavailable(cap?:Capabilities) {
  if (!cap) return "正在连接创作服务…";
  if (cap.read_only) return "系统维护中，暂时不能生成视频";
  if (!cap.video_configured) return "视频服务尚未连接，请联系管理员";
  if (!cap.worker_available) return "生成服务正在启动，请稍后再试";
  if (cap.guardrails && !cap.guardrails.video_unlocked) return "公共环境默认关闭高成本视频生成，请点击输入体验口令解锁";
  if (cap.guardrails?.daily_budget_reached) return "今日公共体验额度已达上限，请输入体验口令解锁";
  return "";
}

function VideoForm({pid,initial,prompt:initialPrompt="",resolution="540p",busy,unavailableReason,onSubmit,error}:{pid?:string;initial?:VideoInput|null;prompt?:string;resolution?:string;busy:boolean;unavailableReason:string;onSubmit:(value:VideoDraft)=>Promise<void>;error?:string}) {
  const [prompt,setPrompt]=useState(initialPrompt);
  const [dataUrl,setDataUrl]=useState("");
  const [removed,setRemoved]=useState(false);
  const [duration,setDuration]=useState(5);
  const [audio,setAudio]=useState(true);
  const [imageError,setImageError]=useState("");
  const [reading,setReading]=useState(false);
  const file=useRef<HTMLInputElement>(null);
  const reader=useRef<FileReader|null>(null);
  const {data:wallet,error:walletError}=useWallet();
  const {data:quote,error:quoteError}=useQuery({queryKey:["video-quote",duration,resolution],queryFn:()=>api<{credits:string;required_units:number}>("/video/quote?duration="+duration),refetchInterval:30000});
  useEffect(()=>{
    if(initial){setDuration(initial.duration);setAudio(!!initial.audio);if(initial.prompt)setPrompt(initial.prompt);setDataUrl("");setRemoved(false)}
  },[initial?.image_asset_id,initial?.prompt,initial?.duration,initial?.audio]);
  useEffect(()=>()=>reader.current?.abort(),[]);
  const imageAssetId=removed?undefined:initial?.image_asset_id||undefined;
  const poster=dataUrl||(pid&&imageAssetId?mediaUrl(pid,imageAssetId):"");
  const reason=busy?"视频正在生成，可以离开页面，结果会保存在项目中。":unavailableReason|| (reading?"正在读取参考图片…":!prompt.trim()?"请先描述你想生成的视频":quoteError?"费用暂不可用，请稍后重试":walletError?"积分余额暂不可用，请刷新页面":!quote||!wallet?"正在读取费用和可用积分…":wallet.available_units<quote.required_units?`可用积分不足，生成一条视频需要 ${quote.credits} 积分`:"");
  function chooseImage(selected?:File) {
    if(!selected)return;
    setImageError("");
    if(!["image/png","image/jpeg","image/webp"].includes(selected.type)||selected.size>5*1024*1024){
      setImageError("请选择 5 MB 以内的 PNG、JPEG 或 WebP 图片");
      if(file.current) file.current.value="";
      return;
    }
    reader.current?.abort();
    const next=new FileReader();reader.current=next;setReading(true);
    next.onload=()=>{setDataUrl(String(next.result));setRemoved(false);setReading(false)};
    next.onerror=()=>{setImageError("图片读取失败，请重新选择");setReading(false)};
    next.readAsDataURL(selected);
  }
  async function submit(event:FormEvent) {
    event.preventDefault();
    if(reason)return;
    await onSubmit({prompt:prompt.trim(),dataUrl,imageAssetId,duration,audio});
  }
  return <form className="video-form" aria-label="视频生成设置" onSubmit={submit}>
    <div className="video-form-heading"><span><Clapperboard size={17}/>{poster?"图生视频":"文生视频"}</span><small>Vidu Q3 Pro · {resolution}</small></div>
    <label className="video-field-label" htmlFor="video-prompt">描述你想生成的视频</label>
    <textarea id="video-prompt" value={prompt} maxLength={20000} disabled={busy} placeholder="例如：夕阳下的海边，一只金毛奔向镜头，海浪轻轻涌动，镜头缓缓后退，温暖的电影质感。" onChange={event=>setPrompt(event.target.value)}/>
    <label className="video-field-label" htmlFor="video-image">参考图片 <small>可选，不上传也能直接生成</small></label>
    <input ref={file} id="video-image" className="video-file" type="file" accept="image/png,image/jpeg,image/webp" disabled={busy||reading} onChange={event=>chooseImage(event.target.files?.[0])}/>
    <button type="button" className={"video-image-picker "+(poster?"has-image":"")} onClick={()=>file.current?.click()} disabled={busy||reading} aria-label={poster?"更换参考图片":"选择参考图片"}>
      {poster?<><img src={poster} alt="视频参考图片"/><span>更换图片</span></>:<><ImagePlus size={24}/><strong>添加参考图片，让画面从这里开始</strong><span>PNG / JPEG / WebP · 最大 5 MB</span></>}
      {reading&&<LoaderCircle size={22} className="spin"/>}
    </button>
    {poster&&<button type="button" className="video-remove-image" disabled={busy||reading} onClick={()=>{setDataUrl("");setRemoved(true);setImageError("");if(file.current)file.current.value=""}}>移除图片，使用文字生成</button>}
    {imageError&&<p className="inline-error" role="alert">{imageError}</p>}
    <div className="video-options">
      <label>视频时长<select aria-label="视频时长" value={duration} disabled={busy} onChange={event=>setDuration(Number(event.target.value))}>
        {Array.from({length:16},(_,index)=>index+1).map(value=><option key={value} value={value}>{value} 秒</option>)}
      </select></label>
      <label className="video-audio"><input type="checkbox" checked={audio} disabled={busy} onChange={event=>setAudio(event.target.checked)}/>生成声音</label>
    </div>
    <div className="video-quote"><span>每条 <strong>{quote?.credits??"…"} 积分</strong></span><span>可用 {wallet?.available??"…"} 积分</span></div>
    <p className="video-billing-note">提交时预授权，视频生成成功后扣费。确认生成失败后退回预授权积分。</p>
    {error&&<p className="inline-error" role="alert">{error}</p>}
    {reason&&<p id="video-submit-reason" className="video-submit-reason" role="status">{reason}{reason.includes("体验口令")&&<> · <button type="button" className="plain-button" onClick={openWalletDialog}>输入体验码</button></>}</p>}
    <button className="studio-submit video-submit" type="submit" disabled={!!reason} aria-describedby={reason?"video-submit-reason":undefined}>
      {busy?<><LoaderCircle size={17} className="spin"/>正在生成</>:<><Sparkles size={17}/>生成视频</>}
    </button>
  </form>;
}

export function VideoStudio() {
  const {data:cap}=useCapabilities();
  const {create,busy,error}=useProjectCreation(cap);
  return <div className="studio-content video-studio">
    <div className="video-intro"><span className="creative-mark"><Clapperboard size={25}/></span><h1>让你的画面，开始讲故事</h1><p>描述你的想法，直接生成带声音的视频。也可以添加图片作为首帧。</p></div>
    <VideoForm prompt={sessionStorage.getItem("atoms:studio-draft:video")||""} resolution={cap?.video_resolution} busy={busy} unavailableReason={unavailable(cap)} error={error}
      onSubmit={async value=>{await create({kind:"video",prompt:value.prompt,draftKey:"atoms:studio-draft:video",video:{dataUrl:value.dataUrl,duration:value.duration,audio:value.audio}})}}/>
  </div>;
}

export function VideoWorkspace({pid}:{pid:string}) {
  const client=useQueryClient();
  const {data:cap}=useCapabilities();
  const {data:project}=useQuery({queryKey:["project",pid],queryFn:()=>api<Project>("/projects/"+pid),refetchInterval:query=>query.state.data?.active_run_id?2500:false});
  const busy=!!project?.active_run_id;
  const {data:versions}=useQuery({queryKey:["versions",pid],queryFn:()=>api<{items:Version[]}>("/projects/"+pid+"/versions")});
  const {data:input}=useQuery({queryKey:["video-input",pid],queryFn:()=>api<VideoInput|null>("/projects/"+pid+"/video-input")});
  const {data:messages}=useQuery({queryKey:["messages",pid],queryFn:()=>api<{items:Message[]}>("/projects/"+pid+"/messages")});
  const [selected,setSelected]=useState<string>();
  const [sending,setSending]=useState(false);
  const [error,setError]=useState(()=>sessionStorage.getItem("atoms:startup-error:"+pid)||"");
  useEffect(()=>{sessionStorage.removeItem("atoms:startup-error:"+pid)},[pid]);
  const vid=selected||project?.current_version_id;
  const {data:version}=useQuery({queryKey:["version",pid,vid],queryFn:()=>api<Version>("/projects/"+pid+"/versions/"+vid),enabled:!!vid});
  const refresh=async()=>{await Promise.all([client.invalidateQueries({queryKey:["project",pid]}),client.invalidateQueries({queryKey:["projects"]}),client.invalidateQueries({queryKey:["versions",pid]}),client.invalidateQueries({queryKey:["messages",pid]}),client.invalidateQueries({queryKey:["video-input",pid]}),client.invalidateQueries({queryKey:["wallet"]}),client.invalidateQueries({queryKey:["credit-transactions"]})])};
  useEffect(()=>{void refresh()},[project?.active_run_id,project?.current_version_id]);
  const lastAssistant=messages?.items.filter(message=>message.role==="assistant").at(-1);
  const failure=lastAssistant&&["failed","interrupted"].includes(lastAssistant.run_status||"")?lastAssistant:undefined;
  async function submit(value:VideoDraft,retryOf?:string) {
    if(!project||busy||sending)return;
    setSending(true);setError("");
    try{
      const image=value.dataUrl?await api<{id:string}>(`/projects/${pid}/media/images`,"POST",{data_url:value.dataUrl}):undefined;
      const body={prompt:value.prompt,expected_revision:project.revision,base_version_id:project.current_version_id,
        ...(retryOf?{retry_of_run_id:retryOf}:{video:{image_asset_id:image?.id||value.imageAssetId,duration:value.duration,audio:value.audio}})};
      const pendingKey="atoms:pending:"+pid;
      let pending:{id:string;body:typeof body}|undefined;
      try{pending=JSON.parse(sessionStorage.getItem(pendingKey)||"null")}catch{}
      if(!pending||JSON.stringify(pending.body)!==JSON.stringify(body)) pending={id:key(),body};
      sessionStorage.setItem(pendingKey,JSON.stringify(pending));
      try{
        await api(`/projects/${pid}/runs`,"POST",pending.body,{"Idempotency-Key":pending.id});
        sessionStorage.removeItem(pendingKey);
      }catch(error){if(error instanceof ApiError&&error.status<500)sessionStorage.removeItem(pendingKey);throw error}
      setSelected(undefined);await refresh();
    }catch(err){setError((err as Error).message);await refresh()}finally{setSending(false)}
  }
  const media=version?.artifact?.media;
  return <div className="studio-content video-workspace">
    <header className="video-workspace-heading"><div><Link to="/video"><ArrowLeft size={15}/>返回视频创作</Link><h1>{project?.title||"视频项目"}</h1></div>
      {vid&&<a className="export-button" href={`/api/v1/projects/${pid}/versions/${vid}/export`}><Download size={16}/>{media?"下载视频":"导出分镜"}</a>}
    </header>
    <div className="video-workspace-grid">
      <div><VideoForm pid={pid} initial={input} prompt={sessionStorage.getItem("atoms:draft:"+pid)||""} resolution={cap?.video_resolution} busy={busy||sending} unavailableReason={unavailable(cap)} error={error} onSubmit={submit}/>
        {!busy&&failure&&<div className="video-failure" role="alert"><p>{failure.content}</p>
          {failure.run_error_code!=="VIDU_SUBMISSION_UNCERTAIN"&&<button type="button" className="plain-button" disabled={sending||!cap?.video_configured} onClick={()=>{
            const request=messages?.items.find(message=>message.run_id===failure.run_id&&message.role==="user")?.content||"";
            void submit({prompt:request,dataUrl:"",imageAssetId:input?.image_asset_id||undefined,duration:input?.duration||5,audio:!!input?.audio},failure.run_id);
          }}>继续任务</button>}
        </div>}
      </div>
      <section className="video-output" aria-label="视频结果">
        {busy&&<div className="video-progress" role="status"><LoaderCircle size={17} className="spin"/>建设中<small>可以刷新或离开页面，任务会继续。</small></div>}
        {media?<><video key={media.asset_id} controls playsInline preload="metadata" poster={media.image_asset_id?mediaUrl(pid,media.image_asset_id):undefined} src={mediaUrl(pid,media.asset_id)} aria-label="生成的视频"/>
          <p className="video-result-meta">{media.resolution} · {media.duration} 秒 · {media.audio?"带声音":"无声"} · {media.model==="viduq3-pro"?"Vidu Q3 Pro":media.model}</p></>
          :version?.artifact?<div className="video-legacy-preview"><Preview pid={pid} vid={version.id} reload={0} phone={false} onSaved={()=>{}}/></div>
          :<div className="video-empty"><Play size={36}/><h2>{busy?"视频正在成形":"你的视频将出现在这里"}</h2><p>描述场景、动作与镜头，或添加一张参考图片。</p></div>}
        {!!versions?.items.length&&<div className="video-versions" aria-label="视频版本">
          <h3>历史版本</h3>{versions.items.map(item=><button type="button" key={item.id} aria-pressed={vid===item.id} onClick={()=>setSelected(item.id)}><span>v{item.number}</span>{item.summary}</button>)}
          {selected&&selected!==project?.current_version_id&&<button type="button" disabled={busy||!!cap?.read_only} onClick={async()=>{
            try{await api(`/projects/${pid}/versions/${selected}/restore`,"POST",{expected_revision:project?.revision});setSelected(undefined);await refresh()}catch(err){setError((err as Error).message)}
          }}>设为当前版本</button>}
        </div>}
      </section>
    </div>
  </div>;
}
