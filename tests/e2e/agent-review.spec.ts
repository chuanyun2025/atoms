import {test,expect} from "@playwright/test";

test("网站通过运行检查即可交付，窄屏布局建议不触发修复",async({page})=>{
  await page.goto("/");
  await page.getByLabel("描述应用需求").fill("[wide-preview] 做一个支持计数保存的网站");
  await page.getByRole("button",{name:"开始创建",exact:true}).click();
  await expect(page.getByRole("button",{name:"查看版本 v1 预览",exact:true})).toBeVisible();
  const path=(await page.getByRole("link",{name:"导出源码"}).getAttribute("href"))!.replace(/\/export$/,"");
  const version=await(await page.request.get(path)).json();
  const run=await(await page.request.get("/api/v1/runs/"+version.source_run_id)).json();
  expect(run.model_calls).toBe(2);
  expect(version.validation_report.ready).toBe(true);
  expect(version.validation_report.acceptance).toBe("startup");
  expect(version.validation_report.mobile_overflow_px).toBeUndefined();
  expect(version.validation_report.agent_review).toBeUndefined();
  expect(JSON.parse(version.artifact.files["src/agent/plan.json"]).requirements.length).toBeGreaterThan(1);
});

test("FPS 项目通过启动检查后交付",async({page})=>{
  await page.goto("/games");
  await page.getByLabel("描述应用需求").fill("生成一个FPS枪战游戏");
  const accepted=page.waitForResponse(response=>response.url().endsWith("/runs") && response.status()===202);
  await page.getByRole("button",{name:"开始创建",exact:true}).click();
  const run=await (await accepted).json();
  await expect(page.getByRole("button",{name:"查看版本 v1 预览",exact:true})).toBeVisible();
  const state=await (await page.request.get("/api/v1/runs/"+run.id)).json();
  expect(state).toMatchObject({status:"succeeded",model_calls:2});
});

test("赛车先检索，并使用启动检查",async({page})=>{
  await page.goto("/games");
  await page.getByLabel("描述应用需求").fill("生成一个赛车游戏");
  const accepted=page.waitForResponse(response=>response.url().endsWith("/runs") && response.status()===202);
  await page.getByRole("button",{name:"开始创建",exact:true}).click();
  const run=await(await accepted).json();
  await expect(page.getByRole("button",{name:"查看版本 v1 预览",exact:true})).toBeVisible();
  const state=await(await page.request.get("/api/v1/runs/"+run.id)).json();
  expect(state).toMatchObject({status:"succeeded",model_calls:2});
  const events=await(await page.request.get("/api/v1/runs/"+run.id+"/events")).text();
  expect(events).toContain("event: researching");
  expect(events.indexOf("event: researching")).toBeLessThan(events.indexOf("event: planning"));
});
