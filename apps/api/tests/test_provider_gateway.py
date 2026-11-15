import asyncio
import json

import httpx
import pytest

from atoms.config import settings
from atoms.provider_client import ProviderClient
from atoms.provider_contract import ModelError
from atoms.provider_gateway import complete_until_disconnect, create_app
from atoms.provider_secrets import ProviderSecrets
from atoms.provider_settings import ProviderSettings


TOKEN = "provider-test-token-" * 2
MESSAGES = [{"role":"user","content":"测试"}]


def gateway(upstream, **options):
    config = ProviderSettings(provider_gateway_token=TOKEN,llm_api_key="test-text-key",vidu_api_key="test-video-key",
                              llm_base_url="https://api.deepseek.com",llm_model="replacement-model",**options)
    return create_app(config,transport=httpx.MockTransport(upstream))


def test_stable_text_contract_and_gateway_limit(monkeypatch):
    calls = []

    def upstream(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer test-text-key"
        if request.method == "GET":
            assert request.url.path == "/models"
            return httpx.Response(200,json={"data":[{"id":"replacement-model","max_output_tokens":300}]})
        assert request.url.path == "/chat/completions"
        assert json.loads(request.content) == {"model":"replacement-model","messages":MESSAGES,
            "stream":False,"max_completion_tokens":300,"response_format":{"type":"json_object"}}
        return httpx.Response(200,json={"id":"upstream-id","choices":[{"message":{"content":"{}"}}],
                                        "usage":{"prompt_tokens":42,"completion_tokens":8}})

    async def check():
        app = gateway(upstream,provider_requests_per_minute=1,llm_token_limit_param="max_completion_tokens",llm_response_mode="json_object")
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app), ProviderClient(transport=transport) as client:
            denied = await client.http.get("/internal/v1/capabilities")
            assert denied.status_code==401
            assert not calls
            monkeypatch.setattr(settings(),"provider_gateway_token",TOKEN)
            async with ProviderClient(transport=transport) as authorized:
                assert (await authorized.capabilities())["text_model"]=="replacement-model"
                assert await authorized.text_limit()==300
                result=await authorized.generate(MESSAGES,300,None)
                assert result.content=="{}" and result.usage.request_id=="upstream-id"
                assert (result.usage.input_tokens,result.usage.output_tokens)==(42,8)
                with pytest.raises(ModelError,match="繁忙") as caught:
                    await authorized.generate(MESSAGES,300,None)
                assert caught.value.code=="PROVIDER_RATE_LIMIT" and not caught.value.uncertain
        assert [call.method for call in calls]==["GET","POST"]

    asyncio.run(check())


def test_video_submission_uncertainty_and_query_contract(monkeypatch):
    monkeypatch.setattr(settings(),"provider_gateway_token",TOKEN)
    calls = []

    def upstream(request):
        calls.append(request.method)
        assert request.headers["authorization"]=="Token test-video-key"
        if request.method=="POST":
            assert request.url.path=="/ent/v2/text2video"
            assert json.loads(request.content)["model"]=="replacement-video"
            assert json.loads(request.content)["payload"]=="local-run"
            raise httpx.ReadTimeout("test-video-key",request=request)
        assert request.url.path=="/ent/v2/tasks/existing-task/creations"
        return httpx.Response(200,json={"state":"success","credits":17,"creations":[{"url":"https://cdn.example.com/output.mp4"}]})

    async def check():
        app = gateway(upstream,vidu_model="replacement-video")
        async with app.router.lifespan_context(app), ProviderClient(transport=httpx.ASGITransport(app=app)) as client:
            with pytest.raises(ModelError) as rejected:
                await client.submit_video(prompt="test",expected_model="viduq3-pro",resolution="540p",duration=5,audio=True,payload="local-run")
            assert rejected.value.code=="PROVIDER_INVALID_REQUEST" and not rejected.value.uncertain
            with pytest.raises(ModelError) as caught:
                await client.submit_video(prompt="test",expected_model="replacement-video",resolution="540p",duration=5,audio=True,payload="local-run")
            assert caught.value.code=="VIDU_SUBMISSION_UNCERTAIN" and caught.value.uncertain
            assert "test-video-key" not in str(caught.value)
            assert await client.query_video("existing-task")=={
                "state":"success","credits":17,"video_url":"https://cdn.example.com/output.mp4",
            }
    asyncio.run(check())
    assert calls==["POST","GET"]


def test_text_deadline_releases_gateway_slot(monkeypatch):
    monkeypatch.setattr(settings(),"provider_gateway_token",TOKEN)
    canceled=False
    submitted=0

    async def upstream(request):
        nonlocal canceled,submitted
        if request.method=="GET":
            return httpx.Response(200,json={"data":[]})
        submitted+=1
        if submitted==1:
            try:
                await asyncio.sleep(30)
            finally:
                canceled=True
        return httpx.Response(200,json={"choices":[{"message":{"content":"{}"}}],
                                        "usage":{"prompt_tokens":3,"completion_tokens":2}})

    async def check():
        app=gateway(upstream,provider_max_concurrency=1)
        async with app.router.lifespan_context(app), ProviderClient(transport=httpx.ASGITransport(app=app)) as client:
            with pytest.raises(ModelError) as caught:
                await client.generate(MESSAGES,300,None,timeout_seconds=1)
            assert caught.value.code=="MODEL_TIMEOUT" and caught.value.uncertain
            assert canceled
            assert (await client.generate(MESSAGES,300,None,timeout_seconds=1)).content=="{}"

    asyncio.run(check())
    assert submitted==2


def test_gateway_disconnect_cancels_active_text_completion():
    async def check():
        started=asyncio.Event()
        cancelled=asyncio.Event()

        class Request:
            async def receive(self):
                await started.wait()
                return {"type":"http.disconnect"}

        async def complete():
            started.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

        with pytest.raises(ModelError) as error:
            await asyncio.wait_for(complete_until_disconnect(Request(),complete),timeout=1)
        assert cancelled.is_set()
        assert error.value.code=="CALL_INTERRUPTED" and error.value.uncertain

    asyncio.run(check())


def test_kms_secret_overrides_environment_and_is_cached(monkeypatch):
    config = ProviderSettings(provider_gateway_token=TOKEN, llm_api_key="test-fallback",
                              provider_kms_region="cn-hangzhou", llm_kms_secret_name="text-secret")
    source = ProviderSecrets(config)
    reads = []

    def read(name):
        reads.append(name)
        return "test-kms-key"

    monkeypatch.setattr(source,"read_kms",read)

    async def check():
        assert await source.get("llm")=="test-kms-key"
        assert await source.get("llm")=="test-kms-key"

    asyncio.run(check())
    assert reads==["text-secret"]
