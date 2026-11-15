import {test, expect} from "@playwright/test";

for (const [request,genre,example] of [
  ["生成一个2048游戏，方向键和按钮都可以移动","tile_merge","[0,0,0,4]"],
  ["做一个平台跳跃游戏，玩家能跳上第一处必经平台","platformer","第一处平台实际顶面"],
]) {
  test(`游戏 ${genre} 的玩法规则和自测例子随版本保存`, async ({page})=>{
    await page.goto("/games");
    await page.getByLabel("描述应用需求").fill(request);
    await page.getByRole("button",{name:"开始创建",exact:true}).click();
    await expect(page.getByRole("button",{name:"查看版本 v1 预览",exact:true})).toBeVisible();
    const path=(await page.getByRole("link",{name:"导出源码"}).getAttribute("href"))!;
    const version=await (await page.request.get(path.replace(/\/export$/,""))).json();
    const run=await (await page.request.get("/api/v1/runs/"+version.source_run_id)).json();
    expect(run).toMatchObject({status:"succeeded",model_calls:2});
    const plan=JSON.parse(version.artifact.files["src/agent/plan.json"]);
    expect(plan.game_genre).toBe(genre);
    expect(plan.mechanics.examples[0].expected).toContain(example);
    expect(version.validation_report.task_plan.mechanics).toEqual(plan.mechanics);
    expect(version.validation_report.acceptance).toBe("startup");
  });
}

test("启动检查不会自行点击游戏控件",async({page})=>{
  await page.goto("/games");
  await page.getByLabel("描述应用需求").fill("[game-click-error] 制作一个浏览器游戏");
  await page.getByRole("button",{name:"开始创建",exact:true}).click();
  await expect(page.getByRole("button",{name:"查看版本 v1 预览",exact:true})).toBeVisible({timeout:65000});
  const path=(await page.getByRole("link",{name:"导出源码"}).getAttribute("href"))!;
  const version=await (await page.request.get(path.replace(/\/export$/,""))).json();
  const run=await (await page.request.get("/api/v1/runs/"+version.source_run_id)).json();
  expect(run).toMatchObject({status:"succeeded",model_calls:2});
  expect(version.validation_report).toMatchObject({ready:true,acceptance:"startup"});
  expect(version.validation_report.smoke).toBeUndefined();
  expect(version.validation_report.source_review).toBeUndefined();
  await expect(page.getByTestId("build-failure")).toHaveCount(0);
});

test("游戏启动抛出异常时自动修复，并交付玩法设计与工程源码", async ({page})=>{
  await page.goto("/games");
  await page.getByLabel("描述应用需求").fill("[game-repair] 制作一个收集三颗晶体的浏览器游戏");
  await page.getByRole("button",{name:"开始创建",exact:true}).click();
  const versionButton=page.getByRole("button",{name:"查看版本 v1 预览",exact:true});
  await expect(versionButton).toBeVisible();
  const path=(await page.getByRole("link",{name:"导出源码"}).getAttribute("href"))!;
  const version=await (await page.request.get(path.replace(/\/export$/,""))).json();
  const run=await (await page.request.get("/api/v1/runs/"+version.source_run_id)).json();
  expect(run.model_calls).toBe(3);
  expect(version.artifact.schema_version).toBe("2");
  expect(JSON.parse(version.artifact.files["src/game/design.json"]).loop).toHaveLength(3);
  expect(version.artifact.files).toHaveProperty(["src/game/engine.ts"]);
  expect(version.artifact.files).toHaveProperty(["src/components/GameHud.tsx"]);
  const preview=page.frameLocator('iframe[title="应用预览"]');
  await preview.getByRole("button",{name:"开始游戏",exact:true}).click();
  for(let i=0;i<3;i++) await preview.getByRole("button",{name:"收集晶体",exact:true}).click();
  await expect(preview.getByText("晶体收集完成")).toBeVisible();
  await preview.getByRole("button",{name:"重开",exact:true}).click();
  await expect(preview.getByText("晶体 0 / 3")).toBeVisible();
  await page.getByRole("button",{name:"代码",exact:true}).click();
  await page.getByRole("button",{name:"design.json",exact:true}).click();
  await expect(page.locator(".cm-content")).toContainText("收齐三颗晶体");
});

test("可操作的回合制游戏无需按指定路线通关即可交付", async ({page})=>{
  await page.goto("/games");
  await page.getByLabel("描述应用需求").fill("[game-replay-repair] 制作一个收集三颗晶体的回合制游戏");
  await page.getByRole("button",{name:"开始创建",exact:true}).click();
  await expect(page.getByRole("button",{name:"查看版本 v1 预览",exact:true})).toBeVisible();
  const path=(await page.getByRole("link",{name:"导出源码"}).getAttribute("href"))!;
  const version=await (await page.request.get(path.replace(/\/export$/,""))).json();
  const run=await (await page.request.get("/api/v1/runs/"+version.source_run_id)).json();
  expect(run.model_calls).toBe(2);
  expect(version.validation_report.acceptance).toBe("startup");
  expect(JSON.parse(version.artifact.files["src/game/design.json"]).playtest.actions).toEqual(["collect","collect"]);
});

