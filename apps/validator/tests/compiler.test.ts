import { describe,it,expect } from "vitest";
import { compile,documentFor,csp } from "../src/compiler.js";
const artifact = () => ({schema_version:"1",title:"计数器",summary:"可点击",files:{"index.html":"<main><h1>0</h1><button>加一</button></main>","styles.css":"body{color:#222}","app.js":"document.querySelector('button').onclick=()=>{};"}});
describe("artifact boundary",() => {
  it("preserves standard text semantics in the preview",()=>{
    const a=artifact();
    a.files["index.html"]='<main><q>示例</q><cite>作品名</cite><kbd>Enter</kbd><ruby>字<rt>zì</rt></ruby></main>';
    expect(compile(a).body_html).toBe(a.files["index.html"]);
  });
  it("identifies missing and unexpected artifact fields",()=>{
    const {files,...metadata}=artifact();
    const {"app.js":script,...incomplete}=files;
    const compileInvalid=()=>compile({...metadata,"wrong.js":script,files:incomplete});
    expect(compileInvalid).toThrow(/根对象 多出 "wrong\.js".*\/files 缺少 app\.js/);
  });
  it("accepts native datalist and safe form metadata without stripping functionality",()=>{
    const a=artifact();
    a.files["index.html"]='<main><label for="city">城市</label><input id="city" list="cities" enterkeyhint="done" spellcheck="false"><datalist id="cities"><option value="上海" label="上海"></option></datalist><meter min="0" max="100" low="20" high="80" optimum="60" value="50"></meter></main>';
    const output=compile(a).body_html;
    expect(output).toContain('list="cities"');
    expect(output).toContain('<datalist id="cities">');
    expect(output).toContain('optimum="60"');
  });
  it("reports HTML problems together so repair can address them in one pass",()=>{
    const a=artifact();a.files["index.html"]='<main bad-one="x"><iframe bad-two="y"></iframe><input onfocus="alert(1)" formaction="https://evil.test"></main>';
    let message="";try{compile(a)}catch(e){message=(e as Error).message}
    for(const text of ["bad-one","bad-two","iframe","onfocus","formaction"])expect(message).toContain(text);
  });
  it("accepts application code beyond the former small file budget",()=>{
    const a=artifact();
    a.files["app.js"]="/*"+"x".repeat(150000)+"*/\nvoid 0;";
    a.files["styles.css"]="/*"+"y".repeat(100000)+"*/\nbody{color:green}";
    expect(compile(a).body_html).toContain("<button>");
  });
  it("compiles real files without interpolating app code",() => {
    const a=artifact(); a.files["app.js"]="const text='</script><img src=x onerror=alert(1)>';";
    const c=compile(a); const html=documentFor(c,{instance_id:"test"});
    expect(html).not.toContain(a.files["app.js"]); expect(html).toContain("<button>加一</button>");
    expect(html).not.toMatch(/\{\{[A-Z0-9_]+\}\}/);
    expect(csp("http://localhost:8080")).toContain("script-src data:");
  });
  it.each(["<script>alert(1)</script>","<img src=x onerror=alert(1)>","<iframe src='https://evil.test'></iframe>","<a href='javascript:alert(1)'>go</a>","<svg onload=alert(1)></svg>"])("rejects active HTML %s",html => {
    const a=artifact();a.files["index.html"]=html;expect(()=>compile(a)).toThrow();
  });
  it("rejects module code and external styles",() => {
    const a=artifact();a.files["app.js"]="import x from 'https://x.test/x'";expect(()=>compile(a)).toThrow();
    a.files["app.js"]="void 0";a.files["styles.css"]="@import 'https://x.test/x.css'";expect(()=>compile(a)).toThrow();
  });
  it("preserves scroll-behavior in normal and reduced-motion styles", () => {
    const a = artifact();
    a.files["styles.css"] = "html{scroll-behavior:smooth}@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}";
    expect(Buffer.from(compile(a).css_base64,"base64").toString()).toBe(a.files["styles.css"]);
  });
  it.each(["behavior:none", "-ms-behavior:none", "-moz-binding:none", "width:expression(1)"])("still rejects active CSS %s", declaration => {
    const a = artifact();
    a.files["styles.css"] = `main{${declaration}}`;
    expect(() => compile(a)).toThrow(/主动/);
  });
});
