import {expect,test} from "@playwright/test";

const websites=["金衡财经 · 深色行情门户与资讯分析站","独立站 · 深色编辑杂志风品牌单页","拾光集 · 琥珀暖光的日用选物店"];
const decks=[
  {title:"深圳旅游规划演示文稿",pages:9},
  {title:"年度个人工作汇报 · 网页幻灯片",pages:8},
  {title:"客户运营团队 Q2 复盘",pages:4},
];

test("首页展示三个指定网站与三份完整演示，可按类型筛选和预览",async({page})=>{
  const writes:string[]=[];
  page.on("request",request=>{
    if(request.method()!=="GET"&&request.url().includes("/api/v1/projects")) writes.push(request.url());
  });
  await page.goto("/");
  const gallery=page.getByRole("region",{name:"首页作品区"});
  const cards=gallery.locator(".example-card-v2");
  await expect(cards.locator("strong")).toHaveText([...websites,...decks.map(deck=>deck.title)]);
  await cards.last().scrollIntoViewIfNeeded();
  await expect.poll(()=>cards.locator("img").evaluateAll(images=>images.every(image=>(image as HTMLImageElement).naturalWidth>0))).toBe(true);
  await expect(gallery.getByRole("button",{name:/预览(海边旅宿|未来城市|手作陶器)/})).toHaveCount(0);
  await gallery.getByRole("button",{name:"网站",exact:true}).click();
  await expect(cards).toHaveCount(3);

  for(const title of websites){
    await gallery.getByRole("button",{name:"预览"+title,exact:true}).click();
    const dialog=page.getByRole("dialog",{name:title,exact:true});
    const frame=dialog.frameLocator("iframe");
    await expect(dialog.locator(".preview-loading")).toHaveCount(0);
    await expect(frame.locator("body")).not.toBeEmpty();
    await expect(dialog.locator(".preview-error")).toHaveCount(0);
    if(title===websites[0]){
      await frame.getByLabel("搜索资讯标题").fill("科技成长");
      await expect(frame.getByRole("heading",{name:"搜索结果"})).toBeVisible();
      await frame.getByRole("button",{name:/科技成长板块估值分位梳理/}).click();
      await expect(frame.getByRole("heading",{name:/科技成长板块估值分位梳理/})).toBeVisible();
    }
    if(title===websites[1]){
      const work=frame.getByRole("button",{name:/夜航咖啡/});
      await work.click();
      await expect(work).toHaveAttribute("aria-expanded","true");
    }
    if(title===websites[2]){
      await frame.getByRole("button",{name:"查看 手冲玻璃滤杯",exact:true}).first().click();
      await frame.getByRole("button",{name:"加入购物车",exact:true}).click();
      await frame.getByRole("main").getByRole("button",{name:"查看购物车",exact:true}).click();
      await expect(frame.getByRole("heading",{name:"购物车 · 1 件",exact:true})).toBeVisible();
    }
    await dialog.getByRole("button",{name:"关闭",exact:true}).click();
  }

  await gallery.getByRole("button",{name:"幻灯片",exact:true}).click();
  await expect(cards).toHaveCount(3);
  for(const deck of decks){
    await gallery.getByRole("button",{name:"预览"+deck.title,exact:true}).click();
    const dialog=page.getByRole("dialog",{name:deck.title,exact:true});
    const frame=dialog.frameLocator("iframe");
    const position=frame.locator("[data-deck-position]");
    await expect(position).toHaveText(`1 / ${deck.pages}`);
    await frame.getByRole("button",{name:/下.*页/}).click();
    await expect(position).toHaveText(`2 / ${deck.pages}`);
    await frame.getByRole("button",{name:/下.*页/}).press("End");
    await expect(position).toHaveText(`${deck.pages} / ${deck.pages}`);
    await expect(frame.getByRole("button",{name:/下.*页/})).toBeDisabled();
    await frame.getByRole("button",{name:/上.*页/}).press("Home");
    await expect(position).toHaveText(`1 / ${deck.pages}`);
    await expect(dialog.locator(".preview-error")).toHaveCount(0);
    await dialog.getByRole("button",{name:"关闭",exact:true}).click();
  }
  expect(writes).toEqual([]);

  await page.goto("/slides");
  const slideExamples=page.getByRole("region",{name:"幻灯片示例",exact:true});
  await expect(slideExamples.locator(".example-card-v2 strong")).toHaveText(decks.map(deck=>deck.title));
  await expect(page.getByRole("region",{name:"幻灯片模板"}).getByRole("link")).toHaveCount(3);
  await slideExamples.getByRole("button",{name:"预览"+decks[1].title,exact:true}).click();
  await expect(page.getByRole("dialog").frameLocator("iframe").locator("[data-deck-position]")).toHaveText("1 / 8");
  await page.getByRole("dialog").getByRole("button",{name:"关闭",exact:true}).click();
  await page.setViewportSize({width:390,height:844});
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth)).toBe(390);
});
