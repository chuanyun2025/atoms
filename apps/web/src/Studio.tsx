import {useEffect,useRef,useState,type FormEvent,type ReactNode} from "react";
import {Link} from "react-router-dom";
import {useQuery} from "@tanstack/react-query";
import {ArrowRight,ArrowUp,ArrowUpRight,FolderOpen,LoaderCircle,Menu,Search,Sparkles} from "lucide-react";
import {api,date,type Capabilities,type Project,type ProjectKind} from "./api";
import {creationKinds,inferProjectKind,modes} from "./creationModes";
import Breakout from "./Breakout";
import Modal from "./Modal";
import {ExampleShowcase} from "./ExamplePreview";
import {openWalletDialog} from "./Wallet";
import StudioGallery,{SlideExampleGallery} from "./StudioGallery";
import type {StudioExample} from "./studioExamples";
import {SlideTemplateGallery} from "./SlideTemplateGallery";
import {useProjectCreation} from "./useProjectCreation";

export function useProjects() {
  return useQuery({
    queryKey:["projects"],
    queryFn:()=>api<{items:Project[]}>("/projects"),
    refetchInterval:query=>query.state.data?.items.some(project=>project.active_run_id)?3000:false,
  });
}
export function useCapabilities() {
  return useQuery({
    queryKey:["capabilities"],
    queryFn:()=>api<Capabilities>("/capabilities"),
    refetchInterval:query=>{
      const data=query.state.data;
      return data?.worker_available&&(data.model_configured||data.video_configured)?60000:10000;
    },
  });
}

export function ProjectLibrary({compact=false}:{compact?:boolean}) {
  const {data,isLoading,error} = useProjects();
  const [query,setQuery] = useState("");
  const [filter,setFilter] = useState<ProjectKind|"all">("all");
  const items = data?.items ?? [];
  const results = items.filter(project =>
    (filter === "all" || (project.kind || "web") === filter) &&
    project.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
  );
  const shown = compact ? results.slice(0,3) : results;
  return <section className={"studio-library"+(compact?" studio-library-compact":"")}>
    <div className="studio-section-heading">
      <div>
        {compact ? <h2>最近项目</h2> : <h1>我的项目</h1>}
        {!compact && <p>搜索、筛选并继续你的创作。</p>}
      </div>
      {compact ? <Link to="/projects" className="studio-section-link">查看全部 <ArrowRight size={15}/></Link> :
        <label className="studio-search"><Search size={16}/><input aria-label="搜索项目" placeholder="搜索项目" value={query} onChange={event=>setQuery(event.target.value)}/></label>}
    </div>
    {!compact && <div className="studio-filters" aria-label="项目类型">
      {(["all",...creationKinds] as const).map(value => <button type="button" key={value} aria-pressed={filter===value} onClick={()=>setFilter(value)}>{value==="all"?"全部":modes[value].label}</button>)}
    </div>}
    {isLoading && <p className="studio-empty" role="status">正在加载项目…</p>}
    {error && <p className="inline-error" role="alert">{error.message}</p>}
    {!isLoading && !error && shown.length === 0 && <div className="studio-empty">
      <FolderOpen size={21}/><div><strong>{items.length ? "没有匹配的项目" : "还没有项目"}</strong><p>{items.length ? "试试其他关键词或类型。" : "新建的项目会保存在这里。"}</p></div>
      {!compact && !items.length && <Link to="/" className="studio-section-link">开始创作 <ArrowRight size={15}/></Link>}
    </div>}
    {shown.length > 0 && <div className="studio-projects">
      {shown.map(project => {
        const kind = project.kind || "web";
        const ModeIcon = modes[kind].icon;
        return <Link to={"/projects/"+project.id} key={project.id} className="studio-project">
          <div className={"project-kind-icon kind-"+kind}><ModeIcon size={21}/></div>
          <div><h3>{project.title}</h3><p>{modes[kind].label} · {project.active_run_id ? "建设中" : project.current_version_id ? "已生成" : "草稿"}</p></div>
          <time>{date(project.updated_at)}</time><ArrowUpRight size={16} className="project-open"/>
        </Link>;
      })}
    </div>}
  </section>;
}

