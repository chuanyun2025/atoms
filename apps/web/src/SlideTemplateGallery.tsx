import type {CSSProperties} from "react";
import {Link} from "react-router-dom";
import {ArrowUpRight} from "lucide-react";
import {slideTemplates,type SlideTemplate,type TemplateSlide} from "./slideTemplates";
import "./slide-templates.css";

const exampleBars=[32,48,44,65,71,93];

function SampleBars() {
  return <div className="template-bar-chart" aria-hidden="true">
    {exampleBars.map(height=><i key={height} style={{height:`${height}%`}}/>)}
  </div>;
}

export function SlideArtwork({template,slide}:{template:SlideTemplate;slide:TemplateSlide}) {
  const {palette,theme,eyebrow}=template;
  const colors={
    "--deck-bg":palette.background,
    "--deck-ink":palette.ink,
    "--deck-accent":palette.accent,
    "--deck-secondary":palette.secondary,
  } as CSSProperties;
  return <div className={`template-slide template-slide--${theme} template-slide--${slide.layout}`} style={colors}>
    <div className="template-slide-inner">
      <div className="template-slide-copy">
        <span className="template-slide-eyebrow">{eyebrow}</span>
        <h3>{slide.title}</h3>
        <p>{slide.description}</p>
      </div>
      {slide.layout==="cover" && <div className="template-slide-cover-art" aria-hidden="true">
        {theme==="launch" ? <img src="/templates/launch-speaker.webp" width={720} height={864} alt="" decoding="async"/> :
          theme==="report" ? <SampleBars/> : <div className="template-research-art"><i/><i/><i/></div>}
      </div>}
      {slide.items && <ul className="template-slide-items">
        {slide.items.map(item=><li key={item.title}>
          <strong>{item.title}</strong><span>{item.detail}</span>
        </li>)}
      </ul>}
      {slide.layout==="metrics" && <SampleBars/>}
    </div>
  </div>;
}

export function SlideTemplateGallery() {
  return <section className="slide-template-gallery" aria-label="幻灯片模板">
    <div className="gallery-heading">
      <h2>幻灯片模板</h2>
      <p>挑一套版式，换成你的主题和内容。</p>
    </div>
    <div className="example-cover-grid">
      {slideTemplates.map(template=><Link key={template.id} className="example-card-v2 slide-template-card"
        aria-label={`预览模板 ${template.name}`} to={`/slides/templates/${template.id}`}>
        <div className="slide-template-cover" aria-hidden="true">
          <SlideArtwork template={template} slide={template.slides[0]}/>
        </div>
        <div className="example-info">
          <div><strong>{template.name}</strong><p>{template.description}</p></div>
          <ArrowUpRight size={17} aria-hidden="true"/>
        </div>
      </Link>)}
    </div>
  </section>;
}
