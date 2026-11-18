import {lazy,Suspense,useCallback,useEffect,useRef,useState,type FormEvent,type ReactNode} from "react";
import {Link,NavLink,Route,Routes,useParams} from "react-router-dom";
import Modal from "./Modal";
import WalletButton,{openWalletDialog,useWallet} from "./Wallet";
import {useQuery,useQueryClient} from "@tanstack/react-query";
import {ArrowUp,Plus,Layers3,PanelLeftClose,PanelLeftOpen,Settings2,ChevronDown,Check,CheckCircle2,Code2,Eye,Download,History,Monitor,Smartphone,RotateCcw,X,Sparkles,LayoutGrid,ArrowLeft,LoaderCircle,AlertCircle,Braces,House,Menu,ChevronRight,Save,Square} from "lucide-react";
import {api,active,ApiError,date,key,type Message,type Project,type ProjectKind,type Run,type RunSource,type Version} from "./api";
import {creationKinds,modes} from "./creationModes";
import {StudioLanding,StudioHeader,ProjectLibrary,useProjects,useCapabilities} from "./Studio";
import Preview from "./Preview";
import PublishedPage,{PublishButton} from "./Publication";
import BuildFailure from "./BuildFailure";
import SlideTemplateDetail from "./SlideTemplateDetail";
import {VideoStudio,VideoWorkspace} from "./VideoStudio";
import RunProgress,{useRunProgress} from "./RunProgress";
import InspectorDrawer from "./InspectorPanel";
import "./run-workspace.css";

