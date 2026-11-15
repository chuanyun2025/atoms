import {test,expect} from "@playwright/test";

test("模板收到实现说明后改为请求逐页内容，并交付可翻页演示",async({page})=>{
  await page.goto("/slides/templates/quarterly-review");
  await page.getByLabel("把它变成你的").fill("[template-content-repair]\n主题：客户运营 Q2 复盘");
  const accepted=page.waitForResponse(r=>r.url().endsWith("/runs")&&r.request().method()==="POST"&&r.status()===202);
  await page.getByRole("button",{name:"使用模板生成"}).click();
  const run=await (await accepted).json();
  await expect(page.getByRole("button",{name:"查看版本 v1 预览"})).toBeVisible();
  expect(await (await page.request.get("/api/v1/runs/"+run.id)).json()).toMatchObject({status:"succeeded",model_calls:2});
  const deck=page.frameLocator('iframe[title="应用预览"]');
  await expect(deck.getByRole("heading",{name:"客户运营 Q2 复盘",exact:true})).toBeVisible();
  await deck.getByRole("button",{name:"下一页"}).click();
  await expect(deck.locator("[data-deck-position]")).toHaveText("2 / 2");
  await expect(deck.getByText("待补充", {exact:true})).toBeVisible();
  await expect(page.getByTestId("build-failure")).toHaveCount(0);
});

test("幻灯片启动异常时修复一次",async({page})=>{
  await page.goto("/slides");
  await page.getByLabel("描述应用需求").fill("[slides-repair] 制作一套两页的社区绿地幻灯片");
  const accepted=page.waitForResponse(r=>r.url().endsWith("/runs")&&r.request().method()==="POST"&&r.status()===202);
  await page.getByRole("button",{name:"开始创建",exact:true}).click();
  const run=await (await accepted).json();
  await expect(page.getByRole("button",{name:"查看版本 v1 预览"})).toBeVisible();
  const completed=await page.request.get("/api/v1/runs/"+run.id);
  expect(await completed.json()).toMatchObject({status:"succeeded",model_calls:2});
  const deck=page.frameLocator('iframe[title="应用预览"]');
  await expect(deck.locator("[data-deck-position]")).toHaveText("1 / 2");
  await deck.getByRole("button",{name:"下一页"}).click();
  await expect(deck.locator("[data-deck-position]")).toHaveText("2 / 2");
  await expect(page.getByTestId("build-failure")).toHaveCount(0);
});

test("标准 cite 标签自动兼容，首次生成直接交付",async({page})=>{
  await page.goto("/");
  await page.getByLabel("描述应用需求").fill("[compat] 做一个显示示例来源的计数器");
  await page.getByRole("button",{name:"开始创建",exact:true}).click();
  const preview=page.frameLocator('iframe[title="应用预览"]');
  await expect(preview.locator("cite")).toHaveText("计数器练习");
  await preview.getByRole("button",{name:"增加一次"}).click();
  await expect(preview.locator("#count")).toHaveText("1");
  await expect(preview.locator("#save")).toHaveText("已保存");
  await expect(page.getByTestId("build-failure")).toHaveCount(0);
  await page.getByRole("button",{name:"积分余额",exact:true}).filter({visible:true}).click();
  await expect(page.getByTestId("wallet-available")).toHaveText("499.888000");
});

test("不同根因可以修复到第十轮并在原任务交付",async({page})=>{
  await page.goto("/");
  await page.getByLabel("描述应用需求").fill("[repair-loop] 做一个计数网站");
  const accepted=page.waitForResponse(r=>r.url().endsWith("/runs")&&r.request().method()==="POST"&&r.status()===202);
  await page.getByRole("button",{name:"开始创建",exact:true}).click();
  const run=await (await accepted).json();
  await expect(page.getByRole("region",{name:"构建进度"})).toContainText("第 1/10 轮");
  await expect(page.getByRole("button",{name:"查看版本 v1 预览"})).toBeVisible();
  const result=await (await page.request.get("/api/v1/runs/"+run.id)).json();
  expect(result).toMatchObject({status:"succeeded",model_calls:12,retry_of_run_id:null});
  await expect(page.getByTestId("build-failure")).toHaveCount(0);
  await expect(page.frameLocator('iframe[title="应用预览"]').getByRole("button",{name:"增加一次"})).toBeVisible();
});

