import {useEffect,useRef,useState,type FormEvent,type KeyboardEvent} from "react";
import {Link,useParams} from "react-router-dom";
import {ArrowLeft,ArrowUpRight,ChevronLeft,ChevronRight,LoaderCircle,RotateCcw} from "lucide-react";
import {useCapabilities} from "./Studio";
import {SlideArtwork} from "./SlideTemplateGallery";
import {slideTemplates,templatePrompt,type SlideTemplate} from "./slideTemplates";
import {useProjectCreation} from "./useProjectCreation";

function TemplatePreview({template}:{template:SlideTemplate}) {
  const [page,setPage]=useState(0);
  const slides=template.slides;
  const last=slides.length-1;
  const move=(change:number)=>setPage(value=>Math.max(0,Math.min(last,value+change)));

  function onPreviewKey(event:KeyboardEvent<HTMLElement>) {
    if (!["ArrowLeft","ArrowRight","Home","End"].includes(event.key)) return;
    event.preventDefault();
    if (event.key==="Home") setPage(0);
    else if (event.key==="End") setPage(last);
    else move(event.key==="ArrowLeft"?-1:1);
  }

  return <section className="template-preview" aria-label="模板预览" tabIndex={0} onKeyDown={onPreviewKey}>
    <SlideArtwork template={template} slide={slides[page]}/>
    <div className="template-preview-toolbar">
      <button type="button" className="icon-button" aria-label="上一页" disabled={page===0} onClick={()=>move(-1)}><ChevronLeft size={20}/></button>
      <span aria-live="polite">第 {page+1} / {slides.length} 页</span>
      <button type="button" className="icon-button" aria-label="下一页" disabled={page===last} onClick={()=>move(1)}><ChevronRight size={20}/></button>
    </div>
    <div className="template-preview-thumbnails" aria-label="幻灯片页面">
      {slides.map((slide,index)=><button type="button" key={slide.title}
        aria-pressed={index===page} aria-label={`第 ${index+1} 页 ${slide.title}`} onClick={()=>setPage(index)}>
        <div aria-hidden="true"><SlideArtwork template={template} slide={slide}/></div>
        <span>{slide.title}</span>
      </button>)}
    </div>
  </section>;
}

const promptFields=["主题","听众","内容"] as const;

function TemplatePrompt({template}:{template:SlideTemplate}) {
  const draftKey="atoms:slide-template-draft:"+template.id;
  const original=templatePrompt(template);
  const [prompt,setPrompt]=useState(()=>sessionStorage.getItem(draftKey)??original);
  const textArea=useRef<HTMLTextAreaElement>(null);
  const {data:cap}=useCapabilities();
  const {create,busy,error}=useProjectCreation(cap);
  const unavailable=cap && (!cap.model_configured || !cap.worker_available);

  function update(value:string) {
    setPrompt(value);
    sessionStorage.setItem(draftKey,value);
  }

  function selectField(label:string) {
    const field=new RegExp(`(^|\\n)${label}[:：]([^\\n]*)`).exec(prompt);
    const input=textArea.current;
    if (!input) return;
    input.focus();
    if (!field) return;
    const end=field.index+field[0].length;
    input.setSelectionRange(end-field[2].length,end);
  }

  function submit(event:FormEvent) {
    event.preventDefault();
    void create({kind:"slides",prompt,draftKey,slideTemplateId:template.id,title:template.name});
  }

  return <form className="template-customize" onSubmit={submit} aria-label="自定义幻灯片模板">
    <div className="template-customize-intro">
      <h1>{template.name}</h1>
      <p>{template.description}</p>
    </div>
    <div className="template-prompt-heading">
      <label htmlFor="template-prompt">把它变成你的</label>
      <button type="button" className="plain-button" disabled={prompt===original || busy} onClick={()=>update(original)}>
        <RotateCcw size={14}/> 恢复默认
      </button>
    </div>
    <div className="template-field-shortcuts" aria-label="快速选中要替换的内容">
      {promptFields.map(label=><button type="button" key={label} onClick={()=>selectField(label)}>{label}</button>)}
    </div>
    <textarea id="template-prompt" ref={textArea} value={prompt} maxLength={100000} onChange={event=>update(event.target.value)}/>
    {error && <p className="inline-error" role="alert">{error}</p>}
    {cap?.read_only && <p className="template-status" role="status">系统维护中，当前可以预览和编辑提示词。</p>}
    {unavailable && !cap.read_only && <p className="template-status" role="status">生成服务暂不可用，可以先保存项目草稿。</p>}
    <button type="submit" className="studio-submit template-submit" disabled={busy || !prompt.trim() || cap?.read_only}>
      {busy ? <><LoaderCircle size={16} className="spin"/> 正在创建</> :
        <>{unavailable?"保存项目草稿":"使用模板生成"} <ArrowUpRight size={16}/></>}
    </button>
  </form>;
}

export default function SlideTemplateDetail() {
  const {templateId}=useParams();
  const template=slideTemplates.find(item=>item.id===templateId);
  useEffect(()=>{window.scrollTo(0,0)},[templateId]);

  return <div className="studio-content template-detail">
    <Link className="template-return" to="/slides"><ArrowLeft size={17}/> 幻灯片模板</Link>
    {template ? <div className="template-detail-grid" key={template.id}>
      <TemplatePreview template={template}/>
      <TemplatePrompt template={template}/>
    </div> : <div className="studio-empty"><strong>这个模板不存在。</strong></div>}
  </div>;
}
