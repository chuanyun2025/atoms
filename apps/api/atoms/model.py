import asyncio
import json
from pathlib import Path
from dataclasses import dataclass
import time
import httpx
from .config import settings
from .db import compact
from .prompts import messages_for
from .skills import GenerationSkill
from .slide_decks import DeckContent

class ModelError(Exception):
    def __init__(self,code,message,usage=None,uncertain=False):
        self.code=code
        self.usage=usage
        self.uncertain=uncertain
        super().__init__(message)


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    request_id: str | None = None


@dataclass(frozen=True)
class Prepared:
    messages: list
    input_ceiling: int
    output_limit: int
    slide_content: bool = False
    react_site: bool = False
    decision_role: str | None = None
    response_schema: dict | None = None


@dataclass(frozen=True)
class ModelResult:
    content: str
    usage: Usage


_capabilities={}


async def native_output_limit():
    config=settings()
    if config.app_env=="test" and config.test_fixture:
        return config.llm_provider_max_output_tokens
    cache_key=(config.llm_base_url,config.llm_model)
    cached=_capabilities.get(cache_key)
    if cached and cached[0]>time.monotonic():
        return cached[1]
    base=config.llm_base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        base=base[:-len("/chat/completions")]
    limit=config.llm_provider_max_output_tokens
    try:
        async with httpx.AsyncClient(timeout=10,follow_redirects=False,trust_env=False) as client:
            response=await client.get(base+"/models",headers={"Authorization":"Bearer "+config.llm_api_key})
            if response.status_code in {401,403}:
                raise ModelError("MODEL_AUTH","模型服务认证失败，请检查密钥和服务权限")
            if response.is_success:
                metadata=response.json()
                model=next((m for m in metadata.get("data",[]) if m.get("id")==config.llm_model),None)
                if model and type(model.get("max_output_tokens")) is int and model["max_output_tokens"]>0:
                    limit=model["max_output_tokens"]
    except (httpx.HTTPError,ValueError,TypeError):
        # Explicit provider capability fallback, never the former 8192 business cap.
        pass
    if type(limit) is not int or limit<1:
        raise ModelError("MODEL_CONFIG","缺少模型原生输出能力，请配置供应商能力回退值")
    _capabilities[cache_key]=(time.monotonic()+600,limit)
    return limit


async def prepare(context, repair, *, skill: GenerationSkill):
    messages=messages_for(context, repair, skill=skill)
    # A conservative financial authorization, not actual token billing or a context truncation.
    input_ceiling=len(compact(messages).encode("utf-8"))+1024
    return Prepared(messages,input_ceiling,await native_output_limit(),
                    slide_content=bool(context.get("slide_template")),react_site=context.get("site_format")=="react")

async def prepare_decision(role: str, context: dict):
    from .orchestration import TaskPlan, TaskReview, decision_messages

    messages=decision_messages(role,context)
    schema=(TaskPlan if role=="planner" else TaskReview).model_json_schema()
    return Prepared(messages,len(compact(messages).encode("utf-8"))+1024,
                    min(4096,await native_output_limit()),decision_role=role,response_schema=schema)


def parse_usage(data):
    usage=data.get("usage")
    if not isinstance(usage,dict):
        raise ModelError("MODEL_USAGE_MISSING","模型没有返回可信用量，预授权积分待核对",uncertain=True)
    input_tokens,output_tokens=usage.get("prompt_tokens"),usage.get("completion_tokens")
    if type(input_tokens) is not int or type(output_tokens) is not int or min(input_tokens,output_tokens)<0:
        raise ModelError("MODEL_USAGE_INVALID","模型返回用量无效，预授权积分待核对",uncertain=True)
    request_id=data.get("id")
    return Usage(input_tokens,output_tokens,request_id[:200] if isinstance(request_id,str) else None)


