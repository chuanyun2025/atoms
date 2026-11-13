import {useState} from "react";
import product from "./data/product.json";
import media from "./assets/starter-media.json";

const cover = (media as {hero?:string}).hero;

export default function App() {
  const [selected,setSelected] = useState(0);
  const version = product.versions[selected];
  return <>
    <header className="top"><div className="wrap top-row">
      <a className="brand" href="#top"><span aria-hidden="true">◉</span> {product.brand}</a>
      <nav aria-label="产品导航"><a href="#features">体验</a><a href="#versions">规格</a><a href="#questions">常见问题</a></nav>
    </div></header>
    <main id="top">
      <section className="hero"><div className="wrap hero-row">
        <div><p className="label">{product.category}</p><h1>{product.headline}</h1><p className="intro">{product.description}</p><a className="cta" href="#versions">比较产品规格 →</a></div>
        {cover ? <img src={cover} alt={product.brand + " 概念图"}/> :
          <div className="hero-art" aria-hidden="true"><span>{product.category}</span><strong>{product.brand}</strong></div>}
      </div></section>
      <section id="features" className="wrap features"><h2>[[copy:features.heading]]</h2>
        <div className="tiles">{product.features.map(feature => <article key={feature.name}>
          <span className="feature-icon" aria-hidden="true">{feature.icon}</span><h3>{feature.name}</h3><p>{feature.copy}</p>
        </article>)}</div>
      </section>
      <section id="versions" className="wrap versions">
        <div><h2>型号对比</h2><div className="chooser" aria-label="选择型号">{product.versions.map((item,i) =>
          <button key={item.name} aria-pressed={i === selected} onClick={() => setSelected(i)}>{item.name}</button>
        )}</div></div>
        <article aria-live="polite"><h3>{version.name}</h3><p>{version.use}</p><dl>
          {version.specs.map(spec => <div key={spec.label}><dt>{spec.label}</dt><dd>{spec.value}</dd></div>)}
        </dl></article>
      </section>
      <section id="questions" className="wrap questions"><h2>常见问题</h2>{product.questions.map(item =>
        <details key={item.question}><summary>{item.question}</summary><p>{item.answer}</p></details>
      )}</section>
    </main>
    <footer className="wrap footer">{product.brand} · 产品概念示例</footer>
  </>;
}