const prompts=["帮我做一个活动网站","帮我做一份网页演示","帮我做一个浏览器小游戏","帮我做一段品牌短视频"];
const websiteIdeas=[
  {label:"城市观察杂志",prompt:"做一个关注城市建筑和街区生活的新闻网站，首屏放头条专题，支持按栏目筛选和收藏文章。"},
  {label:"建筑摄影作品集",prompt:"做一个建筑摄影作品集，突出大图和光影，按公共空间、住宅和街区分类，提供项目详情。"},
  {label:"户外灯具发布页",prompt:"做一个户外露营灯的产品发布页，比较便携款和营地款，展示使用场景和常见问题。"},
];
const draftKeyFor=(kind:ProjectKind)=>"atoms:studio-draft:"+kind;

function useTypingPlaceholder(active:boolean,fallback:string) {
  const [text,setText]=useState("");
  useEffect(()=>{
    if (!active) {
      setText("");
      return;
    }
    const motion=window.matchMedia("(prefers-reduced-motion: reduce)");
    let timer:number|undefined;
    let index=0,length=0;
    function tick() {
      if (document.hidden || motion.matches) return;
      const phrase=prompts[index];
      setText(phrase.slice(0,++length));
      if (length===phrase.length) {
        index=(index+1)%prompts.length;
        length=0;
        timer=window.setTimeout(tick,2200);
      } else timer=window.setTimeout(tick,90);
    }
    function reset() {
      window.clearTimeout(timer);
      if (document.hidden || motion.matches) {
        setText("");
        return;
      }
      index=0;
      length=0;
      tick();
    }
    reset();
    document.addEventListener("visibilitychange",reset);
    motion.addEventListener("change",reset);
    return ()=>{
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange",reset);
      motion.removeEventListener("change",reset);
    };
  },[active]);
  return active && text?text:fallback;
}