test("游戏可操作时，缺少特定控件标记不会触发修复", async ({page})=>{
  await page.goto("/games");
  await page.getByLabel("描述应用需求").fill("[game-supplemental] 制作一个收集晶体的游戏");
  await page.getByRole("button",{name:"开始创建",exact:true}).click();
  await expect(page.getByRole("button",{name:"查看版本 v1 预览",exact:true})).toBeVisible();
  const path=(await page.getByRole("link",{name:"导出源码"}).getAttribute("href"))!;
  const version=await (await page.request.get(path.replace(/\/export$/,""))).json();
  const run=await (await page.request.get("/api/v1/runs/"+version.source_run_id)).json();
  expect(run).toMatchObject({status:"succeeded",model_calls:2,retry_of_run_id:null});
  expect(version.validation_report.acceptance).toBe("startup");
  await expect(page.getByTestId("build-failure")).toHaveCount(0);
  const preview=page.frameLocator('iframe[title="应用预览"]');
  await preview.getByRole("button",{name:"开始游戏"}).click();
  await preview.getByRole("button",{name:"暂停"}).click();
  await preview.getByRole("button",{name:"继续"}).click();
  await preview.getByRole("button",{name:"收集晶体"}).click();
  await expect(preview.getByText("晶体 1 / 3")).toBeVisible();
});

test("短测无需方向或玩法断言", async ({page})=>{
  await page.goto("/games");
  await page.getByLabel("描述应用需求").fill("[game-input-repair] 做一个左右移动并收集晶体的浏览器游戏");
  await page.getByRole("button",{name:"开始创建",exact:true}).click();
  await expect(page.getByRole("button",{name:"查看版本 v1 预览",exact:true})).toBeVisible();
  const path=(await page.getByRole("link",{name:"导出源码"}).getAttribute("href"))!;
  const version=await (await page.request.get(path.replace(/\/export$/,""))).json();
  const run=await (await page.request.get("/api/v1/runs/"+version.source_run_id)).json();
  expect(run.model_calls).toBe(2);
  expect(version.validation_report.acceptance).toBe("startup");
});

test("轨道解谜可完成三关，飞行示例可操作、收集与暂停", async ({page,browser,baseURL})=>{
  await page.goto("/games");
  await page.getByRole("button",{name:"预览轨道信使",exact:true}).click();
  const orbit=page.getByRole("dialog",{name:"轨道信使"});
  const board=orbit.getByLabel(/轨道地图/);
  const keys={U:"ArrowUp",D:"ArrowDown",L:"ArrowLeft",R:"ArrowRight"} as const;
  const routes=["RRRDDLDDLLRRUURRRRDD","DDRRRUURDDDDRRUUUU","DDDDURRUURRDDRRUU"];
  for (const [index,route] of routes.entries()){
    await orbit.getByRole("button",{name:"开始任务",exact:true}).click();
    for (const key of route) await board.press(keys[key as keyof typeof keys]);
    if(index<routes.length-1) await orbit.getByRole("button",{name:"进入下一航区",exact:true}).click();
  }
  await expect(orbit.getByText("全航区已通关")).toBeVisible();
  await orbit.getByRole("button",{name:"关闭",exact:true}).click();

  const mobile=await browser.newContext({viewport:{width:390,height:844},hasTouch:true,isMobile:true});
  try{
    const phone=await mobile.newPage();
    await phone.goto(baseURL+"/games");
    await phone.getByRole("button",{name:"竞速",exact:true}).tap();
    await phone.getByRole("button",{name:"预览潮汐穿梭",exact:true}).tap();
    const flight=phone.getByRole("dialog",{name:"潮汐穿梭"});
    await flight.getByRole("button",{name:"起飞",exact:true}).tap();
    const area=flight.getByLabel(/飞行区域/);
    await area.tap({position:{x:Math.floor((await area.boundingBox())!.width/2),y:30}});
    await expect(flight.getByText("1 / 4",{exact:true})).toBeVisible();
    await flight.getByRole("button",{name:"暂停飞行",exact:true}).tap();
    const progress=flight.getByRole("progressbar",{name:"航程进度"});
    const progressValue=await progress.getAttribute("value");
    await expect(flight.getByText("飞行暂停")).toBeVisible();
    await flight.getByRole("button",{name:"继续飞行",exact:true}).tap();
    await expect.poll(async()=>Number(await progress.getAttribute("value"))).toBeGreaterThan(Number(progressValue));
  }finally{await mobile.close();}
});
