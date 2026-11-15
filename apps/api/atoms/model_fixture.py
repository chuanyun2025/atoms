"""Deterministic model responses for the isolated test environment."""
import re

from .db import compact
from .website_starters import COPY_SLOT


def test_plan(context):
    game=context.get("project_kind")=="game"
    fps=context.get("fps_required",False)
    plan={
        "experience":"first_person_3d" if fps else "other_game" if game else "website",
        "rendering":"threejs" if fps else "dom",
        "requirements":["保留原始需求","实现可以操作的界面"],
        "visual_direction":"按需求组织有主次的视觉与反馈",
        "specialist_brief":context["request"],
    }
    if game:
        genre=context.get("game_genre_hint")
        plan["game_genre"]=genre
        plan["mechanics"]=context.get("base_mechanics") or _test_mechanics(genre)
    return compact(plan)


def _test_mechanics(genre):
    if genre=="tile_merge":
        return {
            "initial_state":"4×4 棋盘有两个数字块，得分为 0。",
            "actions":[{
                "input":"方向键或四个方向按钮","when":"本局仍在进行",
                "effects":["沿输入方向压缩并合并，按读取时的索引写回。","更新得分，有效移动后在空格生成新块。"],
            }],
            "invariants":["每次移动最多合并每个方块一次。","无效移动不加分也不生成新块。"],
            "end_condition":"棋盘无空位，横竖无相同邻格。",
            "restart":"重新生成棋盘并归零本局得分。",
            "examples":[
                {"setup":"一行为 [2,2,0,0]","action":"向右","expected":"生成新块前 [0,0,0,4]，加 4 分。"},
                {"setup":"一列从上到下为 [2,0,2,0]","action":"向下","expected":"生成新块前 [0,0,0,4]，加 4 分。"},
            ],
        }
    if genre in {"platformer","arcade_platformer"}:
        return {
            "initial_state":"角色在出生点，脚底贴在起跳平台顶面。",
            "actions":[{
                "input":"按右方向并跳跃","when":"角色已在平台上落地",
                "effects":["按实际速度和重力更新位置。","下降时脚底跨过平台顶面且横向重叠时落地。"],
            }],
            "invariants":["只用实际碰撞面判断落地。"],
            "end_condition":"抵达出口后完成关卡。",
            "restart":"回到本关出生点并恢复本局状态。",
            "examples":[
                {"setup":"站在出生平台左边，右前方为第一处必经平台。","action":"沿右方向起跳","expected":"下降时脚底落在第一处平台实际顶面，角色可以继续走。"},
                {"setup":"角色在第一处平台边缘。","action":"走出平台并坠落","expected":"角色回到最近的有效重生点。"},
            ],
        }
    return {
        "initial_state":"进入第一回合，进度和分数为 0。",
        "actions":[{"input":"执行主操作","when":"游戏处于进行中","effects":["更新进度","显示本次操作结果"]}],
        "invariants":["一次有效输入只结算一次。"],
        "end_condition":"完成当前目标。",
        "restart":"恢复初始回合。",
        "examples":[
            {"setup":"刚开始且进度为 0","action":"执行一次有效操作","expected":"进度增加一次。"},
            {"setup":"已有进度","action":"重新开始","expected":"进度回到 0。"},
        ],
    }


def slides_artifact(broken: bool):
    html = """<main><section data-deck-slide><h1>社区绿地</h1><p>步行可达的公共空间</p></section>
<section data-deck-slide hidden><h1>规划建议</h1><p>连接街道与公园</p></section>
<nav><button data-deck-prev disabled>上一页</button><output data-deck-position>1 / 2</output>
<button data-deck-next>下一页</button></nav></main>"""
    script = """const pages = Array.from(document.querySelectorAll('[data-deck-slide]'));
const previous = document.querySelector('[data-deck-prev]');
const next = document.querySelector('[data-deck-next]');
const position = document.querySelector('[data-deck-position]');
let index = 0;
function show(target) {
  index = Math.min(pages.length - 1, Math.max(0, target));
  pages.forEach((page, number) => { page.hidden = index !== number; });
  previous.disabled = index === 0;
  next.disabled = index === pages.length - 1;
  position.textContent = (index + 1) + ' / ' + pages.length;
}
previous.addEventListener('click', () => show(index - 1));
document.addEventListener('keydown', event => {
  if (event.key === 'ArrowLeft') show(index - 1);
  if (event.key === 'ArrowRight') show(index + 1);
  if (event.key === 'Home') show(0);
  if (event.key === 'End') show(pages.length - 1);
});
show(0);"""
    script += "\nnext.addEventListener('click', () => show(index + 1));"
    if broken:
        script += '\nthrow new Error("幻灯片启动异常");'
    return compact({
        "schema_version":"1", "title":"测试网页幻灯片", "summary":"用两页验证翻页交互。",
        "files":{"index.html":html,"styles.css":"main{padding:2rem}nav{display:flex;gap:1rem}","app.js":script},
    })


