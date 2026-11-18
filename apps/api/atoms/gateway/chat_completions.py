"""OpenAI-compatible text generation adapter, used by the provider gateway."""

import json

import httpx

from atoms.gateway.provider_contract import ModelError, ModelResult, Usage


def base_url(config):
    return config.llm_base_url.rstrip("/").removesuffix("/chat/completions")


async def output_limit(config, api_key, *, transport=None):
    fallback = config.llm_provider_max_output_tokens
    try:
        async with httpx.AsyncClient(timeout=4, follow_redirects=False, trust_env=False, transport=transport) as client:
            response = await client.get(base_url(config) + "/models", headers={"Authorization": "Bearer " + api_key})
            if response.is_success:
                for model in response.json().get("data", []):
                    if model.get("id") == config.llm_model:
                        maximum = model.get("max_output_tokens")
                        if type(maximum) is int and maximum > 0:
                            return maximum
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        pass
    return fallback


def parse_usage(data):
    usage = data.get("usage")
    if not isinstance(usage, dict):
        raise ModelError("MODEL_USAGE_MISSING", "模型没有返回可信用量，预授权积分待核对", uncertain=True)
    input_tokens, output_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if type(input_tokens) is not int or type(output_tokens) is not int or min(input_tokens, output_tokens) < 0:
        raise ModelError("MODEL_USAGE_INVALID", "模型返回用量无效，预授权积分待核对", uncertain=True)
    request_id = data.get("id")
    return Usage(input_tokens, output_tokens, request_id[:200] if isinstance(request_id, str) else None)


def _as_dict(value):
    if not isinstance(value, dict):
        raise TypeError("expected JSON object")
    return value


async def _read_json_completion(response, on_usage=None):
    usage = None
    try:
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > 32 * 1024 * 1024:
                raise ModelError("MODEL_RESPONSE_TOO_LARGE", "模型响应超过传输资源保护，积分待核对", uncertain=True)
        data = _as_dict(json.loads(body))
        usage = parse_usage(data)
        if on_usage is not None:
            on_usage(usage)
        choices = data["choices"]
        if not isinstance(choices, list):
            raise TypeError("choices must be a list")
        choice = _as_dict(choices[0])
        if choice.get("finish_reason") == "length":
            raise ModelError(
                "MODEL_TRUNCATED", "模型输出达到供应商能力或当前积分预算边界，未交付不完整代码", usage=usage
            )
        message = _as_dict(choice["message"])
        if message.get("refusal"):
            raise ModelError("MODEL_REFUSED", "模型未接受该请求，请调整需求", usage=usage)
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ModelError("MODEL_EMPTY", "模型没有返回可用代码", usage=usage)
        return ModelResult(content, usage)
    except ModelError:
        raise
    except (KeyError, IndexError, ValueError, TypeError, AttributeError):
        raise ModelError(
            "MODEL_PROTOCOL", "模型返回不兼容的响应；用量可得时仍按实际结算", usage=usage, uncertain=usage is None
        ) from None