function Brand({compact=false}:{compact?:boolean}){
  return <Link to="/" className={"brand "+(compact?"compact":"")} aria-label="Atoms Studio 首页"><span className="brand-mark"><Layers3 size={21} strokeWidth={2.2}/></span>{!compact&&<span>atoms<span className="brand-light"> studio</span></span>}</Link>
}
function Settings({onClose}:{onClose:()=>void}){
  const {data}=useCapabilities();
  return <Modal title="工作台说明" onClose={onClose}><p className="muted">从一句需求开始，生成可以真实使用的小型网页应用。</p><div className="setting-row"><span>模型</span><strong>{data?.model||"尚未设置"}</strong></div><div className="setting-row"><span>模型服务</span><span className={data?.model_configured?"positive":"warning"}>{data?.model_configured?"已配置":"待配置"}</span></div><div className="setting-row"><span>生成服务</span><span>{data?.worker_available?"运行中":"正在连接"}</span></div><div className="setting-row"><span>视频模型</span><strong>{data?.video_model||"viduq3-pro"} · {data?.video_resolution||"540p"}</strong></div><div className="setting-row"><span>视频服务</span><span>{data?.video_configured?"已配置":"待配置"}</span></div><div className="explain"><h3>支持什么</h3><p>任务看板、表单、计算器、筛选列表和简单数据看板。应用数据按项目保存，代码可以查看、恢复版本和导出。</p><h3>使用边界</h3><p>新网站和游戏使用 React 与 TypeScript。游戏交付包含玩法设计、规则模块和可操作的预览。汇率项目可在构建时引入有日期的公开参考数据。首次赠送 500 积分，输入每百万 token 20 积分、输出每百万 token 80 积分，按实际用量结算。</p><p>当前使用匿名访客会话。请使用同一浏览器重新打开；清除 Cookie 后无法找回原项目。</p></div>{!data?.model_configured&&<div className="configuration-note">本地操作者：在 .env.local 配置 LLM_BASE_URL、LLM_MODEL 和 LLM_API_KEY 后重建 Worker。密钥不会进入前端。</div>}{!data?.video_configured&&<div className="configuration-note">视频服务：在 .env.local 填写 VIDU_API_KEY，默认模型 viduq3-pro、分辨率 540p，然后重建 API 和 Worker。</div>}</Modal>
}
function Sidebar({collapsed,toggle,mobileOpen=false,closeMobile}:{collapsed:boolean;toggle:()=>void;mobileOpen?:boolean;closeMobile?:()=>void}){
  const {data}=useProjects(),{pid}=useParams();
  const [settings,setSettings]=useState(false);
  useEffect(()=>{
    if(!mobileOpen || !closeMobile) return;
    const escape=(event:KeyboardEvent)=>{if(event.key==="Escape")closeMobile()};
    window.addEventListener("keydown",escape);
    return ()=>window.removeEventListener("keydown",escape);
  },[mobileOpen,closeMobile]);
  const compact=collapsed&&!mobileOpen;
  return <>
    {mobileOpen&&<button className="studio-menu-scrim" aria-label="关闭菜单" onClick={closeMobile}/>}
    <aside className={"sidebar studio-sidebar "+(compact?"collapsed ":"")+(mobileOpen?"studio-drawer":"")}>
      <div className="sidebar-top">
        <Brand compact={compact}/>
        <button className="icon-button sidebar-toggle" onClick={mobileOpen?closeMobile:toggle} aria-label={mobileOpen?"收起菜单":compact?"展开侧栏":"收起侧栏"}>
          {mobileOpen?<X size={18}/>:compact?<PanelLeftOpen size={17}/>:<PanelLeftClose size={17}/>}
        </button>
      </div>
      <Link className="new-project" to="/" onClick={closeMobile} aria-label="新建应用"><Plus size={19}/>{!compact&&"新建创作"}</Link>
      <nav className="studio-nav" aria-label="主导航">
        {creationKinds.map(kind=>{
          const mode=modes[kind], Icon=kind==="web"?House:mode.icon;
          return <NavLink key={kind} end={kind!=="slides"} className="nav-item" aria-label={mode.nav} title={compact?mode.nav:undefined} to={mode.path} onClick={closeMobile}><Icon size={19}/>{!compact&&mode.nav}</NavLink>;
        })}
        <NavLink className="nav-item nav-projects" end to="/projects" onClick={closeMobile} aria-label="项目" title={compact?"项目":undefined}><LayoutGrid size={19}/>{!compact&&"项目"}</NavLink>
      </nav>
      {!compact&&<><div className="nav-heading projects-heading">最近项目</div><div className="recent-projects">
        {data?.items.slice(0,6).map(project=>{
          const Icon=modes[project.kind||"web"].icon;
          return <Link key={project.id} onClick={closeMobile} to={"/projects/"+project.id} className={"recent-project "+(project.id===pid?"active":"")}><Icon size={15}/><span>{project.title}</span>{project.active_run_id&&<LoaderCircle className="spin" size={12}/>}</Link>;
        })}
        {data?.items.length===0&&<p className="sidebar-empty">暂无项目</p>}
      </div></>}
      <div className="sidebar-bottom"><WalletButton compact={compact}/><button className="profile" onClick={()=>setSettings(true)} title="工作台说明"><span className="avatar">访</span>{!compact&&<><span><strong>访客工作空间</strong></span><Settings2 size={16}/></>}</button></div>
      {settings&&<Settings onClose={()=>setSettings(false)}/>}
    </aside>
  </>;
}
function StudioRoute({kind,children}:{kind?:ProjectKind;children?:ReactNode}){
  const [collapsed,setCollapsed]=useState(false);
  const [menuOpen,setMenuOpen]=useState(false);
  return <div className="app-layout studio-layout">
    <Sidebar collapsed={collapsed} toggle={()=>setCollapsed(value=>!value)} mobileOpen={menuOpen} closeMobile={()=>setMenuOpen(false)}/>
    <main className="studio-main">
      <StudioHeader label={kind ? modes[kind].nav : "项目"} onMenu={()=>setMenuOpen(true)} actions={<WalletButton compact/>}/>
      {children ?? (kind==="video"?<VideoStudio/>:kind ? <StudioLanding key={kind} kind={kind}/> : <div className="studio-content project-library-page"><ProjectLibrary/></div>)}
    </main>
  </div>;
}

const Code=lazy(()=>import("./Code"));
const emptyEdits: Record<string,string> = {};