export function StudioLanding({kind}:{kind:ProjectKind}) {
  const home=kind==="web";
  const game=kind==="game";
  const mode = modes[kind];
  const ModeIcon = mode.icon;
  const draftKey = draftKeyFor(kind);
  const [prompt,setPrompt] = useState(()=>sessionStorage.getItem(draftKey)||"");
  const [focused,setFocused]=useState(false);
  const [example,setExample]=useState<StudioExample>();
  const [pendingExample,setPendingExample]=useState<string>();
  const input = useRef<HTMLTextAreaElement>(null);
  const {data:cap} = useCapabilities();
  const {create,busy,error} = useProjectCreation(cap);
  const placeholder=useTypingPlaceholder(home && !focused && !prompt && !example && !pendingExample,home?"描述你想创作的作品…":mode.placeholder);

  function changePrompt(value:string) {
    setPrompt(value);
    sessionStorage.setItem(draftKey,value);
  }

  function applyExample(value:string) {
    changePrompt(value);
    setExample(undefined);
    setPendingExample(undefined);
    window.requestAnimationFrame(()=>input.current?.focus());
  }

  function useExample(value:string) {
    if (busy) return;
    setExample(undefined);
    if (prompt.trim() && prompt!==value) {
      setPendingExample(value);
      return;
    }
    applyExample(value);
  }

  function start(event:FormEvent) {
    event.preventDefault();
    void create({kind:home?inferProjectKind(prompt):kind,prompt,draftKey});
  }

  return <div className={"studio-content studio-"+kind+" creative-studio"}>
    <section className={"creative-hero"+(game?" creative-hero-game":"")}>
      <div className="creative-pattern" aria-hidden="true"/>
      {game && <div className="creative-arcade">
        <Breakout collapsed={focused} suspended={!!example||!!pendingExample}/>
      </div>}
      <div className="creative-column">
        {!game && <div className="creative-mark" aria-hidden="true">{home?<Sparkles size={23}/>:<ModeIcon size={24}/>}</div>}
        <h1>{home?"你想创造什么？":modes[kind].title}</h1>
        <p>{home?"从一个想法开始，做一个可以使用的作品。":game?"描述玩法、画风和胜负条件。":mode.description}</p>
        <form className="studio-composer" onSubmit={start}>
          <label className="sr-only" htmlFor="idea">描述应用需求</label>
          <textarea id="idea" ref={input} value={prompt} onChange={event=>changePrompt(event.target.value)}
            onPointerDown={event=>{if(game && event.pointerType==="touch") event.currentTarget.focus({preventScroll:true})}}
            onFocus={()=>setFocused(true)} onBlur={()=>setFocused(false)}
            maxLength={100000} placeholder={placeholder} onKeyDown={event=>{
              if (event.key==="Enter" && !event.nativeEvent.isComposing && (event.ctrlKey || event.metaKey)) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}/>
          <div className="studio-compose-bar">
            {!home && <span className="studio-output"><ModeIcon size={15}/>{mode.output}</span>}
            <button className="studio-submit" type="submit" disabled={!prompt.trim()||busy||cap?.read_only}>
              {busy ? <><LoaderCircle size={16} className="spin"/>正在创建</> : <>开始创建 <ArrowUp size={16}/></>}
            </button>
          </div>
        </form>
        {home && <div className="studio-filters website-idea-shortcuts" aria-label="网站创作示例">
          {websiteIdeas.map(idea => <button key={idea.label} type="button" onClick={()=>useExample(idea.prompt)}>{idea.label}</button>)}
        </div>}
        {cap?.guardrails?.daily_budget_reached && <div className="capability-warning" role="status">
          <span>今日全站公共体验额度已达上限（预计 {cap.guardrails.reset_label} 重置）；仍可浏览体验下方作品，或使用口令继续生成。</span>
          <button type="button" className="plain-button" onClick={openWalletDialog}>输入体验码</button>
        </div>}
        {error && <div className="inline-error" role="alert">{error}</div>}
      </div>
    </section>
    {home || game ? <StudioGallery game={game} onOpen={setExample} projects={<ProjectLibrary compact/>}/> :
      kind==="slides" ? <><SlideExampleGallery onOpen={setExample}/><SlideTemplateGallery/></> :
      <section className="example-gallery" aria-label={mode.label+"示例"}>
        <div className="gallery-heading"><h2>{mode.label}示例</h2></div>
        <div className="example-cover-grid">
          {modes[kind].examples.map(item=><button type="button" key={item.title} className="example-prompt"
            onClick={()=>useExample(item.prompt)}><ModeIcon size={20}/><span><strong>{item.title}</strong><small>{item.description}</small></span><ArrowUpRight size={16}/></button>)}
        </div>
      </section>}
    {example && <Modal wide title={example.title} onClose={()=>setExample(undefined)}>
      <ExampleShowcase example={example} busy={busy} onUsePrompt={useExample}/>
    </Modal>}
    {pendingExample && <Modal title="替换已有草稿？" onClose={()=>setPendingExample(undefined)}>
      <p className="muted">输入框已有一份未提交的需求。你可以保留草稿，或换成这条示例需求。</p>
      <div className="modal-actions">
        <button type="button" className="plain-button" onClick={()=>setPendingExample(undefined)}>保留草稿</button>
        <button type="button" className="studio-submit" onClick={()=>applyExample(pendingExample)}>替换草稿</button>
      </div>
    </Modal>}
  </div>;
}

export function StudioHeader({label,onMenu,actions}:{label:string;onMenu:()=>void;actions?:ReactNode}) {
  return <header className="studio-header">
    <button type="button" className="icon-button studio-mobile-menu" aria-label="打开菜单" onClick={onMenu}><Menu size={20}/></button>
    <div className="studio-crumb"><span>工作空间</span><b>/</b><strong>{label}</strong></div>
    <div className="studio-header-actions">{actions}</div>
  </header>;
}
