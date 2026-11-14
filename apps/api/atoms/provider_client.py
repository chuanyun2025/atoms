"""Stable internal API for text generation and asynchronous video."""
import asyncio
import re

import httpx

from .config import settings
from .provider_contract import ModelError, ModelResult, Usage

TASK_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
VIDEO_STATES = {"created", "queueing", "processing", "success", "failed"}


def parse_usage(value):
    if not isinstance(value, dict):
        return None
    input_tokens = value.get("input_tokens")
    output_tokens = value.get("output_tokens")
    if type(input_tokens) is not int or type(output_tokens) is not int or min(input_tokens, output_tokens) < 0:
        return None
    request_id = value.get("request_id")
    return Usage(input_tokens, output_tokens, request_id[:200] if isinstance(request_id, str) else None)


class ProviderClient:
    def __init__(self, *, transport=None):
        cfg = settings()
        self.http = httpx.AsyncClient(
            base_url=cfg.provider_gateway_url,
            headers={"Authorization":"Bearer "+cfg.provider_gateway_token},
            timeout=httpx.Timeout(cfg.provider_gateway_timeout_seconds, connect=5),
            follow_redirects=False, trust_env=False, transport=transport,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.http.aclose()

    async def request(self, method, path, *, payload=None, run_id=None, timeout=10):
        paid = method == "POST"
        try:
            response = await self.http.request(
                method,path,json=payload,headers={"X-Run-ID":run_id} if run_id else None,
                timeout=self.http.timeout if timeout is None else httpx.Timeout(timeout,connect=5),
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise ModelError("MODEL_CONNECTION","暂未连接到模型网关，请稍后重试") from None
        except httpx.TimeoutException:
            code="MODEL_TIMEOUT" if path=="/internal/v1/text/generate" else "MODEL_NETWORK"
            raise ModelError(code,"模型网关响应超时，请稍后重试",uncertain=paid) from None
        except httpx.HTTPError:
            raise ModelError("MODEL_NETWORK","模型网关响应中断，请稍后查询",uncertain=paid) from None
        try:
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError()
        except ValueError:
            raise ModelError("MODEL_PROTOCOL","模型网关返回无效响应",uncertain=paid) from None
        if not response.is_success:
            error = result.get("error")
            if not isinstance(error, dict) or not isinstance(error.get("code"),str) or not isinstance(error.get("message"),str):
                raise ModelError("MODEL_HTTP","模型网关暂不可用",uncertain=paid and response.status_code>=500)
            usage = parse_usage(error.get("usage"))
            raise ModelError(error["code"],error["message"],usage=usage,uncertain=error.get("uncertain") is True)
        return result

    async def capabilities(self):
        result = await self.request("GET","/internal/v1/capabilities")
        model = result.get("text_model")
        return {"text_configured":result.get("text_configured") is True,
                "video_configured":result.get("video_configured") is True,
                "text_model":model if isinstance(model,str) else None}

    async def text_limit(self):
        result = await self.request("GET","/internal/v1/text/capabilities")
        limit = result.get("max_output_tokens")
        if type(limit) is not int or limit < 1:
            raise ModelError("MODEL_CONFIG","模型网关未提供有效的输出上限")
        return limit

    async def generate(self, messages, limit, response_schema, *, run_id=None, timeout_seconds=None):
        payload = {
            "messages":messages,"max_output_tokens":limit,"response_schema":response_schema,
        }
        if timeout_seconds is not None:
            payload["timeout_seconds"] = timeout_seconds
        deadline = min(timeout_seconds + 10, self.http.timeout.read) if timeout_seconds is not None else None
        try:
            async with asyncio.timeout(deadline):
                result = await self.request("POST","/internal/v1/text/generate",payload=payload,run_id=run_id,timeout=None)
        except TimeoutError:
            raise ModelError("MODEL_TIMEOUT","模型请求超时，未确认的积分预授权待核对",uncertain=True) from None
        usage = parse_usage(result.get("usage"))
        if not usage:
            raise ModelError("MODEL_USAGE_MISSING","模型没有返回可信用量，预授权积分待核对",uncertain=True)
        content = result.get("content")
        if not isinstance(content,str) or not content.strip():
            raise ModelError("MODEL_EMPTY","模型没有返回可用代码",usage=usage)
        return ModelResult(content,usage)

    async def submit_video(self, *, image=None, prompt, expected_model, resolution, duration, audio, payload):
        try:
            result = await self.request("POST","/internal/v1/video/tasks",payload={
                "image":image,"prompt":prompt,"expected_model":expected_model,"resolution":resolution,
                "duration":duration,"audio":bool(audio),"request_id":payload,
            },run_id=payload,timeout=90)
        except ModelError as error:
            if error.uncertain:
                raise ModelError("VIDU_SUBMISSION_UNCERTAIN","视频提交结果待核对，系统不会重复提交",uncertain=True) from None
            raise
        task_id = result.get("task_id")
        if not isinstance(task_id,str) or not TASK_ID.fullmatch(task_id):
            raise ModelError("VIDU_SUBMISSION_UNCERTAIN","生成请求的结果待核对，请联系管理员",uncertain=True)
        return task_id

    async def query_video(self, task_id, *, run_id=None):
        if not TASK_ID.fullmatch(task_id):
            raise ModelError("VIDU_INVALID_TASK","视频任务编号无效")
        try:
            result = await self.request("GET",f"/internal/v1/video/tasks/{task_id}",run_id=run_id,timeout=70)
        except ModelError as error:
            if error.code in {"MODEL_CONNECTION","MODEL_NETWORK","MODEL_HTTP","PROVIDER_RATE_LIMIT","PROVIDER_SECRET_UNAVAILABLE","PROVIDER_NOT_CONFIGURED"}:
                raise ModelError("VIDU_POLL_RETRY","视频正在生成，稍后继续查询") from None
            raise
        if result.get("state") not in VIDEO_STATES:
            raise ModelError("VIDU_INVALID_RESPONSE","视频服务暂未返回任务状态，请稍后继续查询")
        return result
