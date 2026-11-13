import {createHash} from "node:crypto";
import {readFileSync} from "node:fs";
import {posix} from "node:path";
import {fileURLToPath} from "node:url";
import {Ajv2020} from "ajv/dist/2020.js";
import {build,type Loader,type Plugin} from "esbuild";
import {compile,type Compiled} from "./compiler.js";

type ReactArtifact = {schema_version:"2";title:string;summary:string;files:Record<string,string>};
const schema = JSON.parse(readFileSync(new URL("../../../shared/contracts/react-artifact.schema.json",import.meta.url),"utf8"));
const validate = new Ajv2020({strict:true,allowMatchingProperties:true,allErrors:true}).compile<ReactArtifact>(schema);
const dependencies = new Set(["react","react-dom/client","react/jsx-runtime"]);
const runtimeDependencies = JSON.parse(readFileSync(new URL("../../../shared/runtime-dependencies.json",import.meta.url),"utf8"));
for (const name of Object.keys(runtimeDependencies)) dependencies.add(name);
const loaderByExtension:Record<string,Loader> = {".ts":"ts",".tsx":"tsx",".json":"json"};
const entryPath = "__atoms_entry.tsx";
const entry = `
import {createRoot} from "react-dom/client";
import App from "./src/App.tsx";
const root = createRoot(document.getElementById("root"));
root.render(<App />);
`;

function sourceModules(files:Record<string,string>):Plugin {
  return {
    name:"atoms-source",
    setup(bundle) {
      bundle.onResolve({filter:/^atoms-entry$/}, args =>
        args.kind==="entry-point"?{path:entryPath,namespace:"atoms-source"}:undefined
      );
      bundle.onResolve({filter:/.*/,namespace:"atoms-source"}, args => {
        if (args.kind !== "import-statement") {
          return {errors:[{text:"源码只支持静态 import"}]};
        }
        if (dependencies.has(args.path)) return {path:fileURLToPath(import.meta.resolve(args.path))};
        if (args.path.startsWith("./") || args.path.startsWith("../")) {
          const path=posix.join(posix.dirname(args.importer),args.path);
          // The trusted document loads the global stylesheet separately.
          if (path === "src/styles.css") return {path,namespace:"atoms-styles"};
          const found=[path,path+".tsx",path+".ts"].find(name =>
            Object.hasOwn(files,name) && Object.hasOwn(loaderByExtension,posix.extname(name))
          );
          if (found) return {path:found,namespace:"atoms-source"};
        }
        return {errors:[{text:"无法导入 "+JSON.stringify(args.path)+"。可用 React、Three.js 与项目 src 内的 TSX、TS、JSON 文件"}]};
      });
      bundle.onLoad({filter:/.*/,namespace:"atoms-styles"}, () => ({contents:"",loader:"js"}));
      bundle.onLoad({filter:/.*/,namespace:"atoms-source"}, args => ({
        contents:args.path===entryPath?entry:files[args.path],
        loader:loaderByExtension[posix.extname(args.path)],
      }));
    },
  };
}

export async function compileReact(input:unknown):Promise<Compiled> {
  if (!validate(input)) {
    const details=validate.errors?.slice(0,6).map(issue=>[
      issue.instancePath||"根对象",issue.message,
      issue.keyword==="required"?issue.params.missingProperty:"",
      issue.keyword==="additionalProperties"?issue.params.additionalProperty:"",
    ].filter(Boolean).join(" "));
    throw new Error("React 产物不符合约定："+details?.join("；"));
  }
  let total=0;
  for (const source of Object.values(input.files)) {
    const size=Buffer.byteLength(source);
    if (size>4*1024*1024) throw new Error("单文件超过 4 MiB 资源保护");
    total+=size;
  }
  if (total>8*1024*1024) throw new Error("源码总大小超过 8 MiB 资源保护");

  const bundle=await build({
    entryPoints:["atoms-entry"],
    plugins:[sourceModules(input.files)],
    tsconfigRaw:{compilerOptions:{}},
    jsx:"automatic",
    bundle:true,
    platform:"browser",
    format:"iife",
    target:"es2022",
    define:{"process.env.NODE_ENV":'"production"'},
    minify:true,
    write:false,
    logLevel:"silent",
  });
  const compiled=compile({
    schema_version:"1",title:input.title,summary:input.summary,
    files:{"index.html":'<div id="root"></div>',"styles.css":input.files["src/styles.css"],"app.js":bundle.outputFiles[0].text},
  });
  return {
    ...compiled,
    digest:createHash("sha256").update(JSON.stringify({artifact:input,bundle:compiled.digest,compiler_version:"2"})).digest("hex"),
    compiler_version:"2",
  };
}
