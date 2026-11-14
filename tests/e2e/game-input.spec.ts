import {test,expect} from "@playwright/test";
import {checkGame} from "../../apps/validator/src/game-check";
import {checkInputs} from "../../apps/validator/src/input-checks";
import {readGamePlaytest,runGamePlaytest} from "../../apps/validator/src/game-delivery";
import {smokeGame} from "../../apps/validator/src/game-smoke";

test("通用可玩性检查点击当前目标，不读取固定目标或得分断言",async({page})=>{
  await page.setContent(`<main data-game-phase="playing" data-game-actions="左移 右移 射击 跳跃">
    <button data-game-input="slot-1">位置 1</button>
    <button data-game-input="slot-2">位置 2</button>
    <output>准备中</output>
  </main><script>
    const target=document.querySelector('[data-game-input="slot-2"]');
    setTimeout(()=>{target.dataset.gameActive='true'},400);
    target.onclick=()=>{if(target.dataset.gameActive==='true')document.querySelector('output').textContent='已操作'};
  </script>`);
  const report=await smokeGame(page.mainFrame(),[{label:"固定位置",control:"slot-1",hold_ms:0,signal:"score",change:"increase",min_delta:999}],false);
  expect(report).toMatchObject({core_playable:true,input:"button"});
  expect(report.visible_feedback).toContain("已操作");
});

test("画面持续变化但玩家输入没有响应时，通用验收失败",async({page})=>{
  await page.setContent(`<main data-game-phase="playing" data-game-actions="0">
    <button>操作</button><output>0秒</output>
  </main><script>
    let elapsed=0;
    setInterval(()=>{document.querySelector('output').textContent=String(++elapsed)+'秒'},50);
  </script>`);
  await expect(smokeGame(page.mainFrame(),[],false)).rejects.toThrow(/未观察到/);
});

test("暂停弹层和 HUD 都有继续按钮时，试玩点击未被遮挡的按钮",async({page})=>{
  await page.setContent(`<main data-game-phase="playing" data-game-actions="0" data-playtest-score="0">
    <button data-game-input="collect">收集</button><button data-game-pause>暂停</button>
    <button data-game-resume hidden>HUD 继续</button>
    <div id="overlay" hidden style="position:fixed;inset:0;background:white">
      <button data-game-resume>弹层继续</button><button data-game-restart>重开</button>
    </div>
  </main><script>
    const game=document.querySelector('main'),overlay=document.querySelector('#overlay');
    const pause=document.querySelector('[data-game-pause]'), resumes=[...document.querySelectorAll('[data-game-resume]')];
    function phase(next){
      game.dataset.gamePhase=next;
      pause.hidden=next==='paused';overlay.hidden=next!=='paused';resumes[0].hidden=next!=='paused';
    }
    document.querySelector('[data-game-input]').onclick=()=>{
      game.dataset.gameActions='1';game.dataset.playtestScore='1';
    };
    pause.onclick=()=>phase('paused');
    resumes[1].onclick=()=>phase('playing');
    document.querySelector('[data-game-restart]').onclick=()=>{game.dataset.gameActions='0';phase('playing')};
  </script>`);
  const report=await checkGame(page.mainFrame(),[],800,false,[
    {label:"收集后得分",control:"collect",hold_ms:0,signal:"score",change:"increase",min_delta:1},
  ]);
  expect(report.lifecycle).toEqual({start:true,pause:true,resume:true,restart:true});
  expect(report.supplemental_failures).toEqual([]);
});

