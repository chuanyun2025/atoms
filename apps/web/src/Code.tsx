import {useEffect,useRef,useState} from "react";
import {Compartment,EditorState} from "@codemirror/state";
import {EditorView,lineNumbers,highlightActiveLineGutter} from "@codemirror/view";
import {minimalSetup} from "codemirror";
import {html} from "@codemirror/lang-html";
import {css} from "@codemirror/lang-css";
import {javascript} from "@codemirror/lang-javascript";
import {FileCode2,Folder} from "lucide-react";
import "./code-workspace.css";
type CodeProps = {
  files: Record<string,string>;
  edits: Record<string,string>;
  editable: boolean;
  onEdit: (path:string,value:string)=>void;
};

const editMode=(editable:boolean)=>[EditorState.readOnly.of(!editable),EditorView.editable.of(editable)];

export default function Code({files,edits,editable,onEdit}:CodeProps){
  const [selection,setFile]=useState<string>(),[filter,setFilter]=useState("");
  const node=useRef<HTMLDivElement>(null);
  const editor=useRef<EditorView>(null);
  const mode=useRef(new Compartment()).current;
  const props=useRef({edits,editable,onEdit});
  props.current={edits,editable,onEdit};
  const paths=Object.keys(files);
  const classic=paths.every(path=>["index.html","styles.css","app.js"].includes(path));
  const defaultFile=["src/App.tsx","index.html"].find(path=>Object.hasOwn(files,path))??paths[0]??"";
  const file=selection && Object.hasOwn(files,selection)?selection:defaultFile;
  useEffect(()=>{
    if(!node.current) return;
    const view=new EditorView({parent:node.current,state:EditorState.create({doc:props.current.edits[file]??files[file]??"",extensions:[
      mode.of(editMode(props.current.editable)),minimalSetup,lineNumbers(),highlightActiveLineGutter(),
      EditorView.contentAttributes.of({"aria-label":file||"源码", "aria-multiline":"true"}),
      EditorView.updateListener.of(update=>{
        if(update.docChanged)props.current.onEdit(file,update.state.doc.toString());
      }),
      file.endsWith(".html")?html():file.endsWith(".css")?css():javascript({
        typescript:/\.tsx?$/.test(file),jsx:file.endsWith(".tsx"),
      }),
      EditorView.theme({"&":{height:"100%",fontSize:"12px"},".cm-scroller":{overflow:"auto",fontFamily:"'Cascadia Code',Consolas,monospace"},".cm-content":{padding:"16px 0"},".cm-gutters":{backgroundColor:"#fafafa",borderRight:"1px solid #eceef1"},".cm-line":{padding:"0 18px"}})
    ]})});
    editor.current=view;
    return ()=>{view.destroy();editor.current=null};
  },[file,files,mode]);
  useEffect(()=>{
    editor.current?.dispatch({effects:mode.reconfigure(editMode(editable))});
  },[editable,mode]);
  if (classic) return <div className="code-panel"><div className="file-tabs">{["index.html","styles.css","app.js"].filter(name=>Object.hasOwn(files,name)).map(name=><button key={name} className={file===name?"selected":""} onClick={()=>setFile(name)}>{name}</button>)}<span>{editable?"可编辑":"只读"}</span></div><div ref={node} className="editor"/></div>;

  const folders=new Map<string,string[]>();
  for (const path of paths.filter(path=>path.toLowerCase().includes(filter.trim().toLowerCase())).sort()) {
    const directory=path.includes("/")?path.slice(0,path.lastIndexOf("/")):"";
    const children=folders.get(directory)??[];
    children.push(path);
    folders.set(directory,children);
  }
  return <div className="code-panel react-code-panel">
    <nav className="code-file-browser" aria-label="React 源码文件">
      <input aria-label="搜索源码文件" placeholder="搜索文件" value={filter} onChange={event=>setFilter(event.target.value)}/>
      {Array.from(folders,([directory,children])=><details open key={directory}>
        <summary><Folder size={14}/> {directory||"项目文件"}</summary>
        {children.map(path=><button type="button" key={path} aria-current={file===path?"true":undefined} onClick={()=>setFile(path)}>
          <FileCode2 size={13}/>{path.split("/").at(-1)}
        </button>)}
      </details>)}
      {!folders.size&&<p>没有匹配的文件</p>}
    </nav>
    <div className="code-file-content">
      <div className="code-file-heading"><span>{file}</span><small>{editable?"可编辑":"只读"}</small></div>
      <div ref={node} className="editor"/>
    </div>
  </div>;
}
