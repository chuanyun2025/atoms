"""Private, versioned AI provider gateway. No project or wallet database access."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
import hmac
import logging
import re
from time import monotonic
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import chat_completions
from .provider_contract import ModelError
from .provider_secrets import ProviderSecrets
from .provider_settings import ProviderSettings
from .vidu import TASK_ID, ViduClient

log = logging.getLogger("uvicorn.error")


class GenerationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system","user","assistant"]
    content: str


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[GenerationMessage] = Field(min_length=1)
    max_output_tokens: Annotated[int, Field(strict=True,gt=0)]
    response_schema: dict | None = None
    timeout_seconds: Annotated[int, Field(strict=True,gt=0)] | None = None


class VideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1,max_length=20000)
    image: str | None = None
    expected_model: str = Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")
    resolution: Literal["540p","720p","1080p"]
    duration: Annotated[int, Field(strict=True,ge=1,le=16)]
    audio: bool
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")


async def read_input(request: Request, schema, limit: int):
    body = bytearray()
    async for chunk in request.stream():
        if len(body)+len(chunk) > limit:
            raise ModelError("PROVIDER_INVALID_REQUEST","网关请求超过大小上限")
        body.extend(chunk)
    try:
        return schema.model_validate_json(body)
    except ValidationError:
        raise ModelError("PROVIDER_INVALID_REQUEST","网关请求格式无效") from None


def create_app(config=None, *, transport=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.config = config or ProviderSettings()
        app.state.secrets = ProviderSecrets(app.state.config)
        app.state.slots = {kind:asyncio.Semaphore(app.state.config.provider_max_concurrency) for kind in ("text","video")}
        app.state.tokens = float(app.state.config.provider_requests_per_minute)
        app.state.refill_at = monotonic()
        app.state.text_limit = None
        app.state.text_limit_lock = asyncio.Lock()
        yield

    app = FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)

    async def authorize(request: Request):
        token = app.state.config.provider_gateway_token.get_secret_value()
        if not hmac.compare_digest(request.headers.get("authorization","").encode(),("Bearer "+token).encode()):
            raise ModelError("PROVIDER_UNAUTHORIZED","网关服务凭证无效")

    def limit_requests(paid):
        cfg = app.state.config
        now = monotonic()
        tokens = min(cfg.provider_requests_per_minute,
                     app.state.tokens+(now-app.state.refill_at)*cfg.provider_requests_per_minute/60)
        app.state.refill_at = now
        app.state.tokens = tokens
        if not paid:
            return
        if tokens < 1:
            raise ModelError("PROVIDER_RATE_LIMIT","供应商网关繁忙，请稍后重试")
        app.state.tokens -= 1

    async def key_for(provider):
        key = await app.state.secrets.get(provider)
        if not key:
            raise ModelError("PROVIDER_NOT_CONFIGURED","供应商暂未配置")
        return key

    async def current_text_limit():
        cfg = app.state.config
        if not cfg.llm_base_url or not cfg.llm_model:
            raise ModelError("PROVIDER_NOT_CONFIGURED","文本生成尚未配置")
        async with app.state.text_limit_lock:
            cached = app.state.text_limit
            if cached and cached[0] > monotonic():
                return cached[1]
            limit = await chat_completions.output_limit(cfg,await key_for("llm"),transport=transport)
            app.state.text_limit = (monotonic()+600,limit)
            return limit

    @app.exception_handler(ModelError)
    async def model_error(request, error):
        statuses = {"PROVIDER_UNAUTHORIZED":401,"PROVIDER_INVALID_REQUEST":400,
                    "PROVIDER_RATE_LIMIT":429,"PROVIDER_NOT_CONFIGURED":503,
                    "PROVIDER_SECRET_UNAVAILABLE":503,"VIDU_POLL_RETRY":503,
                    "MODEL_AUTH":401,"MODEL_RATE_LIMIT":429,"MODEL_TIMEOUT":504}
        return JSONResponse({"error":{"code":error.code,"message":str(error),"uncertain":error.uncertain,
                                      "usage":asdict(error.usage) if error.usage else None}},
                            status_code=statuses.get(error.code,502))

    async def invoke(request, operation, call):
        started = monotonic()
        run_id = request.headers.get("x-run-id","")
        run_id = run_id if re.fullmatch(r"[A-Za-z0-9_-]{1,128}",run_id) else "-"
        outcome = "ok"
        try:
            slots = app.state.slots[operation.partition(".")[0]]
            if slots.locked():
                raise ModelError("PROVIDER_RATE_LIMIT","供应商网关繁忙，请稍后重试")
            limit_requests(request.method == "POST")
            async with slots:
                return await call()
        except ModelError as error:
            outcome = error.code
            raise
        except Exception:
            outcome = "PROVIDER_INTERNAL"
            raise ModelError(outcome,"供应商网关处理失败",uncertain=request.method=="POST") from None
        finally:
            log.info("provider operation=%s run=%s outcome=%s elapsed_ms=%d",operation,run_id,outcome,(monotonic()-started)*1000)

    @app.get("/health/live")
    async def live():
        return {"status":"ok"}

    private = [Depends(authorize)]

    @app.get("/internal/v1/capabilities",dependencies=private)
    async def capabilities():
        cfg = app.state.config
        text = bool(cfg.llm_model and cfg.llm_base_url and (cfg.llm_kms_secret_name or cfg.llm_api_key.get_secret_value()))
        video = bool(cfg.vidu_kms_secret_name or cfg.vidu_api_key.get_secret_value())
        return {"text_configured":text,"text_model":cfg.llm_model if text else None,"video_configured":video}

    @app.get("/internal/v1/text/capabilities",dependencies=private)
    async def text_capabilities():
        return {"max_output_tokens":await current_text_limit()}

    @app.post("/internal/v1/text/generate",dependencies=private)
    async def generate(request: Request):
        data = await read_input(request,GenerationRequest,32*1024*1024)
        cfg = app.state.config
        if data.max_output_tokens > await current_text_limit():
            raise ModelError("PROVIDER_INVALID_REQUEST","请求的输出长度超出模型配置")
        async def call():
            key=await key_for("llm")
            timeout=min(data.timeout_seconds or cfg.llm_request_timeout_seconds,cfg.llm_request_timeout_seconds)
            try:
                async with asyncio.timeout(timeout):
                    result=await chat_completions.complete(cfg,key,[m.model_dump() for m in data.messages],
                                   data.max_output_tokens,data.response_schema,transport=transport)
            except TimeoutError:
                raise ModelError("MODEL_TIMEOUT","模型请求超时，未确认的积分预授权待核对",uncertain=True) from None
            return asdict(result)
        return await invoke(request,"text.generate",call)

    @app.post("/internal/v1/video/tasks",dependencies=private)
    async def submit_video(request: Request):
        data = await read_input(request,VideoRequest,8*1024*1024)
        cfg = app.state.config
        if data.expected_model != cfg.vidu_model:
            raise ModelError("PROVIDER_INVALID_REQUEST","视频模型与报价不一致，请重新提交任务")
        if data.image and not data.image.startswith(("data:image/png;base64,","data:image/jpeg;base64,","data:image/webp;base64,")):
            raise ModelError("PROVIDER_INVALID_REQUEST","视频首帧必须是内联图片")
        async def call():
            async with ViduClient(await key_for("vidu"),cfg.vidu_base_url,transport=transport) as provider:
                options = data.model_dump(exclude={"image","request_id","expected_model"})
                options["model"] = cfg.vidu_model
                options["payload"] = data.request_id
                task_id = await provider.create(image=data.image,**options) if data.image else await provider.create_text(**options)
                return {"task_id":task_id}
        return await invoke(request,"video.submit",call)

    @app.get("/internal/v1/video/tasks/{task_id}",dependencies=private)
    async def query_video(task_id: str, request: Request):
        if not TASK_ID.fullmatch(task_id):
            raise ModelError("PROVIDER_INVALID_REQUEST","视频任务编号无效")
        async def call():
            async with ViduClient(await key_for("vidu"),app.state.config.vidu_base_url,transport=transport) as provider:
                result = await provider.query(task_id)
                creations = result.get("creations")
                first = creations[0] if isinstance(creations,list) and creations and isinstance(creations[0],dict) else {}
                return {"state":result["state"],"credits":result.get("credits"),"video_url":first.get("url")}
        return await invoke(request,"video.query",call)

    return app


app = create_app()
