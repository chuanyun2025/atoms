import {expect,test} from "@playwright/test";

const examples=[
  {title:"丛林突击：魂斗罗",start:undefined},
  {title:"草原跳跃：三关奇旅",start:"开始冒险"},
  {title:"霓虹赤湾 · 海岸环线竞速",start:"发车 ↗"},
  {title:"仓库突围：冷光行动",start:"开始战斗"},
];

test("四个已生成游戏排在示例最前，可隔离试玩且不触发生成",async({page})=>{
  const projectWrites:string[]=[];
  page.on("request",request=>{
    if(request.method()!=="GET"&&/\/api\/v1\/projects/.test(request.url())) projectWrites.push(request.url());
  });
  await page.goto("/games");
  const cards=page.locator(".example-card-v2");
  await expect(cards).toHaveCount(9);
  await expect(cards.locator("strong")).toHaveText([
    ...examples.map(example=>example.title),"轨道信使","潮汐穿梭","星光打砖块","星象翻牌","霓虹贪吃蛇",
  ]);
  await cards.last().scrollIntoViewIfNeeded();
  await expect.poll(()=>cards.locator("img").evaluateAll(images=>images.every(image=>(image as HTMLImageElement).naturalWidth>0))).toBe(true);
  const bounds=await cards.evaluateAll(elements=>elements.map(element=>({x:element.getBoundingClientRect().x,y:element.getBoundingClientRect().y})));
  expect(new Set(bounds.map(bound=>Math.round(bound.x))).size).toBe(3);
  expect(new Set(bounds.map(bound=>Math.round(bound.y))).size).toBe(3);
  const gallery=page.getByRole("region",{name:"游戏示例"});
  await gallery.getByRole("button",{name:"动作",exact:true}).click();
  await expect(cards).toHaveCount(2);
  await gallery.getByRole("button",{name:"射击",exact:true}).click();
  await expect(cards).toHaveCount(1);
  await gallery.getByRole("button",{name:"全部",exact:true}).click();

  for(const example of examples){
    await page.getByRole("button",{name:"预览"+example.title,exact:true}).click();
    const dialog=page.getByRole("dialog",{name:example.title,exact:true});
    const frame=dialog.frameLocator("iframe");
    await expect(dialog.locator(".preview-loading")).toHaveCount(0);
    const root=frame.locator("[data-game-phase]").first();
    if(example.start) await frame.getByRole("button",{name:example.start,exact:true}).click();
    await expect(root).toHaveAttribute("data-game-phase","playing");
    await frame.locator("canvas").first().click();
    await page.keyboard.press("d");
    await expect(dialog.locator(".preview-error")).toHaveCount(0);
    const stored=await frame.locator("body").evaluate(async()=>{
      const sdk=(window as unknown as {atoms:{storage:{get:(key:string)=>unknown;set:(key:string,value:unknown)=>void;flush:()=>Promise<void>}}}).atoms.storage;
      const previous=sdk.get("gallery-test");
      sdk.set("gallery-test",123);
      await sdk.flush();
      return {previous,next:sdk.get("gallery-test")};
    });
    expect(stored).toEqual({previous:null,next:123});
    // FPS captures the pointer while playing. Release it before using parent controls.
    await frame.locator("body").evaluate(()=>document.exitPointerLock());
    await dialog.getByRole("button",{name:"关闭",exact:true}).click();
    await expect(page.locator(".published-example-preview iframe")).toHaveCount(0);
  }
  expect(projectWrites).toEqual([]);
});
