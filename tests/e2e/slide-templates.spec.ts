import {expect,test} from "@playwright/test";

test("预览模板、替换提示词并生成绑定模板的项目",async({page})=>{
  const writes:string[]=[];
  page.on("request",request=>{
    if(request.method()==="POST" && /\/api\/v1\/projects(?:\/[^/]+\/runs)?$/.test(request.url())) writes.push(request.url());
  });

  await page.goto("/slides");
  const templates=page.getByRole("region",{name:"幻灯片模板"});
  await expect(templates.getByRole("link")).toHaveCount(3);
  await templates.getByRole("link",{name:"预览模板 产品发布简报"}).click();
  await expect(page).toHaveURL(/\/slides\/templates\/product-launch$/);
  const preview=page.getByRole("region",{name:"模板预览"});
  const editor=page.getByRole("form",{name:"自定义幻灯片模板"});
  await expect(preview.getByText("第 1 / 4 页",{exact:true})).toBeVisible();
  await expect.poll(()=>preview.locator(":scope > .template-slide img").evaluate(image=>(image as HTMLImageElement).naturalWidth)).toBe(720);
  await preview.getByRole("button",{name:"下一页"}).click();
  await expect(preview.getByText("第 2 / 4 页",{exact:true})).toBeVisible();
  await preview.press("End");
  await expect(preview.getByText("第 4 / 4 页",{exact:true})).toBeVisible();
  await expect(preview.getByRole("button",{name:"下一页"})).toBeDisabled();
  await preview.getByRole("button",{name:"第 3 页 三个核心体验"}).click();
  await expect(preview.getByText("第 3 / 4 页",{exact:true})).toBeVisible();
  await page.screenshot({path:"test-results/slide-template-detail.png"});

  const prompt=editor.getByLabel("把它变成你的");
  await expect(prompt).toHaveValue(/声屿桌面音箱新品发布/);
  await editor.getByRole("button",{name:"主题",exact:true}).click();
  await expect.poll(()=>prompt.evaluate(element=>{
    const input=element as HTMLTextAreaElement;
    return input.value.slice(input.selectionStart,input.selectionEnd);
  })).toBe("声屿桌面音箱新品发布");
  await page.keyboard.insertText("桌面阅读灯新品发布");
  await expect(prompt).toHaveValue(/主题：桌面阅读灯新品发布/);
  await page.reload();
  await expect(prompt).toHaveValue(/主题：桌面阅读灯新品发布/);
  await editor.getByRole("button",{name:"恢复默认"}).click();
  await expect(prompt).toHaveValue(/主题：声屿桌面音箱新品发布/);
  const revised="主题：夜读阅读灯\n听众：书店会员\n内容：从阅读场景讲起，说明可调光与使用方式。";
  await prompt.fill(revised);
  await page.setViewportSize({width:390,height:844});
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth)).toBe(390);
  await expect(editor.getByRole("button",{name:"使用模板生成"})).toBeEnabled();
  expect(writes).toHaveLength(0);

  const created=page.waitForResponse(response=>response.url().endsWith("/api/v1/projects")&&response.request().method()==="POST"&&response.status()===201);
  const started=page.waitForResponse(response=>response.url().endsWith("/runs")&&response.request().method()==="POST"&&response.status()===202);
  await editor.getByRole("button",{name:"使用模板生成"}).click();
  expect(await (await created).json()).toMatchObject({kind:"slides",slide_template_id:"product-launch"});
  expect((await started).request().postDataJSON().prompt).toBe(revised);
  await expect(page).toHaveURL(/\/projects\/[a-z0-9]+$/);
  const deck=page.frameLocator('iframe[title="应用预览"]');
  await expect(deck.locator("[data-deck-position]")).toHaveText("1 / 2");
  await expect(deck.getByRole("heading",{name:"夜读阅读灯",exact:true})).toBeVisible();
});
