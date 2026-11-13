import {useState,type ReactNode} from "react";
import {ArrowUpRight,Eye,FileText,Gamepad2} from "lucide-react";
import {coverUrl,studioExamples,type StudioExample} from "./studioExamples";
import {SlideTemplateGallery} from "./SlideTemplateGallery";

type Filter="全部"|"街机"|"解谜"|"竞速"|"动作"|"射击";
type HomeTab="发现"|"网站"|"幻灯片"|"项目"|"模板";

export function ExampleCard({example,onOpen,template=false,index}:{example:StudioExample;onOpen:()=>void;template?:boolean;index:number}) {
  const Icon=example.kind==="game"?Gamepad2:template||example.kind==="slides"?FileText:Eye;
  return <button type="button" className="example-card-v2" onClick={onOpen} aria-label={"预览"+example.title}>
    <div className={"example-cover cover-"+example.id}>
      <img src={coverUrl(example.id)} alt="" width={768} height={432} loading={index<3?"eager":"lazy"} decoding="async"/>
      <span><Icon size={14}/> {example.category}</span>
    </div>
    <div className="example-info">
      <div><strong>{example.title}</strong><p>{example.description}</p></div>
      <ArrowUpRight size={17} aria-hidden="true"/>
    </div>
  </button>;
}

export default function StudioGallery({game,onOpen,projects}:{game:boolean;onOpen:(example:StudioExample)=>void;projects:ReactNode}) {
  const [filter,setFilter]=useState<Filter>("全部");
  const [tab,setTab]=useState<HomeTab>("发现");
  const examples=studioExamples.filter(item=>game
    ? item.kind==="game" && (filter==="全部" || item.category===filter)
    : item.kind!=="game" && (tab!=="网站"&&tab!=="幻灯片" || item.category===tab));
  return <section className="example-gallery" aria-label={game?"游戏示例":"首页作品区"}>
    <div className="gallery-heading">
      <h2>{game?"游戏示例":"创作灵感"}</h2>
      <p>{game?"试玩之后，把喜欢的玩法带回创作框。":"看看示例能做什么，或继续你的项目。"}</p>
    </div>
    {game ? <div className="gallery-tabs" aria-label="游戏分类">
      {(["全部","动作","射击","街机","解谜","竞速"] as const).map(value=><button type="button" key={value} aria-pressed={filter===value} onClick={()=>setFilter(value)}>{value}</button>)}
    </div> : <div className="gallery-tabs" aria-label="首页作品分类">
      {(["发现","网站","幻灯片","项目","模板"] as const).map(value=><button type="button" key={value} aria-pressed={tab===value} onClick={()=>setTab(value)}>{value}</button>)}
    </div>}
    {!game && tab==="项目" ? projects : <>
      {!game && tab==="模板" && <p className="template-guidance">打开模板预览，选择「使用此示例的提示词」开始编辑。</p>}
      <div className="example-cover-grid">
        {examples.map((item,index)=><ExampleCard key={item.id} example={item} index={index} template={!game && tab==="模板"} onOpen={()=>onOpen(item)}/>)}
      </div>
      {!game && tab==="模板" && <SlideTemplateGallery/>}
    </>}
  </section>;
}

export function SlideExampleGallery({onOpen}:{onOpen:(example:StudioExample)=>void}) {
  const examples=studioExamples.filter(example=>example.kind==="slides");
  return <section className="example-gallery published-example-gallery" aria-label="幻灯片示例">
    <div className="gallery-heading"><h2>幻灯片示例</h2><p>打开完整演示，翻阅每一页。</p></div>
    <div className="example-cover-grid">
      {examples.map((example,index)=><ExampleCard key={example.id} example={example} index={index} onOpen={()=>onOpen(example)}/>)}
    </div>
  </section>;
}