def adapted_website(starter):
    labels = {
        "editorial": {
            "site.name":"街巷 · 城市通讯",
            "story.1.title":"临河步道的空间记录", "story.1.section":"建筑",
            "story.2.title":"怎样策划一场让人愿意停留的展览", "story.2.section":"文化",
        },
        "portfolio": {
            "site.name":"林间 · 创作档案", "hero.headline":"用镜头记录城市",
            "work.1.title":"旧楼的光线", "work.1.category":"建筑",
            "work.2.title":"海岸图书馆", "work.2.category":"空间",
            "work.3.title":"窗前的色彩", "work.3.category":"视觉",
        },
        "landing": {
            "site.name":"山行 · 户外灯具", "hero.headline":"天黑之后，继续在路上。",
            "version.1.name":"随身款", "version.2.name":"营地款", "spec.label":"续航示例", "version.2.value":"14 小时",
            "faq.question":"这款产品可以购买吗？", "faq.answer":"这是概念发布页，型号和规格用于展示选型体验。",
        },
    }[starter["id"]]
    files = {
        path: COPY_SLOT.sub(lambda slot: labels.get(slot[1], "示例内容 " + slot[1]), source)
        for path, source in starter["files"].items()
    }
    return compact({"schema_version":"2", "title":labels["site.name"], "summary":"测试模型基于参考生成的页面。", "files":files})


