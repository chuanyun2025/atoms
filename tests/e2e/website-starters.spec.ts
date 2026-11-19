import {test, expect, type Page} from "@playwright/test";

async function createWebsite(page: Page, prompt: string) {
  await page.goto("/");
  await page.getByLabel("描述应用需求").fill(prompt);
  await page.getByRole("button", {name:"开始创建",exact:true}).click();
  await expect(page.getByRole("button", {name:"查看版本 v1 预览"})).toBeVisible();
  return page.frameLocator('iframe[title="应用预览"]');
}

test("一句话资讯网站经过模型改写，保留搜索与收藏交互", async ({page}) => {
  const preview = await createWebsite(page, "生成一个新闻网站");
  await expect(preview.getByRole("button", {name:/街巷/})).toBeVisible();
  await page.getByRole("button", {name:"积分余额",exact:true}).filter({visible:true}).click();
  await expect(page.getByTestId("wallet-available")).toHaveText("48");
  await page.getByRole("button", {name:"关闭",exact:true}).click();
  await expect(preview.getByText("示例内容", {exact:true})).toBeVisible();
  await expect(preview.getByRole("heading", {name:"发布速览"})).toBeVisible();
  await page.screenshot({path:"test-results/website-editorial.png"});
  await preview.getByLabel("搜索资讯").fill("展览");
  await expect(preview.getByRole("heading", {name:"搜索结果"})).toBeVisible();
  await preview.getByRole("button", {name:"怎样策划一场让人愿意停留的展览"}).click();
  await preview.getByRole("button", {name:"收藏此条"}).click();
  await expect(preview.getByRole("button", {name:"取消收藏"})).toBeVisible();
  await page.reload();
  await preview.getByRole("button", {name:"收藏 1",exact:true}).click();
  await expect(preview.getByRole("button", {name:"怎样策划一场让人愿意停留的展览"})).toBeVisible();
});

test("一句话作品集保留分类和详情，采用新主题", async ({page}) => {
  const preview = await createWebsite(page, "创建一个个人作品集");
  await expect(preview.getByRole("heading", {name:"精选作品"})).toBeVisible();
  await expect(preview.getByRole("heading", {name:/记录城市/})).toBeVisible();
  await expect(preview.getByRole("img")).toHaveCount(0);
  await page.screenshot({path:"test-results/website-portfolio.png"});
  await preview.getByRole("button", {name:"空间",exact:true}).click();
  await expect(preview.getByRole("button", {name:/旧楼的光线/})).toHaveCount(0);
  await preview.getByRole("button", {name:/海岸图书馆/}).click();
  await expect(preview.getByRole("heading", {name:"海岸图书馆"})).toBeVisible();
  await preview.getByRole("button", {name:"返回作品",exact:false}).click();
  await expect(preview.getByRole("heading", {name:"精选作品"})).toBeVisible();
});

test("一句话产品发布页生成新首屏并支持型号比较和 FAQ", async ({page}) => {
  const preview = await createWebsite(page, "创建一个产品发布页");
  await expect(preview.getByRole("heading", {name:"天黑之后，继续在路上。"})).toBeVisible();
  await page.screenshot({path:"test-results/website-landing.png"});
  await preview.getByRole("button", {name:"营地款"}).click();
  await expect(preview.getByText("14 小时", {exact:true})).toBeVisible();
  await preview.getByText("这款产品可以购买吗？", {exact:true}).click();
  await expect(preview.getByText(/这是概念发布页/)).toBeVisible();
});
