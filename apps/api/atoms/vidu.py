"""Vidu Q3 native video API. Paid submissions are never blindly retried."""
import asyncio
import re

import httpx

from .model import ModelError

TASK_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
STATES = {"created","queueing","processing","success","failed"}


class ViduClient:
    def __init__(self, api_key, base_url="https://api.vidu.cn", *, transport=None):
        self.http = httpx.AsyncClient(base_url=base_url.rstrip("/"),
            headers={"Authorization":"Token "+api_key,"Content-Type":"application/json"},
            timeout=httpx.Timeout(60,connect=15),follow_redirects=False,transport=transport)

    async def __aenter__(self):
        return self

    async def __aexit__(self,*args):
        await self.http.aclose()

    @staticmethod
    def parse(response, *, submitting=False):
        if not response.is_success:
            messages={401:"视频服务配置异常，请联系管理员",403:"视频服务暂不可用，请联系管理员",
                      402:"视频服务额度不足，请联系管理员",429:"视频服务繁忙，请稍后重试"}
            uncertain=submitting and response.status_code>=500
            raise ModelError("VIDU_SUBMISSION_UNCERTAIN" if uncertain else "VIDU_REQUEST_FAILED",
                "Vidu 暂未确认提交结果，请先核对供应商任务，避免重复生成" if uncertain else messages.get(response.status_code,"Vidu 未能完成请求，请稍后重试"),uncertain=uncertain)
        try:
            value=response.json()
            if not isinstance(value,dict):
                raise ValueError()
            return value
        except (ValueError,TypeError):
            raise ModelError("VIDU_INVALID_RESPONSE","Vidu 返回内容暂不可用，请稍后查询",uncertain=submitting) from None

    async def create(self, *, image, prompt, model, resolution, duration, audio, payload):
        return await self._submit("/ent/v2/img2video",{"model":model,"images":[image],"prompt":prompt,
            "is_rec":False,"duration":duration,"resolution":resolution,"audio":bool(audio),"off_peak":False,"payload":payload})

    async def create_text(self, *, prompt, model, resolution, duration, audio, payload):
        return await self._submit("/ent/v2/text2video",{"model":model,"prompt":prompt,
            "aspect_ratio":"16:9","duration":duration,"resolution":resolution,"audio":bool(audio),"off_peak":False,"payload":payload})

    async def _submit(self,endpoint,body):
        for attempt in range(3):
            try:
                response=await self.http.post(endpoint,json=body)
            except httpx.HTTPError:
                raise ModelError("VIDU_SUBMISSION_UNCERTAIN","提交结果待核对，暂不重复扣费，请联系管理员",uncertain=True) from None
            if response.status_code==429 and attempt<2:
                await asyncio.sleep(2**attempt)
                continue
            value=self.parse(response,submitting=True)
            task_id=value.get("task_id")
            if not isinstance(task_id,str) or not TASK_ID.fullmatch(task_id):
                raise ModelError("VIDU_SUBMISSION_UNCERTAIN","生成请求的结果待核对，请联系管理员",uncertain=True)
            return task_id

    async def query(self,task_id):
        if not TASK_ID.fullmatch(task_id):
            raise ModelError("VIDU_INVALID_TASK","视频任务编号无效")
        try:
            response=await self.http.get("/ent/v2/tasks/"+task_id+"/creations")
        except httpx.HTTPError:
            raise ModelError("VIDU_POLL_RETRY","视频正在生成，稍后继续查询") from None
        if response.status_code==429 or response.status_code>=500:
            raise ModelError("VIDU_POLL_RETRY","视频正在生成，稍后继续查询")
        value=self.parse(response)
        if value.get("state") not in STATES:
            raise ModelError("VIDU_INVALID_RESPONSE","Vidu 暂未返回任务状态，请稍后继续查询")
        return value
