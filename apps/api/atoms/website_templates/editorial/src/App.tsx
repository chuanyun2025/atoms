import {useState} from "react";
import fallback from "./data/stories.json";
import feed from "./data/editorial-feed.json";

type Story = {id:string; title:string; section:string; source:string; published_at?:string; url?:string; description?:string};
type Snapshot = {status:string; collected_at:string|null; items:Story[]};
const snapshot = feed as Snapshot;
const stories: Story[] = snapshot.status === "sample" ? fallback : snapshot.items;
const sectionNames = Array.from(new Set(stories.map(story => story.section)));
const date = (value: string) => new Intl.DateTimeFormat("zh-CN", {
  dateStyle:"long", timeStyle:"short", timeZone:"Asia/Shanghai",
}).format(new Date(value));
const store = (window as unknown as {atoms:{storage:{get(key:string, fallback:string[]):string[];set(key:string, value:string[]):void;flush():Promise<void>}}}).atoms.storage;

function Byline({story}: {story:Story}) {
  return <div className="byline"><strong>{story.source}</strong>{story.published_at && <time dateTime={story.published_at}>{date(story.published_at)}</time>}</div>;
}

export default function App() {
  const [section, setSection] = useState("要闻");
  const [query, setQuery] = useState("");
  const [detail, setDetail] = useState<Story|null>(null);
  const [saved, setSaved] = useState(() => store.get("editorial.saved.v1", []));
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState("");
  const isFront = section === "要闻" && !query.trim();
  const visible = stories.filter(story =>
    (section === "要闻" || (section === "收藏" ? saved.includes(story.id) : story.section === section)) &&
    (story.title + story.source).toLowerCase().includes(query.trim().toLowerCase())
  );
  const lead = isFront ? visible[0] : undefined;

  function openStory(story: Story) {
    setDetail(story);
    window.scrollTo({top:0});
  }

  async function toggle(story: Story) {
    if (saving) return;
    setSaving(true);
    setFeedback("");
    const next = saved.includes(story.id) ? saved.filter(id => id !== story.id) : [...saved, story.id];
    try {
      store.set("editorial.saved.v1", next);
      await store.flush();
      setSaved(next);
    } catch {
      setFeedback("收藏保存失败，请重试。");
    } finally {
      setSaving(false);
    }
  }

  return <>
    <header className="masthead"><div className="shell masthead-row">
      <button className="brand" onClick={() => {setSection("要闻");setQuery("");setDetail(null);}}>
        <span className="brand-icon" aria-hidden="true">◒</span><span>[[copy:site.name]]</span>
      </button>
      <nav aria-label="资讯栏目">{["要闻", ...sectionNames, "收藏"].map(name =>
        <button key={name} aria-pressed={!detail && section === name} onClick={() => {setDetail(null);setSection(name);setQuery("");}}>
          {name}{name === "收藏" && saved.length > 0 ? " " + saved.length : ""}
        </button>
      )}</nav>
      <label className="search"><span>搜索资讯</span><input value={query} onChange={event => {setDetail(null);setQuery(event.target.value);}} placeholder="标题或来源"/></label>
    </div></header>
    <main className="shell">
      <div className="edition"><span>{snapshot.status === "sample" ? "示例内容" : "公开发布快照"}</span>
        <span>{snapshot.collected_at && <>采集于 <time dateTime={snapshot.collected_at}>{date(snapshot.collected_at)}</time></>}{snapshot.status === "stale" && " · 上次成功采集"}</span>
      </div>
      {feedback && <p role="alert">{feedback}</p>}
      {detail ? <article className="detail">
        <button className="text-button" onClick={() => setDetail(null)}>← 返回资讯</button>
        <p className="eyebrow">{detail.section}</p><h1>{detail.title}</h1><Byline story={detail}/>
        {detail.description && <p>{detail.description}</p>}
        {detail.url && <div className="source">
          <label htmlFor="source-url">官方原文地址</label>
          {window.top === window.self ? <a href={detail.url} target="_blank" rel="noreferrer">{detail.url}</a> :
            <input id="source-url" value={detail.url} readOnly onFocus={event => event.target.select()}/>}
        </div>}
        <button className="primary" aria-pressed={saved.includes(detail.id)} disabled={saving} onClick={() => void toggle(detail)}>
          {saved.includes(detail.id) ? "取消收藏" : "收藏此条"}
        </button>
      </article> : <>
        {lead && <div className="front">
          <article className="feature">
            <div className="feature-art" aria-hidden="true"><span></span><strong>[[copy:site.name]]</strong></div>
            <p className="eyebrow">头条 <span>／ {lead.section}</span></p>
            <h1><button onClick={() => openStory(lead)}>{lead.title}</button></h1>
            <Byline story={lead}/><button className="primary" onClick={() => openStory(lead)}>查看详情 →</button>
          </article>
          <aside className="briefs"><h2>发布速览</h2>{stories.slice(1,6).map(story =>
            <article key={story.id}><span className="eyebrow">{story.section}</span><h3><button onClick={() => openStory(story)}>{story.title}</button></h3><Byline story={story}/></article>
          )}</aside>
        </div>}
        <section className="articles">
          <h2>{query.trim() ? "搜索结果" : section === "要闻" ? "全部资讯" : section}</h2>
          {!visible.length && <p className="empty">{snapshot.status === "unavailable" ? "暂时无法取得资讯源。稍后重新生成版本可更新内容。" : section === "收藏" ? "还没有收藏的资讯。" : "没有找到匹配的资讯。"}</p>}
          <div className="article-grid">{visible.map(story => <article key={story.id}>
            <p className="eyebrow">{story.section}</p><h3><button onClick={() => openStory(story)}>{story.title}</button></h3><Byline story={story}/>
          </article>)}</div>
        </section>
      </>}
    </main>
    <footer className="shell footer">[[copy:site.name]] · {snapshot.status === "sample" ? "示例内容" : "公开资讯索引"}</footer>
  </>;
}
