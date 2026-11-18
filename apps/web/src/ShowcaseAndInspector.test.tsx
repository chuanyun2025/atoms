// @vitest-environment happy-dom
import {readFileSync} from "node:fs";
import {resolve} from "node:path";
import {act} from "react";
import {createRoot,type Root} from "react-dom/client";
import {QueryClient,QueryClientProvider} from "@tanstack/react-query";
import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import {ExampleShowcase} from "./ExamplePreview";
import InspectorDrawer from "./InspectorPanel";
import {studioExamples} from "./studioExamples";

(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT = true;

function jsonResponse(body:unknown,status=200):Response {
  return new Response(JSON.stringify(body),{
    status,
    headers:{"Content-Type":"application/json"},
  });
}

describe("ExampleShowcase and InspectorDrawer",()=>{
  let container:HTMLDivElement;
  let root:Root;

  beforeEach(async()=>{
    const happy=(window as unknown as {happyDOM?:{settings:{handleDisabledFileLoadingAsSuccess?:boolean}}}).happyDOM;
    if(happy?.settings) happy.settings.handleDisabledFileLoadingAsSuccess=true;
    await import("./Code");
    container=document.createElement("div");
    document.body.appendChild(container);
    root=createRoot(container);
  });

  afterEach(()=>{
    vi.restoreAllMocks();
    act(()=>{
      root.unmount();
    });
    container.remove();
  });

  it("switches gallery example between preview, read-only source, and BuildStory replay without session calls",async()=>{
    const example=studioExamples.find(item=>item.id==="jinheng-finance")!;
    const fetchMock=vi.fn(async(input:RequestInfo|URL)=>{
      const url=String(input);
      if(url.endsWith("/examples/jinheng-finance/preview-ticket")){
        return jsonResponse({
          url:"/sandbox/examples/jinheng-finance?ticket=test",
          instance_id:"inst-1",
          channel_nonce:"nonce-1",
          read_only:false,
        });
      }
      if(url.endsWith("/examples/jinheng-finance/source")){
        return jsonResponse({
          example_id:"jinheng-finance",
          schema_version:"2",
          title:example.title,
          summary:example.description,
          files:{
            "src/App.tsx":"export default function App(){return <h1>金衡财经</h1>}",
            "src/styles.css":"body{margin:0}",
            "src/data/marketData.ts":"export const INDICES=[]",
          },
        });
      }
      throw new Error("Unexpected URL: "+url);
    });
    vi.stubGlobal("fetch",fetchMock);

    await act(async()=>{
      root.render(<ExampleShowcase example={example} busy={false} onUsePrompt={()=>{}}/>);
    });

    expect(container.textContent).toContain("本地静态快照 · 零积分消耗");

    const storyBtn=Array.from(container.querySelectorAll("button")).find(btn=>btn.textContent?.includes("构建回放"))!;
    await act(async()=>{
      storyBtn.dispatchEvent(new MouseEvent("click",{bubbles:true}));
    });

    expect(container.textContent).toContain("主 Agent 规划摘要");
    expect(container.textContent).toContain("生成一个财经网站");
    expect(container.textContent).toContain("VALIDATION_FAILED");
    expect(container.textContent).toContain("5.9279 积分");

    const sourceBtn=Array.from(container.querySelectorAll("button")).find(btn=>btn.textContent?.includes("只读源码"))!;
    await act(async()=>{
      sourceBtn.dispatchEvent(new MouseEvent("click",{bubbles:true}));
    });
    for(let i=0;i<20&&!container.textContent?.includes("marketData.ts");i++){
      await act(async()=>{
        await new Promise(resolve=>setTimeout(resolve,25));
      });
    }

    expect(container.textContent).toContain("marketData.ts");
    expect(fetchMock.mock.calls.some(([url])=>String(url).includes("/session"))).toBe(false);
  });

  it("keeps InspectorDrawer collapsed until opened and renders plan, mechanics, repairs, and billing",async()=>{
    const fetchMock=vi.fn(async(input:RequestInfo|URL)=>{
      const url=String(input);
      if(url.endsWith("/api/v1/session")){
        return jsonResponse({visitor_id:"vis-1",csrf_token:"csrf-1"});
      }
      if(url.endsWith("/api/v1/runs/run-demo-1/inspector")){
        return jsonResponse({
          run_id:"run-demo-1",
          project_kind:"game",
          status:"succeeded",
          stage:"completed",
          version_number:2,
          elapsed_seconds:31.5,
          task_plan:{
            experience:"other_game",
            rendering:"canvas2d",
            game_genre:"arcade_platformer",
            visual_direction:"高对比赛博网格街机风",
            requirements:["支持键盘与触屏操作","包含三条生命与暂停重开"],
            mechanics:{
              initial_state:"玩家满血 3 点位于起点",
              invariants:["暂停期间不扣减生命"],
              end_condition:"清空敌人获胜，生命归零失败",
              examples:[{setup:"游戏进行中",action:"按下 Esc",expected:"进入暂停遮罩"}],
            },
          },
          validation:{
            ready:true,
            acceptance:"startup",
            sandbox_enabled:true,
            schema_version:"2",
            compiler_version:"2",
            sdk_version:"1",
            file_count:4,
            static_contract:"react-ast-import-whitelist",
            generation_skill:{kind:"game",revision:"v2"},
            website_starter:null,
            slide_renderer:null,
          },
          repairs:[
            {
              seq:5,
              round:1,
              label:"修复编译错误（第 1/10 轮）",
              strategy:"修正模块导入路径并保留原玩法状态",
              diagnostic:{code:"COMPILE_IMPORT",file:"src/App.tsx",line:4,subject:"Disallowed import"},
              created_at:1700000000,
            },
          ],
          billing:{
            calls:[
              {attempt:1,role:"planning",status:"settled",input_tokens:2000,output_tokens:500,settled_units:80000,settled_credits:"0.080000",reserved_credits:"1.000000",error_code:null},
              {attempt:2,role:"generation",status:"settled",input_tokens:5000,output_tokens:3000,settled_units:340000,settled_credits:"0.340000",reserved_credits:"2.000000",error_code:null},
            ],
            media_calls:[],
            total_input_tokens:7000,
            total_output_tokens:3500,
            total_settled_units:420000,
            total_settled_credits:"0.420000",
          },
        });
      }
      throw new Error("Unexpected URL: "+url);
    });
    vi.stubGlobal("fetch",fetchMock);

    const queryClient=new QueryClient({defaultOptions:{queries:{retry:false}}});
    await act(async()=>{
      root.render(
        <QueryClientProvider client={queryClient}>
          <InspectorDrawer runId="run-demo-1" label="版本 v2 · 工程透视"/>
        </QueryClientProvider>,
      );
    });

    expect(fetchMock).not.toHaveBeenCalled();

    const details=container.querySelector("details")!;
    await act(async()=>{
      details.open=true;
      details.dispatchEvent(new Event("toggle"));
    });
    await act(async()=>{
      await new Promise(resolve=>setTimeout(resolve,20));
    });

    expect(container.textContent).toContain("高对比赛博网格街机风");
    expect(container.textContent).toContain("游戏规则状态机（GameMechanics）");
    expect(container.textContent).toContain("COMPILE_IMPORT");
    expect(container.textContent).toContain("src/App.tsx:4");
    expect(container.textContent).toContain("0.42 积分");
  });

  it("keeps every studioExample BuildStory backed by real archive snapshots and omits fabricated stories on hand-coded demos",()=>{
    const sharedDir=resolve(process.cwd(),"../../shared");
    for(const item of studioExamples){
      if(!item.publishedExample){
        expect(item.buildStory).toBeUndefined();
        continue;
      }
      const folder=item.kind==="game"?"game-examples":"published-examples";
      const raw=JSON.parse(readFileSync(resolve(sharedDir,folder,`${item.publishedExample}.json`),"utf8")) as {
        artifact:{schema_version:string;files:Record<string,string>};
        compiled:{digest:string};
        build_story:typeof item.buildStory;
      };
      expect(item.buildStory).toBeDefined();
      expect(item.buildStory).toEqual(raw.build_story);
      expect(item.buildStory!.source).toBe("atoms-sqlite-run-archive-v1");
      expect(item.buildStory!.compiledDigest).toBe(raw.compiled.digest);
      const expectedCredits=((item.buildStory!.inputTokens*20+item.buildStory!.outputTokens*80)/1_000_000).toFixed(6);
      expect(item.buildStory!.credits).toBe(expectedCredits);

      const fileSet=new Set(Object.keys(raw.artifact.files));
      for(const archFile of item.buildStory!.architecture){
        expect(fileSet.has(archFile),`${item.id} missing architecture file ${archFile}`).toBe(true);
      }
      if(raw.artifact.schema_version==="1"){
        expect(item.buildStory!.rendering).not.toContain("React");
      }else{
        expect(item.buildStory!.rendering).toContain("React");
      }
    }
  });
});