def game_artifact(broken: bool, incomplete_replay: bool, direction: int | None = None, unmarked_resume: bool = False):
    engine = """export const goal=3;
export const initial={phase:"ready",actions:0};
export function collect(game, route="open"){
  if(game.phase!=="playing" || route==="blocked") return game;
  const actions=game.actions+1;
  return {phase:actions===goal?"won":"playing",actions};
}"""
    app = """import {useState} from "react";
import {collect,goal,initial} from "./game/engine";
import GameHud from "./components/GameHud";
export default function App(){
  const [game,setGame]=useState(initial);
  function phase(phase){setGame(current=>({...current,phase}));}
  return <main data-game-phase={game.phase} data-game-actions={game.actions} data-playtest-score={game.actions}>
    <h1>晶体航线</h1><GameHud score={game.actions} goal={goal}/>
    {game.phase==="ready"&&<button data-game-start onClick={()=>phase("playing")}>开始游戏</button>}
    {game.phase==="playing"&&<><button data-game-action="left" onClick={()=>setGame(current=>collect(current,"blocked"))}>尝试左侧航线</button>
      <button data-game-action="right" data-game-input="collect" onClick={ACTION}>收集晶体</button>
      <button data-game-pause onClick={()=>phase("paused")}>暂停</button></>}
    {game.phase==="paused"&&<button data-game-resume onClick={()=>phase("playing")}>继续</button>}
    {(game.phase==="paused"||game.phase==="won")&&<button data-game-restart onClick={()=>setGame(initial)}>重开</button>}
    {game.phase==="won"&&<p>晶体收集完成</p>}
  </main>;
}""".replace("ACTION", "()=>{}" if broken else "()=>setGame(collect)")
    if unmarked_resume:
        app=app.replace("button data-game-resume onClick", "button onClick")
    design = {
        "genre":"回合制收集","objective":"收齐三颗晶体","controls":"点击收集按钮",
        "loop":["开始一局","采集一颗晶体","收集三颗后结算"],"progression":"记录三段收集进度",
        "feedback":"HUD 更新收集进度","ending":"收齐后显示完成并可重开","art_direction":"深蓝色控制面板",
        "playtest":{"mode":"turn_based","actions":["collect"]*(2 if incomplete_replay else 3),
                    "checks":[{"label":"收集后晶体数量增加","control":"collect","signal":"score","change":"increase"}]},
    }
    if direction is not None:
        engine = engine.replace('phase:"ready",actions:0', 'phase:"ready",actions:0,position:60')
        engine = engine.replace('return {phase:actions', 'return {...game,phase:actions')
        engine += "\nexport function move(game, step){return {...game, position:game.position+step, actions:game.actions+1};}"
        app = app.replace('import {useState}', 'import {useEffect,useLayoutEffect,useRef,useState}')
        app = app.replace('import {collect,goal,initial}', 'import {collect,goal,initial,move}')
        app = app.replace('  function phase', f'''  const board=useRef(null), actor=useRef(null), root=useRef(null);
  useLayoutEffect(()=>{{
    root.current.dataset.playtestScreenX=String(actor.current.getBoundingClientRect().left-board.current.getBoundingClientRect().left);
  }},[game.position]);
  useEffect(()=>{{
    function onKey(event){{
      if(game.phase!=="playing"||!["ArrowLeft","ArrowRight"].includes(event.key)) return;
      const step=(event.key==="ArrowLeft"?-10:10)*{direction};
      setGame(current=>move(current,step));
    }}
    window.addEventListener("keydown",onKey);
    return ()=>window.removeEventListener("keydown",onKey);
  }},[game.phase]);
  function phase''').replace('<main data-game-phase', '<main ref={root} data-game-phase')
        app = app.replace('<h1>晶体航线</h1>', '<h1>晶体航线</h1><div ref={board} style={{position:"relative",height:40}}><span ref={actor} style={{position:"absolute",left:game.position}}>◆</span></div>')
        design["controls"]="方向键移动，点击按钮收集"
        design["playtest"]["checks"]= [
            {"label":"左键向左移动","key":"ArrowLeft","signal":"screen-x","change":"decrease","min_delta":5},
            {"label":"右键向右移动","key":"ArrowRight","signal":"screen-x","change":"increase","min_delta":5},
        ]
    return compact({"schema_version":"2","title":"晶体航线","summary":"收集三颗晶体并完成挑战。","files":{
        "src/game/design.json":compact(design),
        "src/game/engine.ts":engine,
        "src/components/GameHud.tsx":"export default function GameHud({score,goal}){return <p>晶体 {score} / {goal}</p>}",
        "src/App.tsx":app,
        "src/styles.css":"body{margin:0;background:#12304c;color:#fff;font:18px system-ui}main{padding:20px}button{margin:4px;padding:9px}",
    }})


