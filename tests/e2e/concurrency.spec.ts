import {expect, test} from "@playwright/test";

test("同一访客可并行构建三个项目，超出上限的任务在腾出名额后启动", async ({request, baseURL}) => {
  const origin = new URL(baseURL!).origin;
  const headers = {Origin:origin, "X-App-Request":"atoms"};
  const session = await request.post("/api/v1/session", {data:{},headers});
  expect(session.ok()).toBe(true);
  const auth = {...headers, "X-CSRF-Token":(await session.json()).csrf_token};
  const runs: string[] = [];

  async function submit(projectId: string, index: number) {
    return request.post(`/api/v1/projects/${projectId}/runs`, {
      headers:{...auth, "Idempotency-Key":`concurrent-run-${index}`},
      data:{prompt:index===2?"制作两页幻灯片":"[slow] 生成两页幻灯片",expected_revision:0,base_version_id:null},
    });
  }

  let firstProjectId = "";
  for (let index=0; index<4; index++) {
    const created = await request.post("/api/v1/projects", {
      headers:auth,
      data:{client_key:`concurrent-project-${index}`,kind:"slides",title:`并发演示 ${index+1}`},
    });
    expect(created.status()).toBe(201);
    const projectId = (await created.json()).id;
    if (index===0) firstProjectId=projectId;
    const accepted = await submit(projectId,index);
    expect(accepted.status()).toBe(202);
    runs.push((await accepted.json()).id);
  }

  const duplicate = await submit(firstProjectId,4);
  expect(duplicate.status()).toBe(409);
  expect((await duplicate.json()).detail.code).toBe("run_active");

  async function states() {
    return Promise.all(runs.map(async id=>{
      const response = await request.get(`/api/v1/runs/${id}`);
      expect(response.ok()).toBe(true);
      return response.json();
    }));
  }
  await expect.poll(async ()=>(await states()).map(run=>run.status), {intervals:[100],timeout:5000})
    .toEqual(["running","running","running","pending"]);
  await expect.poll(async ()=>(await states()).map(run=>run.status), {intervals:[200],timeout:15000})
    .toEqual(["succeeded","succeeded","succeeded","succeeded"]);
  const [first,second,third,fourth] = await states();
  expect(fourth.started_at).toBeGreaterThanOrEqual(third.finished_at);
  expect(fourth.started_at).toBeLessThan(Math.min(first.finished_at,second.finished_at));
  expect([first,second,third,fourth].map(run=>run.model_calls)).toEqual([1,1,1,1]);
  const wallet = await (await request.get("/api/v1/wallet")).json();
  expect(wallet).toMatchObject({available:"499.776000",held:"0.000000"});
});