async def generate(prepared,output_tokens):
    config=settings()
    if config.app_env=="test" and config.test_fixture:
        from .model_fixture import test_artifact

        context=json.loads(prepared.messages[1]["content"])
        repair=json.loads(prepared.messages[2]["content"].split("\n",1)[1]) if len(prepared.messages)>2 else None
        await asyncio.sleep(8 if "[slow]" in context["request"] else .25)
        if prepared.decision_role:
            from .model_fixture import test_decision
            raw=test_decision(prepared.decision_role,context)
        else:
            raw=test_artifact(context,repair)
        return ModelResult(raw,Usage(1200,400,"fixture-"+str(time.time_ns())))
    base=config.llm_base_url.rstrip("/")
    url=base if base.endswith("/chat/completions") else base+"/chat/completions"
    if config.llm_token_limit_param not in {"max_tokens","max_completion_tokens"}:
        raise ModelError("MODEL_CONFIG","输出长度参数配置无效")
    payload={"model":config.llm_model,"messages":prepared.messages,"stream":False,config.llm_token_limit_param:output_tokens}
    if config.llm_thinking_mode:
        if config.llm_thinking_mode not in {"enabled","disabled"}:
            raise ModelError("MODEL_CONFIG","思考模式配置无效")
        payload["thinking"]={"type":config.llm_thinking_mode}
    if config.llm_response_mode=="json_object":
        payload["response_format"]={"type":"json_object"}
    elif config.llm_response_mode=="json_schema":
        if prepared.response_schema:
            name,schema=prepared.decision_role,prepared.response_schema
        elif prepared.slide_content:
            name,schema="slide_content",DeckContent.model_json_schema()
        else:
            name,filename=("react_artifact","react-artifact") if prepared.react_site else ("artifact","artifact")
            schema=json.loads((Path(__file__).resolve().parents[3]/"shared/contracts"/f"{filename}.schema.json").read_text("utf-8"))
            schema.pop("$schema",None)
        payload["response_format"]={"type":"json_schema","json_schema":{"name":name,"strict":True,"schema":schema}}
    elif config.llm_response_mode!="text":
        raise ModelError("MODEL_CONFIG","响应格式配置无效")
    usage=None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(config.llm_request_timeout_seconds,connect=10),follow_redirects=False,trust_env=False) as client:
            async with client.stream("POST",url,headers={"Authorization":"Bearer "+config.llm_api_key},json=payload) as response:
                if response.status_code in {401,403}:
                    raise ModelError("MODEL_AUTH","模型服务认证失败，请检查密钥和服务权限")
                if response.status_code==429:
                    raise ModelError("MODEL_RATE_LIMIT","模型服务限流或额度不足，请稍后重试")
                if response.status_code>=400:
                    raise ModelError("MODEL_HTTP","模型接口返回错误（HTTP "+str(response.status_code)+"），请检查配置或上下文",uncertain=response.status_code>=500)
                body=bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body)>32*1024*1024:
                        raise ModelError("MODEL_RESPONSE_TOO_LARGE","模型响应超过传输资源保护，积分待核对",uncertain=True)
        data=json.loads(body)
        usage=parse_usage(data)
        choice=data["choices"][0]
        if choice.get("finish_reason")=="length":
            raise ModelError("MODEL_TRUNCATED","模型输出达到供应商能力或当前积分预算边界，未交付不完整代码",usage=usage)
        message=choice["message"]
        if message.get("refusal"):
            raise ModelError("MODEL_REFUSED","模型未接受该请求，请调整需求",usage=usage)
        content=message.get("content")
        if not isinstance(content,str) or not content.strip():
            raise ModelError("MODEL_EMPTY","模型没有返回可用代码",usage=usage)
        return ModelResult(content,usage)
    except (httpx.ConnectError,httpx.ConnectTimeout,httpx.PoolTimeout):
        raise ModelError("MODEL_CONNECTION","未能建立模型连接，积分预授权已释放，请检查网络") from None
    except httpx.TimeoutException:
        raise ModelError("MODEL_TIMEOUT","模型请求超时；缺失用量的积分预授权待核对",uncertain=True) from None
    except httpx.HTTPError:
        raise ModelError("MODEL_NETWORK","模型连接中断；缺失用量的积分预授权待核对",uncertain=True) from None
    except (KeyError,IndexError,ValueError,TypeError):
        raise ModelError("MODEL_PROTOCOL","模型返回不兼容的响应；用量可得时仍按实际结算",usage=usage,uncertain=usage is None) from None
