import {useEffect,useRef,useState} from "react";
import {EditorState} from "@codemirror/state";
import {EditorView,lineNumbers,highlightActiveLineGutter} from "@codemirror/view";
import {defaultHighlightStyle,syntaxHighlighting} from "@codemirror/language";
import {html} from "@codemirror/lang-html";
import {css} from "@codemirror/lang-css";
import {javascript} from "@codemirror/lang-javascript";
import {FileCode2,Folder} from "lucide-react";
import "./code-workspace.css";
export default function Code({files}:{files:Record<string,string>}){
  const [selection,setFile]=useState<string>(),[filter,setFilter]=useState("");
  const node=useRef<HTMLDivElement>(null);
  const paths=Object.keys(files);
  const react=Object.hasOwn(files,"src/App.tsx");
  const file=selection && Object.hasOwn(files,selection)?selection:react?"src/App.tsx":"index.html";
  useEffect(()=>{
    if(!node.current) return;
    const view=new EditorView({parent:node.current,state:EditorState.create({doc:files[file]||"",extensions:[
      EditorState.readOnly.of(true),EditorView.editable.of(false),lineNumbers(),highlightActiveLineGutter(),syntaxHighlighting(defaultHighlightStyle),
      file.endsWith(".html")?html():file.endsWith(".css")?css():javascript({
        typescript:/\.tsx?$/.test(file),jsx:file.endsWith(".tsx"),
      }),
      EditorView.theme({"&":{height:"100%",fontSize:"12px"},".cm-scroller":{overflow:"auto",fontFamily:"'Cascadia Code',Consolas,monospace"},".cm-content":{padding:"16px 0"},".cm-gutters":{backgroundColor:"#fafafa",borderRight:"1px solid #eceef1"},".cm-line":{padding:"0 18px"}})
    ]})});
    return ()=>view.destroy();
  },[file,files]);
  if (!react) return <div className="code-panel"><div className="file-tabs">{["index.html","styles.css","app.js"].map(name=><button key={name} className={file===name?"selected":""} onClick={()=>setFile(name)}>{name}</button>)}<span>只读 · 完整源码</span></div><div ref={node} className="editor"/></div>;

  const folders=new Map<string,string[]>();
  for (const path of paths.filter(path=>path.toLowerCase().includes(filter.trim().toLowerCase())).sort()) {
    const directory=path.slice(0,path.lastIndexOf("/"));
    const children=folders.get(directory)??[];
    children.push(path);
    folders.set(directory,children);
  }
  return <div className="code-panel react-code-panel">
    <nav className="code-file-browser" aria-label="React 源码文件">
      <input aria-label="搜索源码文件" placeholder="搜索文件" value={filter} onChange={event=>setFilter(event.target.value)}/>
      {Array.from(folders,([directory,children])=><details open key={directory}>
        <summary><Folder size={14}/> {directory}</summary>
        {children.map(path=><button type="button" key={path} aria-current={file===path?"true":undefined} onClick={()=>setFile(path)}>
          <FileCode2 size={13}/>{path.split("/").at(-1)}
        </button>)}
      </details>)}
      {!folders.size&&<p>没有匹配的文件</p>}
    </nav>
    <div className="code-file-content">
      <div className="code-file-heading"><span>{file}</span><small>只读</small></div>
      <div ref={node} className="editor"/>
    </div>
  </div>;
}
