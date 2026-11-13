import {useState} from "react";
import projects from "./data/projects.json";
import media from "./assets/starter-media.json";

const categories = ["全部", ...new Set(projects.map(project => project.category))];
const pictures: Record<string,string|undefined> = media;

function ProjectVisual({image,alt,title}: {image:string;alt:string;title:string}) {
  return pictures[image] ? <img src={pictures[image]} alt={alt}/> : <div className="art-fallback" aria-hidden="true">{title}</div>;
}

export default function App() {
  const [category,setCategory] = useState("全部");
  const [selected,setSelected] = useState<typeof projects[number] | null>(null);
  const visible = category === "全部" ? projects : projects.filter(project => project.category === category);

  function select(project:typeof projects[number] | null) {
    setSelected(project);
    window.scrollTo({top:0});
  }

  return <div className="site">
    <header className="wrap header">
      <a className="wordmark" href="#top" onClick={() => setSelected(null)}>[[copy:site.name]]</a>
      <nav aria-label="主要导航"><a href="#work" onClick={() => setSelected(null)}>作品</a><a href="#about" onClick={() => setSelected(null)}>关于</a></nav>
    </header>
    <main className="wrap" id="top">
      {selected ? <article className="case">
        <button className="back" onClick={() => select(null)}>← 返回作品</button>
        <p className="label">{selected.category}</p><h1>{selected.title}</h1><p className="intro">{selected.subtitle}</p>
        <ProjectVisual image={selected.image} alt={selected.alt} title={selected.title}/>
        <div className="case-copy"><h2>设计过程</h2><p>{selected.description}</p></div>
      </article> : <>
        <section className="hero">
          <div><p className="label">[[copy:hero.eyebrow]]</p><h1>[[copy:hero.headline]]</h1><p className="intro">[[copy:hero.intro]]</p><a className="cta" href="#work">浏览精选作品 ↓</a></div>
          <div className="hero-image"><ProjectVisual image={projects[0]?.image ?? ""} alt={projects[0]?.alt ?? ""} title="精选作品"/></div>
        </section>
        <section id="work" className="work">
          <div className="section-head"><h2>精选作品</h2><div className="filters" aria-label="筛选作品">{categories.map(name =>
            <button key={name} aria-pressed={name === category} onClick={() => setCategory(name)}>{name}</button>
          )}</div></div>
          <div className="projects">{visible.map(project =>
            <button className="project" key={project.title} onClick={() => select(project)}>
              <ProjectVisual image={project.image} alt={project.alt} title={project.title}/>
              <span className="project-copy"><span className="label">{project.category}</span><strong>{project.title}</strong><span>{project.subtitle}</span></span>
            </button>
          )}</div>
        </section>
        <section id="about" className="about"><h2>关于</h2><p>[[copy:about.bio]]</p></section>
      </>}
    </main>
    <footer className="wrap footer">[[copy:site.name]]</footer>
  </div>;
}
