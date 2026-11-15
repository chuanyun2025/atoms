import {expect,test} from "@playwright/test";

test("停止自动修复后保留草稿，用户可以继续构建",async({page})=>{
  await page.goto("/games");
  await page.getByLabel("描述应用需求").fill("[slow] [game-repair] 制作一个可以收集三颗晶体的游戏");
  const accepted=page.waitForResponse(response=>response.url().endsWith("/runs")&&response.request().method()==="POST"&&response.status()===202);
  await page.getByRole("button",{name:"开始创建",exact:true}).click();
  const run=await (await accepted).json();
  const runPath="/api/v1/runs/"+run.id;
  const progress=page.getByRole("region",{name:"构建进度"});
  await expect(progress.getByRole("status")).toContainText("第 1/10 轮",{timeout:35000});
  const stopped=page.waitForResponse(response=>response.url().endsWith("/runs/"+run.id+"/stop"));
  await page.getByRole("button",{name:"停止构建",exact:true}).click();
  const result=await (await stopped).json();
  expect(result).toMatchObject({status:"interrupted",error_code:"USER_STOPPED",result_version_id:null});
  const card=page.getByTestId("build-failure");
  await expect(card.getByText("已停止构建")).toBeVisible();
  await expect(card.getByRole("button",{name:"继续构建"})).toBeEnabled();
  await page.getByRole("button",{name:"代码",exact:true}).click();
  await page.getByRole("button",{name:"App.tsx",exact:true}).click();
  await expect(page.locator(".cm-content")).toContainText("启动异常");
  await page.reload();
  await expect(card.getByText("已停止构建")).toBeVisible();

  const continued=page.waitForResponse(response=>response.url().endsWith("/runs")&&response.request().method()==="POST"&&response.status()===202);
  await card.getByRole("button",{name:"继续构建"}).click();
  expect(await (await continued).json()).toMatchObject({retry_of_run_id:run.id});
  await expect(page.getByRole("button",{name:"查看版本 v1 预览"})).toBeVisible();
  await expect(page.getByText("这次构建已继续并完成。")).toBeVisible();
  expect(await (await page.request.get(runPath)).json()).toMatchObject({
    status:"interrupted",model_calls:result.model_calls,result_version_id:null,
  });
});