test("同一导入错误换了行号也在两次自动修复后停止",async({page})=>{
  await page.goto("/");
  await page.getByLabel("描述应用需求").fill("[repeat-root] 做一个计数网站");
  const accepted=page.waitForResponse(r=>r.url().endsWith("/runs")&&r.request().method()==="POST"&&r.status()===202);
  await page.getByRole("button",{name:"开始创建",exact:true}).click();
  const run=await (await accepted).json();
  const failure=page.getByTestId("build-failure");
  await expect(failure.getByText("代码编译未通过。")).toBeVisible();
  await failure.getByText("查看问题详情").click();
  await expect(failure.locator("pre")).toContainText("同一问题尝试修复 2 次后仍未通过");
  await expect(failure.locator("pre")).toContainText("src/App.tsx:3:");
  await expect(failure.locator("pre")).toContainText("./same-module");
  await expect(failure.getByRole("button",{name:"继续修复"})).toBeEnabled();
  const result=await (await page.request.get("/api/v1/runs/"+run.id)).json();
  expect(result).toMatchObject({status:"failed",model_calls:4,error_code:"COMPILE_IMPORT"});
  const progress=page.getByRole("region",{name:"构建进度"});
  await progress.getByText("构建记录", {exact:true}).click();
  await expect(progress.getByText("修复编译错误（第 2/10 轮）")).toBeVisible();
});

test("失败后保留内容、一键继续修复、原生 datalist 与积分结算",async({page})=>{
  await page.goto("/");
  await page.getByLabel("描述应用需求").fill("[resume] [datalist] 做一个支持选择城市的计数器");
  const firstAccepted=page.waitForResponse(r=>r.url().endsWith("/runs")&&r.request().method()==="POST"&&r.status()===202);
  await page.getByRole("button",{name:"开始创建",exact:true}).click();
  const firstRun=await (await firstAccepted).json();
  const card=page.getByTestId("build-failure");
  await expect(card.getByText("这次还没生成可用版本",{exact:true})).toBeVisible();
  await expect(card.getByText("生成产物格式未通过检查。",{exact:true})).toBeVisible();
  await expect(card.locator("pre")).toBeHidden();
  expect(await (await page.request.get("/api/v1/runs/"+firstRun.id)).json()).toMatchObject({status:"failed",model_calls:4});
  await page.reload();
  await expect(card.getByRole("button",{name:"继续修复",exact:true})).toBeEnabled();
  await page.getByRole("button",{name:"积分余额",exact:true}).filter({visible:true}).click();
  await expect(page.getByTestId("wallet-available")).toHaveText("499.776000");
  await page.getByRole("button",{name:"关闭",exact:true}).click();
  await page.screenshot({path:"test-results/recoverable-failure.png",fullPage:true});
  const accepted=page.waitForResponse(r=>r.url().endsWith("/runs")&&r.request().method()==="POST"&&r.status()===202);
  await card.getByRole("button",{name:"继续修复",exact:true}).click();
  const run=await (await accepted).json();
  expect(run.retry_of_run_id).toBeTruthy();
  const preview=page.frameLocator('iframe[title="应用预览"]');
  await expect(preview.getByRole("button",{name:"增加一次"})).toBeVisible();
  await expect(card).toHaveCount(0);
  await expect(page.getByText("这次构建已修复。",{exact:true})).toBeVisible();
  await expect(preview.getByLabel("城市")).toHaveAttribute("list","cities");
  await expect(preview.locator("#cities option")).toHaveCount(2);
  await preview.getByLabel("城市").fill("上海");
  await preview.getByRole("button",{name:"增加一次"}).click();
  await expect(preview.locator("#save")).toHaveText("已保存");
  await page.getByRole("button",{name:"积分余额",exact:true}).filter({visible:true}).click();
  await expect(page.getByTestId("wallet-available")).toHaveText("499.664000");
  await page.getByRole("button",{name:"关闭",exact:true}).click();
  await page.screenshot({path:"test-results/repaired-application.png",fullPage:true});
});
