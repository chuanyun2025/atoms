import {test,expect} from "@playwright/test";

test("发布、匿名打开、独立存档、更新、回滚和下架",async({page,browser})=>{
  await page.goto("/");
  await page.getByLabel("描述应用需求").fill("创建一个可以保存数据的计数器");
  await page.getByRole("button",{name:"开始创建",exact:true}).click();
  const editor=page.frameLocator('iframe[title="应用预览"]');
  await editor.getByRole("button",{name:"增加一次"}).click();
  await expect(editor.locator("#save")).toHaveText("已保存");
  await page.getByRole("button",{name:"发布",exact:true}).click();
  const dialog=page.getByRole("dialog",{name:"发布作品"});
  await dialog.getByRole("button",{name:"发布 v1",exact:true}).click();
  await expect(dialog.getByText("已发布 v1")).toBeVisible();
  const link=await dialog.getByLabel("公开链接").inputValue();
  const guest=await browser.newContext();
  try{
    const published=await guest.newPage();
    await published.goto(link);
    const work=published.frameLocator('iframe[title="应用预览"]');
    await expect(work.locator("#count")).toHaveText("0");
    expect(await guest.cookies()).toEqual([]);
    await work.getByRole("button",{name:"增加一次"}).click();
    await expect(work.locator("#save")).toHaveText("已保存");
    await published.reload();
    await expect(work.locator("#count")).toHaveText("1");
    expect(await guest.cookies()).toEqual([]);
    await dialog.getByRole("button",{name:"关闭"}).click();
    await page.getByLabel("描述需求或修改").fill("把每次增加改成加二");
    await page.getByRole("button",{name:"提交需求"}).click();
    await expect(page.getByRole("button",{name:"查看版本 v2 预览"})).toBeVisible();
    await published.reload();
    await expect(work.getByRole("button",{name:"增加一次"})).toBeVisible();
    await page.getByRole("button",{name:"发布",exact:true}).click();
    await dialog.getByRole("button",{name:"更新发布到 v2"}).click();
    await expect(dialog.getByText("已发布 v2")).toBeVisible();
    await expect(dialog.getByLabel("公开链接")).toHaveValue(link);
    await published.reload();
    await expect(work.getByRole("button",{name:"增加两次"})).toBeVisible();
    await dialog.getByRole("button",{name:"回滚到 v1"}).click();
    await dialog.getByRole("button",{name:"确认回滚"}).click();
    await expect(dialog.getByText("已发布 v1")).toBeVisible();
    await published.reload();
    await expect(work.getByRole("button",{name:"增加一次"})).toBeVisible();
    await dialog.getByRole("button",{name:"下架",exact:true}).click();
    await dialog.getByRole("button",{name:"确认下架"}).click();
    await expect(dialog.getByLabel("公开链接")).toHaveCount(0);
    await published.reload();
    await expect(published.getByRole("heading",{name:"这个作品已下架"})).toBeVisible();
    await dialog.getByRole("button",{name:"关闭"}).click();
    await expect(editor.locator("#count")).toHaveText("1");
  }finally{
    await guest.close();
  }
});
