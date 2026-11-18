import {describe,expect,it} from "vitest";
import {compileReact} from "../src/react-compiler.js";

const artifact=()=>({
  schema_version:"2",title:"汇率查询",summary:"React 组件与数据文件",
  files:{
    "src/App.tsx":'import Board from "./components/Board"; export default function App(){return <Board/>}',
    "src/components/Board.tsx":'import {useState} from "react"; import rates from "../data/rates.json"; export default function Board(){const [rate]=useState(rates.value);return <main>{rate}</main>}',
    "src/data/rates.json":'{"value":"SOURCE-FIXTURE"}',
    "src/styles.css":"body{margin:0}",
  },
});

describe("React project compiler",()=>{
  it("bundles local TSX modules and JSON into the isolated browser artifact",async()=>{
    const result=await compileReact(artifact());
    expect(result.compiler_version).toBe("2");
    expect(result.body_html).toBe('<div id="root"></div>');
    expect(Buffer.from(result.js_base64,"base64").toString("utf8")).toContain("SOURCE-FIXTURE");
  });
  it("rejects imports outside the project and the platform dependencies",async()=>{
    const value=artifact();
    value.files["src/App.tsx"]='import x from "node:fs"; export default function App(){return <main>{String(x)}</main>}';
    await expect(compileReact(value)).rejects.toThrow(/无法导入/);
  });
  it("bundles the platform Three.js dependency for perspective scenes",async()=>{
    const value=artifact();
    value.files["src/App.tsx"]='import {PerspectiveCamera} from "three"; export default function App(){return <main>{new PerspectiveCamera().isPerspectiveCamera?"3D":"error"}</main>}';
    const result=await compileReact(value);
    expect(result.compiler_version).toBe("2");
    const script=Buffer.from(result.js_base64,"base64").toString();
    expect(script).toContain("PerspectiveCamera");
    expect(script).not.toContain("process.emitWarning");
  });
  it("bundles the pre-installed lucide-react vector icon package without network fetches",async()=>{
    const value=artifact();
    value.files["src/App.tsx"]=`import {"Sparkles" as Icon, Check} from "lucide-react";
      // import {Box} from "three"
      const msg = 'Welcome from "three"';
      export default function App(){return <main><p>Don't miss</p><Icon size={18}/><Check size={16}/></main>}`;
    const result=await compileReact(value);
    expect(result.compiler_version).toBe("2");
    expect(result.dependencies).toEqual(["lucide-react","react","react-dom"]);
    const script=Buffer.from(result.js_base64,"base64").toString("utf8");
    expect(script).toContain("svg");
  });
  it("accepts importing the already loaded global stylesheet",async()=>{
    const value=artifact();
    value.files["src/App.tsx"]='import "./styles.css"; '+value.files["src/App.tsx"];
    const result=await compileReact(value);
    expect(Buffer.from(result.css_base64,"base64").toString("utf8")).toBe(value.files["src/styles.css"]);
  });
  it("rejects project paths outside src",async()=>{
    const value=artifact();
    const files={...value.files,"../outside.ts":"export default 0;"};
    await expect(compileReact({...value,files})).rejects.toThrow(/不符合约定/);
  });

  it("checks only runtime modules and skips type expressions",async()=>{
    const value=artifact();
    const files:Record<string,string>={...value.files,
      "src/unused.ts":'export type RecordMap = Record<string,string>; export const legacy = () => window.localStorage.length;',
      "src/App.tsx":`
        import type {RecordMap} from "./unused";
        type StorageName = typeof window.localStorage;
        export default function App(){return <form onSubmit={undefined}><button type="button">Ready</button></form>}
      `,
    };
    await expect(compileReact({...value,files})).resolves.toMatchObject({compiler_version:"2"});
    files["src/App.tsx"]='import {legacy} from "./unused"; export default function App(){return <main>{legacy()}</main>}';
    await expect(compileReact({...value,files})).rejects.toMatchObject({
      code:"SANDBOX_NATIVE_STORAGE",location:{file:"src/unused.ts"},
    });
  });
});
