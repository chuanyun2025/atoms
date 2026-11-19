import {expect,test,type Page} from "@playwright/test";
import path from "node:path";

async function fundVideoWallet(page:Page,baseURL?:string){
  const code=process.env.ATOMS_E2E_VIDEO_PASSCODE;
  if(!baseURL||!code)throw new Error("请通过 scripts/test-e2e.ps1 创建测试视频口令，或设置 ATOMS_E2E_VIDEO_PASSCODE");
  const headers={Origin:new URL(baseURL).origin,"X-App-Request":"atoms"};
  const session=await page.request.post("/api/v1/session",{data:{},headers});
  expect(session.ok()).toBe(true);
  const wallet=await page.request.post("/api/v1/wallet/passcode",{data:{code},headers:{...headers,"X-CSRF-Token":(await session.json()).csrf_token}});
  expect(wallet.ok()).toBe(true);
  return Number((await wallet.json()).available);
}

test("首帧生成原生视频，刷新后播放、下载和历史版本均可用",async({page,baseURL})=>{
  expect(await fundVideoWallet(page,baseURL)).toBeGreaterThanOrEqual(200);
  await page.goto("/video");
  const form=page.getByRole("form",{name:"视频生成设置"});
  await expect(form.getByRole("button",{name:"生成视频",exact:true})).toBeDisabled();
  await expect(form.getByRole("combobox",{name:"视频时长"})).toHaveValue("5");
  await expect(form.getByText("Vidu Q3 Pro · 540p",{exact:true})).toBeVisible();
  await form.locator('input[type="file"]').setInputFiles(path.resolve("shared/test-fixtures/first-frame.png"));
  await form.getByLabel("描述你想生成的视频").fill("微风拂过草地，镜头缓缓拉远。");
  await expect(form.getByRole("img",{name:"视频参考图片"})).toBeVisible();
  await page.screenshot({path:"test-results/vidu-video-form.png"});
  const accepted=page.waitForResponse(response=>response.url().endsWith("/runs")&&response.request().method()==="POST"&&response.status()===202);
  await form.getByRole("button",{name:"生成视频",exact:true}).click();
  const firstRun=await (await accepted).json();
  await expect(page).toHaveURL(/\/projects\/[a-f0-9]+$/);
  const player=page.getByLabel("生成的视频",{exact:true});
  await expect(player).toBeVisible();
  await expect.poll(()=>player.evaluate(element=>(element as HTMLVideoElement).readyState)).toBeGreaterThanOrEqual(2);
  await player.evaluate(element=>(element as HTMLVideoElement).play());
  await expect.poll(()=>player.evaluate(element=>(element as HTMLVideoElement).currentTime)).toBeGreaterThan(0);
  const run=await (await page.request.get("/api/v1/runs/"+firstRun.id)).json();
  expect(run).toMatchObject({status:"succeeded",model_calls:0});
  const href=await page.getByRole("link",{name:"下载视频",exact:true}).getAttribute("href");
  const file=await page.request.get(href!);
  expect(file.headers()["content-type"]).toBe("video/mp4");
  expect((await file.body()).subarray(0,32).toString()).toContain("ftyp");
  await page.reload();
  await expect(player).toBeVisible();
  await expect(page.getByRole("img",{name:"视频参考图片"})).toBeVisible();
  await form.getByLabel("描述你想生成的视频").fill("继续拉远镜头，保留柔和的光线。");
  await form.getByRole("button",{name:"生成视频",exact:true}).click();
  const history=page.getByLabel("视频版本",{exact:true});
  await expect(history.getByRole("button",{name:/^v2/})).toBeVisible();
  await history.getByRole("button",{name:/^v1/}).click();
  await expect(page.getByRole("link",{name:"下载视频",exact:true})).toHaveAttribute("href",href!);
  await page.setViewportSize({width:390,height:844});
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({path:"test-results/vidu-video-mobile.png",fullPage:true});
});

test("未配置 Vidu 时明确提示并禁止付费提交",async({page})=>{
  const paid:string[]=[];
  page.on("request",request=>{if(request.method()==="POST"&&request.url().endsWith("/runs"))paid.push(request.url())});
  await page.route("**/api/v1/capabilities",async route=>{
    const response=await route.fetch();
    await route.fulfill({response,json:{...await response.json(),video_configured:false}});
  });
  await page.goto("/video");
  await expect(page.getByRole("status")).toContainText("视频服务尚未连接");
  await expect(page.getByRole("button",{name:"生成视频",exact:true})).toBeDisabled();
  expect(paid).toEqual([]);
});

test("不上传图片也能生成 Q3 视频，每条固定扣 100 积分",async({page,baseURL})=>{
  const startingBalance=await fundVideoWallet(page,baseURL);
  await page.goto("/video");
  const form=page.getByRole("form",{name:"视频生成设置"});
  await expect(form.getByRole("status")).toContainText("请先描述");
  await expect(form).toContainText("可选，不上传也能直接生成");
  await expect(form).toContainText("100 积分");
  await form.getByLabel("描述你想生成的视频").fill("金毛在夕阳下的海边奔跑，镜头缓缓后退。");
  await expect(form.getByRole("button",{name:"生成视频",exact:true})).toBeEnabled();
  const requestPromise=page.waitForRequest(request=>request.method()==="POST"&&request.url().endsWith("/runs"));
  await form.getByRole("button",{name:"生成视频",exact:true}).click();
  const body=(await requestPromise).postDataJSON();
  expect(body.video).toEqual({duration:5,audio:true});
  await expect(page.getByLabel("生成的视频",{exact:true})).toBeVisible();
  await expect(page.getByLabel("生成的视频",{exact:true})).not.toHaveAttribute("poster",/./);
  await expect(page.getByRole("button",{name:"积分余额",exact:true}).getByTestId("credit-balance")).toHaveText(String(startingBalance-100));
  await page.getByRole("button",{name:"积分余额",exact:true}).click();
  await expect(page.getByRole("dialog")).toContainText("视频生成消费");
  await expect(page.getByRole("dialog")).toContainText("-100");
  await page.screenshot({path:"test-results/vidu-text-video-credits.png"});
});

test("参考图片可以移除，费用和积分不足原因明确可见",async({page})=>{
  const paid:string[]=[];
  page.on("request",request=>{if(request.method()==="POST"&&request.url().endsWith("/runs"))paid.push(request.url())});
  await page.goto("/video");
  const form=page.getByRole("form",{name:"视频生成设置"});
  await form.getByLabel("描述你想生成的视频").fill("星空下的海边，海浪轻轻涌动。");
  await form.locator('input[type="file"]').setInputFiles(path.resolve("shared/test-fixtures/first-frame.png"));
  await expect(form.getByRole("img",{name:"视频参考图片"})).toBeVisible();
  await form.getByRole("button",{name:"移除图片，使用文字生成"}).click();
  await expect(form.getByRole("img",{name:"视频参考图片",exact:true})).toHaveCount(0);
  await expect(form.getByRole("status")).toContainText("可用积分不足");
  await expect(form.getByRole("button",{name:"生成视频",exact:true})).toBeDisabled();
  await form.getByRole("combobox",{name:"视频时长"}).selectOption("1");
  await expect(form).toContainText("100 积分");
  await expect(form.getByRole("status")).toContainText("生成一条视频需要 100 积分");
  expect(paid).toEqual([]);
});