async def _read_sse_completion(response, on_usage=None):
    usage = None
    request_id = None
    finish_reason = None
    refusal = None
    parts = []
    raw_bytes = 0
    try:
        async for line in response.aiter_lines():
            raw_bytes += len(line.encode("utf-8")) + 1
            if raw_bytes > 32 * 1024 * 1024:
                raise ModelError("MODEL_RESPONSE_TOO_LARGE", "模型响应超过传输资源保护，积分待核对", uncertain=True)
            if not line or line.startswith(":") or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            chunk = _as_dict(json.loads(payload))
            if isinstance(chunk.get("id"), str) and not request_id:
                request_id = chunk["id"]
            if isinstance(chunk.get("usage"), dict):
                usage = parse_usage({"id": request_id or chunk.get("id"), "usage": chunk["usage"]})
                if on_usage is not None:
                    on_usage(usage)
            if isinstance(chunk.get("error"), dict) and not chunk.get("choices"):
                raise ModelError(
                    "MODEL_PROTOCOL", "模型返回错误流响应；用量可得时仍按实际结算", usage=usage, uncertain=usage is None
                )
            choices = chunk.get("choices")
            if choices is None:
                choices = []
            elif not isinstance(choices, list):
                raise TypeError("choices must be a list")
            if choices:
                choice = _as_dict(choices[0])
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
                delta = choice.get("delta")
                delta = {} if delta is None else _as_dict(delta)
                if delta.get("refusal"):
                    refusal = delta["refusal"]
                piece = delta.get("content")
                if isinstance(piece, str):
                    parts.append(piece)
        if usage is None:
            raise ModelError("MODEL_USAGE_MISSING", "模型没有返回可信用量，预授权积分待核对", uncertain=True)
        if finish_reason == "length":
            raise ModelError(
                "MODEL_TRUNCATED", "模型输出达到供应商能力或当前积分预算边界，未交付不完整代码", usage=usage
            )
        if refusal:
            raise ModelError("MODEL_REFUSED", "模型未接受该请求，请调整需求", usage=usage)
        content = "".join(parts)
        if not content.strip():
            raise ModelError("MODEL_EMPTY", "模型没有返回可用代码", usage=usage)
        return ModelResult(content, usage)
    except ModelError:
        raise
    except httpx.TimeoutException:
        if usage is None:
            raise
        raise ModelError(
            "MODEL_TIMEOUT", "模型请求超时；用量可得时仍按实际结算", usage=usage, uncertain=False
        ) from None
    except httpx.HTTPError:
        if usage is None:
            raise
        raise ModelError(
            "MODEL_NETWORK", "模型连接中断；用量可得时仍按实际结算", usage=usage, uncertain=False
        ) from None
    except (KeyError, IndexError, ValueError, TypeError, AttributeError):
        raise ModelError(
            "MODEL_PROTOCOL", "模型返回不兼容的流式响应；用量可得时仍按实际结算", usage=usage, uncertain=usage is None
        ) from None


async def complete(config, api_key, messages, output_tokens, response_schema, *, transport=None, on_usage=None):
    url = base_url(config) + "/chat/completions"
    stream = bool(getattr(config, "llm_stream", False))
    payload = {
        "model": config.llm_model,
        "messages": messages,
        "stream": stream,
        config.llm_token_limit_param: output_tokens,
    }
    if stream:
        payload["stream_options"] = {"include_usage": True}
    if config.llm_thinking_mode:
        payload["thinking"] = {"type": config.llm_thinking_mode}
    if config.llm_response_mode == "json_object":
        payload["response_format"] = {"type": "json_object"}
    elif config.llm_response_mode == "json_schema" and response_schema:
        payload["response_format"] = {"type": "json_schema", "json_schema": {**response_schema, "strict": True}}
    timeout = (
        httpx.Timeout(None, connect=10, read=min(120, config.llm_request_timeout_seconds))
        if stream
        else httpx.Timeout(config.llm_request_timeout_seconds, connect=10)
    )
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=False, trust_env=False, transport=transport
        ) as client:
            async with client.stream(
                "POST", url, headers={"Authorization": "Bearer " + api_key}, json=payload
            ) as response:
                if response.status_code in {401, 403}:
                    raise ModelError("MODEL_AUTH", "模型服务认证失败，请检查密钥和服务权限")
                if response.status_code == 429:
                    raise ModelError("MODEL_RATE_LIMIT", "模型服务限流或额度不足，请稍后重试")
                if response.status_code >= 400:
                    raise ModelError(
                        "MODEL_HTTP",
                        "模型接口返回错误（HTTP " + str(response.status_code) + "），请检查配置或上下文",
                        uncertain=response.status_code >= 500,
                    )
                content_type = response.headers.get("content-type", "").lower()
                if stream and "application/json" not in content_type:
                    return await _read_sse_completion(response, on_usage)
                return await _read_json_completion(response, on_usage)
    except ModelError:
        raise
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
        raise ModelError("MODEL_CONNECTION", "未能建立模型连接，积分预授权已释放，请检查网络") from None
    except httpx.TimeoutException:
        raise ModelError("MODEL_TIMEOUT", "模型请求超时；缺失用量的积分预授权待核对", uncertain=True) from None
    except httpx.HTTPError:
        raise ModelError("MODEL_NETWORK", "模型连接中断；缺失用量的积分预授权待核对", uncertain=True) from None
    except (KeyError, IndexError, ValueError, TypeError, AttributeError):
        raise ModelError("MODEL_PROTOCOL", "模型返回不兼容的响应；用量可得时仍按实际结算", uncertain=True) from None
