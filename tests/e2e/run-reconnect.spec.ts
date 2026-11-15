import {test,expect} from "@playwright/test";

for(const outcome of ["success","failure"] as const){
  test(`进度流在收到第一条事件后断开，轮询仍会完成${outcome==="success"?"交付":"失败处理"}`,async({page})=>{
    let opened=false;
    await page.route("**/api/v1/runs/*/events",async route=>{
      if(opened){
        await route.abort("connectionreset");
        return;
      }
      opened=true;
      await route.fulfill({contentType:"text/event-stream",body:'id: 1\nevent: accepted\ndata: {"message":"等待生成服务"}\n\n'});
    });
    await page.goto("/games");
    await page.getByLabel("描述应用需求").fill(outcome==="success"
      ?"[slow-build] 做一个收集晶体的游戏"
      :"[slow] [fail] 测试生成校验失败");
    await page.getByRole("button",{name:"开始创建",exact:true}).click();
    const progress=page.getByRole("region",{name:"构建进度"});
    await expect(progress.getByText(/正在重新连接/)).toBeVisible();
    await expect(progress.getByRole("status").filter({hasText:"等待生成服务"})).toHaveCount(0,{timeout:12000});
    await expect(page.locator(".prompt-length")).toHaveCount(0);

    if(outcome==="success"){
      await expect(progress.getByRole("status").filter({hasText:"正在生成代码"})).toBeVisible();
      const frame=page.frameLocator('iframe[title="应用预览"]');
      await expect(page.getByRole("button",{name:"查看版本 v1 预览"})).toBeVisible({timeout:30000});
      await expect(page.getByText("临时预览 · 操作不保存")).toHaveCount(0);
      await expect(frame.getByRole("button",{name:"开始游戏"})).toBeVisible();
      await expect(page.getByRole("link",{name:"导出源码"})).toBeVisible();
    }else{
      const failure=page.getByTestId("build-failure");
      await expect(failure.getByText("生成产物格式未通过检查。")).toBeVisible({timeout:55000});
      await expect(failure.getByRole("button",{name:"继续修复"})).toBeEnabled();
    }
    await expect(progress.getByRole("status")).toHaveCount(0);
  });
}