def test_artifact(context,repair):
    """Fixtures are only reachable in APP_ENV=test; never a production fallback."""
    prompt=context["request"]
    if "[fail]" in prompt:
        return '{"bad":"artifact"}'
    if "[resume]" in prompt and not context.get("continuing_failed_build"):
        return '{"bad":"resume-fixture"}'
    round_number=(repair or {}).get("round",0)
    repeat_root="[repeat-root]" in prompt
    if repeat_root or ("[repair-loop]" in prompt and round_number<10):
        missing="same-module" if repeat_root else "module-"+str(round_number)
        app="\n"*round_number+f'import "./{missing}";\nexport default function App(){{return <main>测试</main>}}'
        return compact({"schema_version":"2","title":"构建修复测试","summary":"编译错误测试",
                        "files":{"src/App.tsx":app,"src/styles.css":"body{margin:0}","src/helper.ts":"export {}"}})
    if "[repair]" in prompt and not repair:
        return "invalid json"
    if context.get("slide_template"):
        if "[template-content-repair]" in prompt and not repair:
            return compact({"files":{"app.js":"翻页状态；这里仅描述实现方案"}})
        topic = re.search(r"主题[：:]\s*([^\n]+)", prompt)
        title = topic.group(1).strip()[:80] if topic else "测试幻灯片模板"
        return compact({"title":title,"summary":"测试模板内容","slides":[
            {"title":title,"description":"自定义主题","items":[]},
            {"title":"下一步","description":"","items":[{"label":"进度","detail":"待补充"}]},
        ]})
    if context["project_kind"] == "slides":
        return slides_artifact(broken="[slides-repair]" in prompt and not repair)
    if context["project_kind"] == "game" and context.get("site_format") == "react":
        game = game_artifact(broken="[game-unconfirmed]" in prompt,
                             incomplete_replay="[game-replay-repair]" in prompt and not repair,
                             direction=(1 if repair else -1) if "[game-input-repair]" in prompt else None,
                             unmarked_resume="[game-supplemental]" in prompt)
        if ("[game-repair]" in prompt or "[game-click-error]" in prompt) and not repair:
            import json
            artifact = json.loads(game)
            app = artifact["files"]["src/App.tsx"]
            if "[game-repair]" in prompt:
                app = app.replace("  return <main", '  throw new Error("启动异常");\n  return <main')
            else:
                app = app.replace("()=>setGame(collect)", '()=>{throw new Error("收集操作异常")}')
            artifact["files"]["src/App.tsx"] = app
            return compact(artifact)
        return game
    if context.get("website_starter"):
        return adapted_website(context["website_starter"])
    label="增加两次" if context.get("base_artifact") else "增加一次"
    step=2 if context.get("base_artifact") else 1
    if context.get("site_format")=="react":
        extras = ""
        if "[compat]" in prompt:
            extras = '<p>示例来自 <cite>计数器练习</cite></p>'
        if "[datalist]" in prompt:
            extras = '<label htmlFor="city">城市</label><input id="city" list="cities"/><datalist id="cities"><option value="上海"/><option value="北京"/></datalist>'
        app = '''import {useState} from "react";
import Counter from "./components/Counter";
export default function App() {
  const [count,setCount]=useState(()=>window.atoms.storage.get("count",0));
  const [status,setStatus]=useState("");
  async function add() {
    const next=count+STEP;
    setCount(next);
    window.atoms.storage.set("count",next);
    try {await window.atoms.storage.flush();setStatus("已保存");}
    catch(error) {setStatus(error.message);}
  }
  return <main><h1>计数器</h1><Counter value={count} add={add} label="LABEL"/><p id="save">{status}</p>EXTRAS</main>;
}'''.replace("STEP",str(step)).replace("LABEL",label).replace("EXTRAS",extras)
        css = "html{scroll-behavior:smooth}body{font-family:system-ui;margin:16px;color:#203a30}output{display:block;font-size:42px}"
        if "[wide-preview]" in prompt:
            css += "main{min-width:700px}"
        return compact({"schema_version":"2","title":"测试计数器","summary":"React 计数器，验证存储和版本迭代。","files":{
            "src/App.tsx":app,
            "src/styles.css":css,
            "src/components/Counter.tsx":'''export default function Counter({value,add,label}:{value:number;add:()=>void;label:string}) {
  return <><output id="count">{value}</output><button onClick={add}>{label}</button></>;
}''',
        }})
    artifact={"schema_version":"1","title":"测试计数器","summary":"测试专用计数器，验证存储和版本迭代。","files":{
        "index.html":'<main><h1>计数器</h1><output id="count">0</output><button id="add">'+label+'</button><p id="save"></p></main>',
        "styles.css":"body{font-family:system-ui;background:#f4f5f1;color:#203a30;padding:40px} main{background:white;padding:40px;border-radius:18px}output{display:block;font-size:56px}button{padding:14px;border:0;background:#2e624e;color:white;border-radius:8px}",
        "app.js":"let n=window.atoms.storage.get('count',0);const out=document.querySelector('#count');out.textContent=n;document.querySelector('#add').addEventListener('click',async()=>{n+="+str(step)+";out.textContent=n;window.atoms.storage.set('count',n);try{await window.atoms.storage.flush();document.querySelector('#save').textContent='已保存'}catch(e){document.querySelector('#save').textContent=e.message}});"
    }}
    if "[datalist]" in prompt:
        artifact["files"]["index.html"]+='<label for="city">城市</label><input id="city" list="cities"><datalist id="cities"><option value="上海"></option><option value="北京"></option></datalist>'
    if "[compat]" in prompt:
        artifact["files"]["index.html"]+='<p>示例来自 <cite>计数器练习</cite></p>'
        artifact["app.js"]=artifact["files"].pop("app.js")
    return compact(artifact)