test("直接开局的开放玩法按实际主操作验收，无需暂停或结算",async({page})=>{
  await page.setContent(`<main data-game-phase="playing" data-game-actions="0" data-playtest-plants="0">
    <button data-game-input="plant">种植</button><output>尚未种植</output>
  </main><script>
    const game=document.querySelector('main');
    document.querySelector('button').onclick=()=>{
      game.dataset.gameActions='1';game.dataset.playtestPlants='1';
      document.querySelector('output').textContent='已种植';
    };
  </script>`);
  const result=await checkGame(page.mainFrame(),[],800,false,[
    {label:"种植后出现作物",control:"plant",hold_ms:0,signal:"plants",change:"increase",min_delta:1},
  ]);
  expect(result.lifecycle).toEqual({start:true});
  expect(result.visible_feedback).toContain("已种植");
});

test("画面按钮在按住期间验证，短点击无法触发同一效果",async({page})=>{
  await page.setContent(`<main data-game-phase="playing" data-playtest-height="0">
    <button data-game-input="lift">上升</button>
    <span id="actor" style="position:absolute;top:100px">◆</span>
  </main><script>
    const game=document.querySelector('main'),button=document.querySelector('button'),actor=document.querySelector('#actor');
    let timer;
    function height(value){
      actor.style.top=(100-value)+'px';
      game.dataset.playtestHeight=String(100-actor.offsetTop);
    }
    button.onpointerdown=()=>{timer=setTimeout(()=>height(32),120)};
    button.onpointerup=()=>{clearTimeout(timer);height(0)};
  </script>`);
  const check={label:"按住上升键后角色抬升",control:"lift",hold_ms:0,signal:"height",change:"increase" as const,min_delta:8};
  await expect(checkInputs(page.mainFrame(),[check])).rejects.toThrow(/从 0 变为 0/);
  const evidence=await checkInputs(page.mainFrame(),[{...check,hold_ms:250}]);
  expect(evidence).toMatchObject([{before:"0",after:"32"}]);
  await expect(page.locator("main")).toHaveAttribute("data-playtest-height","0");
});

test("桌面赛车用原生方向键驾驶，手机按钮可以隐藏", async ({page})=>{
  await page.setContent('<iframe sandbox="allow-scripts" style="width:1000px;height:600px"></iframe>');
  await page.locator("iframe").evaluate((iframe:HTMLIFrameElement)=>{
    iframe.srcdoc=`<!doctype html><style>@media(min-width:720px){[data-game-action]{display:none}}</style>
    <main data-game-phase="ready" data-game-actions="0">
      <output>车速 0</output><button data-game-action="primary">油门</button>
      <button data-game-start>开始</button><button data-game-pause>暂停</button>
      <button data-game-resume>继续</button><button data-game-restart>重开</button>
    </main><script>
      const game=document.querySelector('main'), speed=document.querySelector('output');
      let velocity=0, accelerating=false;
      const controls={ready:['start'],playing:['pause'],paused:['resume','restart']};
      function phase(value){
        game.dataset.gamePhase=value;
        accelerating=false;
        for(const name of ['start','pause','resume','restart']) {
          document.querySelector('[data-game-'+name+']').hidden=!controls[value].includes(name);
        }
      }
      document.querySelector('[data-game-start]').onclick=()=>phase('playing');
      document.querySelector('[data-game-pause]').onclick=()=>phase('paused');
      document.querySelector('[data-game-resume]').onclick=()=>phase('playing');
      document.querySelector('[data-game-restart]').onclick=()=>{
        velocity=0;speed.textContent='车速 0';game.dataset.gameActions='0';phase('ready');
      };
      window.addEventListener('keydown',event=>{if(event.key==='ArrowUp') accelerating=true;});
      window.addEventListener('keyup',event=>{if(event.key==='ArrowUp') accelerating=false;});
      setInterval(()=>{
        if(game.dataset.gamePhase!=='playing'||!accelerating)return;
        velocity++;speed.textContent='车速 '+velocity;
        game.dataset.gameActions=String(Number(game.dataset.gameActions)+1);
      },25);
      phase('ready');
    </script>`;
  });
  const frame=page.frames().find(value=>value.parentFrame())!;
  await frame.locator("[data-game-start]").waitFor();
  await expect(frame.locator("[data-game-action]")).toBeHidden();
  const evidence=await checkGame(frame,[]);
  expect(evidence.control).toBe("ArrowUp");
  expect(evidence.visible_feedback).toMatch(/车速 [1-9]/);
});