function Workspace(){
  const {pid=""}=useParams(),client=useQueryClient();
  const [menuOpen,setMenuOpen]=useState(false);
  const [collapsed,setCollapsed]=useState(true),[prompt,setPrompt]=useState(()=>sessionStorage.getItem("atoms:draft:"+pid)||""),[error,setError]=useState(()=>sessionStorage.getItem("atoms:startup-error:"+pid)||""),[sending,setSending]=useState(false);
  const [tab,setTab]=useState<"preview"|"code"|null>(null),[selected,setSelected]=useState<string|null>(null),[phone,setPhone]=useState(false),[reload,setReload]=useState(0),[saved,setSaved]=useState("已保存"),[history,setHistory]=useState(false),[restore,setRestore]=useState<Version>(),[restoring,setRestoring]=useState(false),[mobileView,setMobileView]=useState("preview");
  const [edits,setEdits]=useState<Record<string,Record<string,string>>>({});
  const [sourceError,setSourceError]=useState<{vid:string;message:string}>();
  const [savedSource,setSavedSource]=useState<{number:number;changed:boolean}>();
  const [savingSource,setSavingSource]=useState(false);
  const [selectedDraft,setSelectedDraft]=useState<string|null>(null);
  const [stopping,setStopping]=useState(false);
  const sourceRequest=useRef<{body:string;key:string}>(null);
  const bottom=useRef<HTMLDivElement>(null);
  const stickToBottom=useRef(true);
  const {data:project,error:projectError}=useQuery({queryKey:["project",pid],queryFn:()=>api<Project>("/projects/"+pid)});
  const {data:messages}=useQuery({queryKey:["messages",pid],queryFn:()=>api<{items:Message[]}>("/projects/"+pid+"/messages")});
  const {data:versions}=useQuery({queryKey:["versions",pid],queryFn:()=>api<{items:Version[]}>("/projects/"+pid+"/versions")});
  const {data:cap}=useCapabilities();
  const {data:wallet}=useWallet();
  const busy=!!project?.active_run_id;
  const runId=project?.active_run_id??messages?.items.at(-1)?.run_id;
  const {data:run}=useQuery({queryKey:["run",runId],queryFn:()=>api<Run>("/runs/"+runId),enabled:!!runId,refetchInterval:busy?3000:false});
  const vid=selected||project?.current_version_id;
  const {data:version,isPending:versionPending}=useQuery({queryKey:["version",pid,vid],queryFn:()=>api<Version>("/projects/"+pid+"/versions/"+vid),enabled:!!vid});
  const historical=!!vid&&vid!==project?.current_version_id;
  const pendingAcceptance=!busy&&run?.status==="failed"&&
    ["ACCEPTANCE_FAILED","ACCEPTANCE_UNCONFIRMED"].includes(run.error_code??"");
  const userStopped=run?.status==="interrupted"&&run.error_code==="USER_STOPPED";
  const retainedPreview=!busy&&(pendingAcceptance||userStopped)&&!!run?.workspace?.has_preview;
  const showRetainedDraft=retainedPreview&&(!vid||selectedDraft===runId);
  const showRunSource=!historical&&!!run?.workspace?.source_revision&&(busy||!vid||showRetainedDraft);
  const {data:runSource}=useQuery({
    queryKey:["run-source",runId,run?.workspace?.source_revision],
    queryFn:()=>api<RunSource>("/runs/"+runId+"/source"),enabled:showRunSource,
    placeholderData:previous=>previous,retry:false,
  });
  const source=showRunSource?runSource:undefined;
  const draftPreview=!historical&&(showRetainedDraft||busy&&active(run))&&!!run?.workspace?.has_preview;
  const files=source?.files??version?.artifact?.files;
  const canPreview=draftPreview||!!version?.artifact;
  const displayTab=files&&(tab==="code"||!canPreview)?"code":"preview";
  const showingDraft=displayTab==="code"?!!source:draftPreview;
  const editableSource=!!version?.artifact&&["1","2"].includes(version.artifact.schema_version)
    &&!source&&!historical&&!busy&&!cap?.read_only;
  const currentEdits=vid&&!source?edits[vid]??emptyEdits:emptyEdits;
  const hasEdits=Object.keys(currentEdits).length>0;
  const saveError=sourceError&&sourceError.vid===vid?sourceError.message:undefined;
  const switchTab=(next:"preview"|"code")=>{setTab(next);setMobileView("preview")};
  const versionsByRun=new Map(versions?.items.map(item=>[item.source_run_id,item]));
  const recoveredRuns=new Set<string>();
  for (const message of (messages?.items??[]).slice().reverse()) {
    if (message.role==="assistant" && message.retry_of_run_id &&
        (message.run_status==="succeeded" || recoveredRuns.has(message.run_id))) {
      recoveredRuns.add(message.retry_of_run_id);
    }
  }
  function showVersion(id:string){
    setSelectedDraft(null);
    setSelected(id===project?.current_version_id?null:id);
    setTab("preview");
    setMobileView("preview");
  }
  const refresh=useCallback(async()=>{
    await Promise.all([client.invalidateQueries({queryKey:["project",pid]}),client.invalidateQueries({queryKey:["projects"]}),client.invalidateQueries({queryKey:["messages",pid]}),client.invalidateQueries({queryKey:["versions",pid]}),client.invalidateQueries({queryKey:["wallet"]}),client.invalidateQueries({queryKey:["credit-transactions"]})]);
  },[client,pid]);
  const progressUpdate=useCallback((kind:string)=>{
    if(client.getQueryData<Project>(["project",pid])?.active_run_id!==runId)return;
    if(["completed","failed","interrupted","source_ready","preview_ready"].includes(kind)){
      void client.invalidateQueries({queryKey:["run",runId]});
    }
    if(["completed","failed","interrupted"].includes(kind))void refresh();
  },[client,pid,refresh,runId]);
  const progress=useRunProgress(runId,progressUpdate);
  useEffect(()=>{sessionStorage.removeItem("atoms:startup-error:"+pid)},[pid]);
  useEffect(()=>{sessionStorage.setItem("atoms:draft:"+pid,prompt)},[pid,prompt]);
  useEffect(()=>{
    const chat=bottom.current?.parentElement;
    if(!chat)return;
    const onScroll=()=>{stickToBottom.current=chat.scrollHeight-chat.scrollTop-chat.clientHeight<120};
    chat.addEventListener("scroll",onScroll,{passive:true});
    return()=>chat.removeEventListener("scroll",onScroll);
  },[]);
  useEffect(()=>{
    if(!stickToBottom.current)return;
    const chat=bottom.current?.parentElement;
    chat?.scrollTo({top:chat.scrollHeight});
  },[messages,busy,progress?.events.length]);
  useEffect(()=>{
    if(!hasEdits)return;
    const onBeforeUnload=(event:BeforeUnloadEvent)=>{event.preventDefault()};
    window.addEventListener("beforeunload",onBeforeUnload);
    return()=>window.removeEventListener("beforeunload",onBeforeUnload);
  },[hasEdits]);
  useEffect(()=>{
    if(busy&&run&&!active(run))void refresh();
  },[busy,run?.status,refresh]);
  function editSource(path:string,value:string){
    if(!vid||!files||!editableSource||savingSource)return;
    setEdits(previous=>{
      const next={...previous[vid]};
      if(value===files[path])delete next[path];
      else next[path]=value;
      return {...previous,[vid]:next};
    });
    setSourceError(undefined);
    setSavedSource(undefined);
  }
  async function saveSource(){
    if(!project||!vid||!editableSource||!hasEdits||savingSource||sending||restoring)return;
    const payload={expected_revision:project.revision,files:currentEdits};
    const body=JSON.stringify([vid,payload]);
    if(sourceRequest.current?.body!==body)sourceRequest.current={body,key:key()};
    setSavingSource(true);
    setSourceError(undefined);
    setSavedSource(undefined);
    try{
      const {project:updatedProject,...result}=await api<Version & {project:Project}>(
        "/projects/"+pid+"/versions/"+vid+"/source","POST",payload,{"Idempotency-Key":sourceRequest.current.key});
      const projectKey=["project",pid];
      await client.cancelQueries({queryKey:projectKey,exact:true});
      client.setQueryData(["version",pid,result.id],result);
      client.setQueryData<Project>(projectKey,current=>
        current&&(current.revision>updatedProject.revision||
          current.revision===updatedProject.revision&&current.updated_at>updatedProject.updated_at)
          ? current : updatedProject);
      setSelected(null);
      setHistory(false);
      switchTab("preview");
      sourceRequest.current=null;
      setEdits(previous=>{
        const next={...previous};
        delete next[vid];
        return next;
      });
      setSavedSource({number:result.number,changed:result.id!==vid});
      void Promise.all([
        client.invalidateQueries({queryKey:projectKey,exact:true}),
        client.invalidateQueries({queryKey:["projects"]}),
        client.invalidateQueries({queryKey:["versions",pid]}),
      ]);
    }catch(e){
      setSourceError({vid,message:e instanceof ApiError?e.message:"保存连接中断，请重新保存。草稿已保留。"});
    }finally{
      setSavingSource(false);
    }
  }
  async function submit(e:FormEvent){
    e.preventDefault();
    await sendRun(prompt);
  }
  async function stopRun(){
    const id=project?.active_run_id;
    if(!id||stopping)return;
    setStopping(true);setError("");
    try{
      await api<Run>("/runs/"+id+"/stop","POST",{});
      await Promise.all([refresh(),client.invalidateQueries({queryKey:["run",id]})]);
    }catch(e){setError((e as Error).message)}
    finally{setStopping(false)}
  }
  async function sendRun(request:string,retryOf?:string){
    if(!project||!request.trim()||sending||busy||savingSource)return;
    setSending(true);setError("");
    const storageKey="atoms:pending:"+pid;
    let pending:{id:string;body:{prompt:string;expected_revision:number;base_version_id:string|null;retry_of_run_id?:string}}|undefined;
    try{pending=JSON.parse(sessionStorage.getItem(storageKey)||"null")||undefined}catch{}
    const body={prompt:request.trim(),expected_revision:project.revision,base_version_id:project.current_version_id,...(retryOf?{retry_of_run_id:retryOf}:{})};
    if(!pending||pending.body?.prompt!==body.prompt||pending.body?.retry_of_run_id!==retryOf)pending={id:key(),body};
    sessionStorage.setItem(storageKey,JSON.stringify(pending));
    try{
      stickToBottom.current=true;
      await api<Run>("/projects/"+pid+"/runs","POST",pending.body,{"Idempotency-Key":pending.id});
      sessionStorage.removeItem(storageKey);if(!retryOf)setPrompt("");await refresh();
    }catch(e){
      setError((e as Error).message);
      if(e instanceof ApiError&&e.status<500)sessionStorage.removeItem(storageKey);
      if(e instanceof ApiError&&e.status===409)await refresh();
    }finally{setSending(false)}
  }
  async function doRestore(){
    if(!project||!restore||savingSource)return;setRestoring(true);setError("");
    try{await api("/projects/"+pid+"/versions/"+restore.id+"/restore","POST",{expected_revision:project.revision});setSelected(null);setRestore(undefined);setHistory(false);await refresh();setReload(n=>n+1)}
    catch(e){setError((e as Error).message)}finally{setRestoring(false)}
  }
  if(projectError)return <div className="fatal"><AlertCircle/><h2>无法打开项目</h2><p>{projectError.message}</p><Link to="/">返回工作空间</Link></div>;
  const projectMode=modes[project?.kind||"web"];
  const ProjectIcon=projectMode.icon;
  return <div className="app-layout workspace-layout">
    <Sidebar collapsed={collapsed} toggle={()=>setCollapsed(value=>!value)} mobileOpen={menuOpen} closeMobile={()=>setMenuOpen(false)}/>
    <main className="workspace">
    <header className="workspace-header">
      <div className="project-heading">
        <button type="button" className="icon-button studio-mobile-menu" aria-label="打开菜单" onClick={()=>setMenuOpen(true)}><Menu size={19}/></button>
        <Link to="/projects" aria-label="返回项目" className="icon-button workspace-back"><ArrowLeft size={17}/></Link>
        <span className={"project-heading-icon kind-"+(project?.kind||"web")}><ProjectIcon size={16}/></span>
        <strong>{project?.title||"加载项目…"}</strong>
        {project&&<span className="workspace-kind">{projectMode.output}</span>}
      </div>
      <div className="workspace-actions">
        <span className="wallet-mobile"><WalletButton compact/></span>
        <span className="autosave"><CheckCircle2 size={14}/>项目已保存</span>
        <button aria-label="版本记录" className={"plain-button "+(history?"pressed":"")} onClick={()=>setHistory(!history)}><History size={16}/><span>版本记录</span></button>
        {vid&&!showRetainedDraft&&<a className="export-button" href={"/api/v1/projects/"+pid+"/versions/"+vid+"/export"}><Download size={15}/><span>导出源码</span></a>}
        {vid&&!showRetainedDraft&&(project?.kind==="web"||project?.kind==="game")&&<PublishButton pid={pid} versionId={vid} versionNumber={version?.number} readOnly={cap?.read_only}/>}
      </div>
    </header>
    <div className="mobile-work-tabs"><button className={mobileView==="chat"?"selected":""} onClick={()=>setMobileView("chat")}>对话</button><button className={mobileView==="preview"?"selected":""} onClick={()=>setMobileView("preview")}>应用</button></div>
    <div className={"workspace-body mobile-"+mobileView}>
      <section className="chat-panel"><div className="chat-heading"><span><span className="agent-mark"><Sparkles size={14}/></span>构建助手</span><small>CODE AGENT</small></div><div className="chat-scroll"><div className="welcome-message"><span className="welcome-icon"><Sparkles size={18}/></span><h3>一起把想法做出来</h3><p>告诉我你想创建的应用。我会生成代码、检查预览，并把每次成功的修改保存成版本。</p><span className="supported-note"><Check size={12}/>支持交互与项目数据保存</span></div>
      {messages?.items.map(message=>{
        const assistant=message.role==="assistant";
        const result=assistant&&message.run_status==="succeeded"?versionsByRun.get(message.run_id):undefined;
        const failed=assistant&&["failed","interrupted"].includes(message.run_status||"");
        const originalPrompt=()=>message.run_prompt||messages.items.find(item=>item.role==="user"&&item.run_id===message.run_id)?.content||"";
        return <article key={message.id} className={"message "+message.role}>
          <div className="message-label">{assistant?<><Sparkles size={13}/>构建助手</>:<><span className="small-avatar">你</span>{message.retry_of_run_id?"继续构建":"你的需求"}</>}<time>{date(message.created_at)}</time></div>
          {failed && recoveredRuns.has(message.run_id) ? <div className="message-content">{message.run_error_code==="USER_STOPPED"?"这次构建已继续并完成。":"这次构建已修复。"}</div>
          : failed ? <BuildFailure message={message} hasVersion={!!project?.current_version_id}
            stale={(message.run_base_version_id??null)!==(project?.current_version_id??null)}
            disabled={busy||savingSource||!!cap?.read_only||!cap?.model_configured||!cap?.worker_available||(!message.has_candidate&&(wallet?.available_units??0)<100)}
            sending={sending} onRetry={()=>void sendRun(originalPrompt(),message.run_id)}
            onPreview={retainedPreview&&runId===message.run_id?()=>{setSelected(null);setSelectedDraft(runId);switchTab("preview")}:undefined}
            onEdit={()=>{setPrompt(originalPrompt());document.getElementById("chat-prompt")?.focus()}}/>
          : <div className="message-content">{message.content}</div>}
          {result && <div className="version-result-wrap">
            <div className="version-result-card">
              <span>版本 v{result.number} 已生成</span>
              <button type="button" aria-label={"查看版本 v"+result.number+" 预览"} onClick={()=>{setHistory(false);showVersion(result.id)}}><Eye size={14}/>查看预览</button>
            </div>
            <InspectorDrawer runId={result.source_run_id} label={"v"+result.number+" 工程透视"} variant="inline"/>
          </div>}
        </article>;
      })}
      <RunProgress runId={runId} events={progress?.events??[]} stage={run?.stage} eventSeq={run?.event_seq} connection={progress?.connection} busy={busy}
        onCode={source?()=>switchTab("code"):undefined}
        onPreview={draftPreview?()=>switchTab("preview"):undefined}/>
      <div ref={bottom}/></div>
      <div className="chat-compose-area">{wallet&&wallet.available_units<100&&<div className="capability-warning">可用积分不足；已有预览、版本和导出仍可使用。</div>}{cap?.guardrails?.daily_budget_reached&&<div className="capability-warning"><span>今日公共体验额度已达上限；当前项目预览、源码编辑和导出仍正常可用。</span><button type="button" className="plain-button" onClick={openWalletDialog}>输入体验码</button></div>}{!cap?.model_configured&&<div className="capability-warning"><AlertCircle size={15}/><span>模型待配置，连接后即可生成应用。</span></div>}{cap?.read_only&&<div className="capability-warning">系统维护中，当前只读。</div>}{error&&<div className="inline-error" role="alert">{error}<button aria-label="关闭错误" onClick={()=>setError("")}><X size={13}/></button></div>}
      <form className="chat-composer" onSubmit={submit}>
        <label className="sr-only" htmlFor="chat-prompt">描述需求或修改</label>
        <textarea id="chat-prompt" placeholder={project?.current_version_id?"描述下一步修改…":"详细描述你想创建的应用…"} maxLength={100000} value={prompt} onChange={e=>setPrompt(e.target.value)} onKeyDown={e=>{if(e.key==="Enter"&&(e.ctrlKey||e.metaKey)){e.preventDefault();e.currentTarget.form?.requestSubmit()}}}/>
        <div>
          <span>{busy?(stopping?"正在停止构建…":"构建期间可以离开此页面"):project?.current_version_id?"基于当前版本继续构建":"准备好，就开始吧"}{!busy&&prompt.length>0&&<span className="prompt-length">{prompt.length} / 100000 字</span>}</span>
          {busy?<button type="button" className="stop-build-button" aria-label="停止构建" title="停止当前项目的构建" disabled={stopping} onClick={()=>void stopRun()}>
            {stopping?<LoaderCircle size={16} className="spin" aria-hidden="true"/>:<Square size={12} fill="currentColor" aria-hidden="true"/>}
          </button>:<button type="submit" aria-label="提交需求" disabled={!prompt.trim()||sending||savingSource||(wallet?.available_units??0)<100||!cap?.model_configured||!cap?.worker_available||cap?.read_only}>
            {sending?<LoaderCircle size={16} className="spin"/>:<ArrowUp size={18}/>}
          </button>}
        </div>
      </form><p className="chat-footnote">Ctrl / ⌘ + Enter 发送 · AI 生成结果请实际验证</p></div></section>
      <section className="build-panel" onKeyDown={event=>{
        if(displayTab==="code"&&(event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="s"){
          event.preventDefault();
          void saveSource();
        }
      }}><div className="preview-toolbar">
        <div className="view-tabs">
          <button className={displayTab==="preview"?"selected":""} aria-pressed={displayTab==="preview"} disabled={!canPreview} onClick={()=>switchTab("preview")}><Eye size={15}/>预览</button>
          <button className={displayTab==="code"?"selected":""} aria-pressed={displayTab==="code"} disabled={!files} onClick={()=>switchTab("code")}><Code2 size={15}/>代码</button>
        </div>
        <div className="preview-controls">
          {showingDraft?<span className="draft-indicator">本次构建</span>:version&&<button className="version-chip" onClick={()=>setHistory(!history)}>v{version.number}<ChevronDown size={12}/></button>}
          {showRetainedDraft&&vid&&<button className="version-chip" onClick={()=>showVersion(vid)}>回到当前版本</button>}
          <span className="toolbar-divider"/>
          <button className={"icon-button "+(!phone?"selected":"")} title="桌面预览" aria-label="桌面预览" disabled={!canPreview||displayTab==="code"} onClick={()=>setPhone(false)}><Monitor size={16}/></button>
          <button className={"icon-button "+(phone?"selected":"")} title="手机预览" aria-label="手机预览" disabled={!canPreview||displayTab==="code"} onClick={()=>setPhone(true)}><Smartphone size={16}/></button>
          <span className="toolbar-divider"/>
          <button className="icon-button" aria-label="重新加载预览" disabled={!canPreview||displayTab==="code"} onClick={()=>setReload(n=>n+1)}><RotateCcw size={15}/></button>
        </div>
      </div>
      {historical&&<div className="history-banner"><History size={14}/><span>正在查看历史 v{version?.number}，业务数据只读</span><button onClick={()=>setSelected(null)}>回到当前</button><button disabled={busy||savingSource||cap?.read_only} onClick={()=>version&&setRestore(version)}>恢复此版本</button></div>}
      {!showingDraft&&version?.source_run_id&&<InspectorDrawer runId={version.source_run_id} label={"版本 v"+version.number+" · 工程透视"} variant="panel"/>}
      {displayTab==="code"&&files&&!source&&(editableSource||hasEdits)&&<div className="source-tools">
        <div className="source-toolbar">
          <span role="status">{savingSource?"正在校验并打包…":hasEdits?"有未保存的修改":"编辑后可保存为新版本"}</span>
          <button type="button" disabled={!editableSource||!hasEdits||savingSource||sending||restoring} onClick={()=>void saveSource()}>
            {savingSource?<LoaderCircle size={15} className="spin"/>:<Save size={15}/>}保存源码
          </button>
        </div>
        {saveError&&<div className="source-diagnostic" role="alert">
          <strong>保存失败，修改已保留</strong><pre>{saveError}</pre>
        </div>}
      </div>}
      {savedSource&&<div className="source-saved-notice">
        <div role="status"><CheckCircle2 size={16} aria-hidden="true"/>
          {savedSource.changed?"源码已保存为 v"+savedSource.number:"源码已是最新，无需创建版本"}
        </div>
        <button type="button" className="icon-button" aria-label="关闭保存提示" onClick={()=>setSavedSource(undefined)}><X size={15}/></button>
      </div>}
      <div className="build-content">
        {displayTab==="code"&&files?<Suspense fallback={<div className="preview-loading">正在加载代码编辑器…</div>}>
          <Code files={files} edits={currentEdits} editable={editableSource&&!savingSource} onEdit={editSource}/>
        </Suspense>
          :draftPreview&&runId?<Preview key={runId+":"+(run?.workspace?.preview_digest??"")} pid={pid} runId={runId} reload={reload} phone={phone} onSaved={setSaved}/>
          :vid&&version?.artifact?<Preview key={vid} pid={pid} vid={vid} reload={reload} phone={phone} onSaved={setSaved}/>
          :<div className="workspace-empty">
            {busy||vid&&versionPending?<LoaderCircle className="spin" size={22}/>:<Code2 size={23}/>}
            <h2>{vid&&versionPending?"正在载入版本":busy?"正在等待源码":run&&!active(run)?"暂无可用预览":"等待首次生成"}</h2>
            <p>{vid&&versionPending?null:busy?"源码就绪后会先显示代码，应用通过运行检查后可预览。":run&&!active(run)?"可在对话中查看构建结果。":"提交需求后，代码和预览会显示在这里。"}</p>
            {busy&&<button className="empty-open-chat" type="button" onClick={()=>setMobileView("chat")}>查看构建进度</button>}
          </div>}
      </div>
      <div className="preview-statusbar">
        <span><span className={"status-dot "+(saved==="未保存"&&!showingDraft?"red":"")}/>
          {showingDraft?(displayTab==="code"?(busy?"构建源码 · 只读":"未发布源码 · 只读"):showRetainedDraft?(userStopped?"临时预览 · 已停止 · 操作不保存":"临时预览 · 待通过验收 · 操作不保存"):"临时预览 · 操作不保存")
            :historical?"历史版本 · 只读":displayTab==="code"?(editableSource?"当前版本源码":"版本源码 · 只读"):canPreview?saved:busy?"正在构建":"暂无预览"}</span>
        {(source||version?.artifact)&&<span>{!showingDraft&&version?"v"+version.number+" · ":""}{(source?.schema_version??version?.artifact?.schema_version)==="2"?"React / TypeScript":"HTML / CSS / JavaScript"}</span>}
      </div>
      {history&&<aside className="history-panel"><div><h3>版本记录</h3><button className="icon-button" aria-label="关闭版本记录" onClick={()=>setHistory(false)}><X size={17}/></button></div><p>构建和源码修改通过校验后会保存为新版本。</p>{versions?.items.length===0&&<div className="history-empty">还没有可用版本</div>}{versions?.items.map(v=><button key={v.id} className={"history-item "+(v.id===vid?"selected":"")} onClick={()=>showVersion(v.id)}><span><strong>版本 {v.number}</strong>{v.id===project?.current_version_id?<small>当前版本</small>:<ChevronRight size={14}/>}</span><p>{v.summary}</p><time>{date(v.created_at)}</time></button>)}</aside>}
      </section>
    </div>
    {restore&&<Modal title={"恢复到版本 "+restore.number} onClose={()=>setRestore(undefined)}><p>当前代码将切换到这个版本，所有历史版本继续保留。</p><p className="muted">业务数据保持现状，不随代码回滚。恢复后再修改，会基于这个版本创建新的版本。</p><div className="modal-actions"><button className="plain-button" onClick={()=>setRestore(undefined)}>取消</button><button className="create-button" disabled={restoring} onClick={doRestore}>{restoring?<LoaderCircle className="spin" size={16}/>:"确认恢复"}</button></div></Modal>}
  </main></div>
}
function WorkspaceRoute(){
  const {pid=""}=useParams();
  const {data:project,isLoading,error}=useQuery({queryKey:["project",pid],queryFn:()=>api<Project>("/projects/"+pid)});
  if(error)return <div className="fatal"><AlertCircle/><h2>无法打开项目</h2><p>{error.message}</p><Link to="/">返回工作空间</Link></div>;
  if(isLoading)return <div className="fatal" role="status">正在打开项目…</div>;
  return project?.kind==="video"?<StudioRoute kind="video"><VideoWorkspace key={pid} pid={pid}/></StudioRoute>:<Workspace key={pid}/>;
}
export default function App(){
  return <Routes>
    <Route path="/p/:slug" element={<PublishedPage/>}/>
    {creationKinds.map(kind=><Route key={kind} path={modes[kind].path} element={<StudioRoute kind={kind}/>}/>)}
    <Route path="/slides/templates/:templateId" element={<StudioRoute kind="slides"><SlideTemplateDetail/></StudioRoute>}/>
    <Route path="/projects" element={<StudioRoute/>}/>
    <Route path="/projects/:pid" element={<WorkspaceRoute/>}/>
    <Route path="*" element={<div className="fatal"><h1>页面不存在</h1><Link to="/">回到工作空间</Link></div>}/>
  </Routes>;
}