test("FPS 试玩释放鼠标锁定后通过真实点击操作 HUD",async({page})=>{
  await page.goto("about:blank");
  await page.setContent('<iframe sandbox="allow-scripts allow-pointer-lock" style="width:900px;height:600px"></iframe>');
  await page.locator("iframe").evaluate((iframe:HTMLIFrameElement)=>{
    iframe.srcdoc=`<!doctype html><div data-game-phase="ready" data-game-actions="0">
      <canvas tabindex="0" width="600" height="300"></canvas>
      <button data-game-start>开始</button>
      <button data-fps-fire data-game-action="primary">射击</button>
      <button data-game-pause>暂停</button>
      <button data-game-resume>继续</button>
      <button data-game-restart>重开</button>
    </div><script>
      const game=document.querySelector('[data-game-phase]');
      const button=name=>document.querySelector('[data-game-'+name+']');
      function phase(value){
        game.dataset.gamePhase=value;
        for(const name of ['start','pause','resume','restart'])button(name).hidden=
          !({ready:['start'],playing:['pause'],paused:['resume','restart']}[value]||[]).includes(name);
      }
      button('start').onclick=async()=>{
        await document.querySelector('canvas').requestPointerLock();
        game.dataset.lockSeen=String(Boolean(document.pointerLockElement));
        phase('playing');
      };
      document.querySelector('[data-fps-fire]').onclick=()=>{
        game.dataset.gameActions=String(Number(game.dataset.gameActions)+1);
        game.dataset.fired='true';
      };
      button('pause').onclick=()=>phase('paused');
      button('resume').onclick=()=>phase('playing');
      button('restart').onclick=()=>{game.dataset.gameActions='0';phase('ready')};
      phase('ready');
    </script>`;
  });
  const frame=page.frames().find(value=>value.parentFrame())!;
  await frame.locator("[data-game-start]").waitFor();
  await checkGame(frame,[],2500,true);
  await expect(frame.locator("[data-game-phase]")).toHaveAttribute("data-lock-seen","true");
  await expect(frame.locator("[data-game-phase]")).toHaveAttribute("data-fired","true");
  expect(await frame.evaluate(()=>Boolean(document.pointerLockElement))).toBe(false);
});

test("连续试玩要求实际状态变化，支持棋盘序列并识别自行变化的计时",async({page})=>{
  const script={checks:[
    {label:"移动后棋盘改变",key:"ArrowRight",signal:"board",change:"changed"},
    {label:"继续移动后棋盘改变",key:"ArrowLeft",signal:"board",change:"changed"},
  ]};
  const checks=readGamePlaytest({"src/game/playtest.json":JSON.stringify(script)},true)!;
  await page.setContent(`<main data-game-phase="playing" data-playtest-board="0,2,0,0" data-playtest-clock="0"><output>棋盘</output></main>
    <script>
      const board = document.querySelector("main");
      window.addEventListener("keydown", event=>{
        if (event.key==="ArrowRight") board.dataset.playtestBoard="0,0,0,2";
        if (event.key==="ArrowLeft") board.dataset.playtestBoard="2,0,0,0";
      });
      setInterval(()=>board.dataset.playtestClock=String(Number(board.dataset.playtestClock)+1),25);
    </script>`);
  const report=await runGamePlaytest(page.mainFrame(),checks);
  expect(report.steps).toMatchObject([{after:"0,0,0,2"},{before:"0,0,0,2",after:"2,0,0,0"}]);
  await expect(runGamePlaytest(page.mainFrame(),checks.map(check=>({...check,signal:"clock"}))))
    .rejects.toThrow(/在输入前已自行变化/);
});
