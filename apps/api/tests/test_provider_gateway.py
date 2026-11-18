import asyncio
import json

import httpx
import pytest

from atoms.core.config import settings
from atoms.gateway.provider_client import ProviderClient
from atoms.gateway.provider_contract import ModelError
from atoms.gateway.provider_secrets import ProviderSecrets
from atoms.gateway.provider_settings import ProviderSettings
from atoms.provider_gateway import complete_until_disconnect, create_app

TOKEN = "provider-test-token-" * 2
MESSAGES = [{"role": "user", "content": "测试"}]


def gateway(upstream, **options):
    config = ProviderSettings(
        provider_gateway_token=TOKEN,
        llm_api_key="test-text-key",
        vidu_api_key="test-video-key",
        llm_base_url="https://api.deepseek.com",
        llm_model="replacement-model",
        **options,
    )
    return create_app(config, transport=httpx.MockTransport(upstream))


def test_stable_text_contract_and_gateway_limit(monkeypatch):
    calls = []

    def upstream(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer test-text-key"
        if request.method == "GET":
            assert request.url.path == "/models"
            return httpx.Response(200, json={"data": [{"id": "replacement-model", "max_output_tokens": 300}]})
        assert request.url.path == "/chat/completions"
        assert json.loads(request.content) == {
            "model": "replacement-model",
            "messages": MESSAGES,
            "stream": False,
            "max_completion_tokens": 300,
            "response_format": {"type": "json_object"},
        }
        return httpx.Response(
            200,
            json={
                "id": "upstream-id",
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 42, "completion_tokens": 8},
            },
        )

    async def check():
        app = gateway(
            upstream,
            provider_requests_per_minute=1,
            llm_token_limit_param="max_completion_tokens",
            llm_response_mode="json_object",
        )
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app), ProviderClient(transport=transport) as client:
            denied = await client.http.get("/internal/v1/capabilities")
            assert denied.status_code == 401
            assert not calls
            monkeypatch.setattr(settings(), "provider_gateway_token", TOKEN)
            async with ProviderClient(transport=transport) as authorized:
                assert (await authorized.capabilities())["text_model"] == "replacement-model"
                assert await authorized.text_limit() == 300
                result = await authorized.generate(MESSAGES, 300, None)
                assert result.content == "{}" and result.usage.request_id == "upstream-id"
                assert (result.usage.input_tokens, result.usage.output_tokens) == (42, 8)
                with pytest.raises(ModelError, match="繁忙") as caught:
                    await authorized.generate(MESSAGES, 300, None)
                assert caught.value.code == "PROVIDER_RATE_LIMIT" and not caught.value.uncertain
        assert [call.method for call in calls] == ["GET", "POST"]

    asyncio.run(check())


def test_video_submission_uncertainty_and_query_contract(monkeypatch):
    monkeypatch.setattr(settings(), "provider_gateway_token", TOKEN)
    calls = []

    def upstream(request):
        calls.append(request.method)
        assert request.headers["authorization"] == "Token test-video-key"
        if request.method == "POST":
            assert request.url.path == "/ent/v2/text2video"
            assert json.loads(request.content)["model"] == "replacement-video"
            assert json.loads(request.content)["payload"] == "local-run"
            raise httpx.ReadTimeout("test-video-key", request=request)
        assert request.url.path == "/ent/v2/tasks/existing-task/creations"
        return httpx.Response(
            200, json={"state": "success", "credits": 17, "creations": [{"url": "https://cdn.example.com/output.mp4"}]}
        )

    async def check():
        app = gateway(upstream, vidu_model="replacement-video")
        async with app.router.lifespan_context(app), ProviderClient(transport=httpx.ASGITransport(app=app)) as client:
            with pytest.raises(ModelError) as rejected:
                await client.submit_video(
                    prompt="test",
                    expected_model="viduq3-pro",
                    resolution="540p",
                    duration=5,
                    audio=True,
                    payload="local-run",
                )
            assert rejected.value.code == "PROVIDER_INVALID_REQUEST" and not rejected.value.uncertain
            with pytest.raises(ModelError) as caught:
                await client.submit_video(
                    prompt="test",
                    expected_model="replacement-video",
                    resolution="540p",
                    duration=5,
                    audio=True,
                    payload="local-run",
                )
            assert caught.value.code == "VIDU_SUBMISSION_UNCERTAIN" and caught.value.uncertain
            assert "test-video-key" not in str(caught.value)
            assert await client.query_video("existing-task") == {
                "state": "success",
                "credits": 17,
                "video_url": "https://cdn.example.com/output.mp4",
            }

    asyncio.run(check())
    assert calls == ["POST", "GET"]


def test_text_deadline_releases_gateway_slot(monkeypatch):
    monkeypatch.setattr(settings(), "provider_gateway_token", TOKEN)
    canceled = False
    submitted = 0

    async def upstream(request):
        nonlocal canceled, submitted
        if request.method == "GET":
            return httpx.Response(200, json={"data": []})
        submitted += 1
        if submitted == 1:
            try:
                await asyncio.sleep(30)
            finally:
                canceled = True
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}},
        )

    async def check():
        app = gateway(upstream, provider_max_concurrency=1)
        async with app.router.lifespan_context(app), ProviderClient(transport=httpx.ASGITransport(app=app)) as client:
            with pytest.raises(ModelError) as caught:
                await client.generate(MESSAGES, 300, None, timeout_seconds=1)
            assert caught.value.code == "MODEL_TIMEOUT" and caught.value.uncertain
            assert canceled
            assert (await client.generate(MESSAGES, 300, None, timeout_seconds=1)).content == "{}"

    asyncio.run(check())
    assert submitted == 2


def test_gateway_disconnect_cancels_active_text_completion():
    async def check():
        started = asyncio.Event()
        cancelled = asyncio.Event()

        class Request:
            async def receive(self):
                await started.wait()
                return {"type": "http.disconnect"}

        async def complete():
            started.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

        with pytest.raises(ModelError) as error:
            await asyncio.wait_for(complete_until_disconnect(Request(), complete), timeout=1)
        assert cancelled.is_set()
        assert error.value.code == "CALL_INTERRUPTED" and error.value.uncertain

    asyncio.run(check())


def test_kms_secret_overrides_environment_and_is_cached(monkeypatch):
    config = ProviderSettings(
        provider_gateway_token=TOKEN,
        llm_api_key="test-fallback",
        provider_kms_region="cn-hangzhou",
        llm_kms_secret_name="text-secret",
    )
    source = ProviderSecrets(config)
    reads = []

    def read(name):
        reads.append(name)
        return "test-kms-key"

    monkeypatch.setattr(source, "read_kms", read)

    async def check():
        assert await source.get("llm") == "test-kms-key"
        assert await source.get("llm") == "test-kms-key"

    asyncio.run(check())
    assert reads == ["text-secret"]


def test_streaming_sse_completion_and_usage_enforcement(monkeypatch):
    monkeypatch.setattr(settings(), "provider_gateway_token", TOKEN)

    def upstream(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "replacement-model", "max_output_tokens": 500}]})
        body = json.loads(request.content)
        assert body["stream"] is True and body["stream_options"] == {"include_usage": True}
        scenario = body["messages"][0]["content"]
        if scenario == "truncated":
            sse = (
                'data: {"id":"req-1","choices":[{"delta":{"content":"{\\"a\\":"}}]}\n\n'
                'data: {"id":"req-1","choices":[{"finish_reason":"length","delta":{}}],"usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n'
                "data: [DONE]\n\n"
            )
            return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=sse.encode())
        if scenario == "missing-usage":
            sse = 'data: {"id":"req-2","choices":[{"delta":{"content":"{}"}}]}\n\ndata: [DONE]\n\n'
            return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=sse.encode())
        sse = (
            'data: {"id":"req-3","choices":[{"delta":{"content":"{\\"ok\\":"}}]}\n\n'
            'data: {"id":"req-3","choices":[{"delta":{"content":"true}"},"finish_reason":"stop"}]}\n\n'
            'data: {"id":"req-3","choices":[],"usage":{"prompt_tokens":20,"completion_tokens":7}}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=sse.encode())

    async def check():
        app = gateway(upstream, llm_stream=True, llm_response_mode="json_object")
        async with app.router.lifespan_context(app), ProviderClient(transport=httpx.ASGITransport(app=app)) as client:
            ok = await client.generate([{"role": "user", "content": "ok"}], 300, None)
            assert ok.content == '{"ok":true}'
            assert (ok.usage.input_tokens, ok.usage.output_tokens, ok.usage.request_id) == (20, 7, "req-3")

            with pytest.raises(ModelError) as truncated:
                await client.generate([{"role": "user", "content": "truncated"}], 300, None)
            assert truncated.value.code == "MODEL_TRUNCATED" and truncated.value.usage.output_tokens == 5

            with pytest.raises(ModelError) as missing:
                await client.generate([{"role": "user", "content": "missing-usage"}], 300, None)
            assert missing.value.code == "MODEL_USAGE_MISSING" and missing.value.uncertain

    asyncio.run(check())


def test_malformed_choice_with_usage_preserves_usage_and_is_not_uncertain(monkeypatch):
    monkeypatch.setattr(settings(), "provider_gateway_token", TOKEN)

    def upstream(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "replacement-model", "max_output_tokens": 500}]})
        body = json.loads(request.content)
        scenario = body["messages"][0]["content"]
        if body.get("stream"):
            if scenario == "sse-malformed":
                sse = (
                    'data: {"id":"req-sse-bad","choices":[],"usage":{"prompt_tokens":25,"completion_tokens":5}}\n\n'
                    'data: {"id":"req-sse-bad","choices":123}\n\n'
                )
                return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=sse.encode())
            if scenario == "sse-bad-delta":
                sse = (
                    'data: {"id":"req-sse-bad-delta","choices":[],"usage":{"prompt_tokens":25,"completion_tokens":5}}\n\n'
                    'data: {"id":"req-sse-bad-delta","choices":[{"delta":"not-an-object"}]}\n\n'
                )
                return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=sse.encode())
            if scenario == "sse-null-delta-ok":
                sse = (
                    'data: {"id":"req-sse-null-delta","choices":[{"delta":{"content":"{}"}}]}\n\n'
                    'data: {"id":"req-sse-null-delta","choices":[{"finish_reason":"stop","delta":null}],"usage":{"prompt_tokens":11,"completion_tokens":3}}\n\n'
                    "data: [DONE]\n\n"
                )
                return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=sse.encode())
            sse = (
                'data: {"id":"req-sse-empty","choices":[],"usage":{"prompt_tokens":25,"completion_tokens":5}}\n\n'
                "data: [DONE]\n\n"
            )
            return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=sse.encode())
        if scenario == "empty-choices":
            return httpx.Response(
                200,
                json={"id": "req-empty-choices", "choices": [], "usage": {"prompt_tokens": 25, "completion_tokens": 5}},
            )
        if scenario == "null-message":
            return httpx.Response(
                200,
                json={
                    "id": "req-null-message",
                    "choices": [{"message": None}],
                    "usage": {"prompt_tokens": 25, "completion_tokens": 5},
                },
            )
        if scenario == "null-choice":
            return httpx.Response(
                200,
                json={
                    "id": "req-null-choice",
                    "choices": [None],
                    "usage": {"prompt_tokens": 25, "completion_tokens": 5},
                },
            )
        if scenario == "non-list-choices":
            return httpx.Response(
                200,
                json={
                    "id": "req-non-list-choices",
                    "choices": "oops",
                    "usage": {"prompt_tokens": 25, "completion_tokens": 5},
                },
            )
        return httpx.Response(
            200,
            json={"id": "req-missing-message", "choices": [{}], "usage": {"prompt_tokens": 30, "completion_tokens": 6}},
        )

    async def check():
        non_stream_app = gateway(upstream, llm_stream=False, llm_response_mode="json_object")
        async with (
            non_stream_app.router.lifespan_context(non_stream_app),
            ProviderClient(transport=httpx.ASGITransport(app=non_stream_app)) as client,
        ):
            with pytest.raises(ModelError) as empty_err:
                await client.generate([{"role": "user", "content": "empty-choices"}], 300, None)
            assert empty_err.value.code == "MODEL_PROTOCOL"
            assert not empty_err.value.uncertain
            assert (
                empty_err.value.usage.input_tokens,
                empty_err.value.usage.output_tokens,
                empty_err.value.usage.request_id,
            ) == (25, 5, "req-empty-choices")

            with pytest.raises(ModelError) as missing_msg_err:
                await client.generate([{"role": "user", "content": "missing-message"}], 300, None)
            assert missing_msg_err.value.code == "MODEL_PROTOCOL"
            assert not missing_msg_err.value.uncertain
            assert (
                missing_msg_err.value.usage.input_tokens,
                missing_msg_err.value.usage.output_tokens,
                missing_msg_err.value.usage.request_id,
            ) == (30, 6, "req-missing-message")

            for name, expected_id in [
                ("null-message", "req-null-message"),
                ("null-choice", "req-null-choice"),
                ("non-list-choices", "req-non-list-choices"),
            ]:
                with pytest.raises(ModelError) as bad_err:
                    await client.generate([{"role": "user", "content": name}], 300, None)
                assert bad_err.value.code == "MODEL_PROTOCOL"
                assert not bad_err.value.uncertain
                assert (
                    bad_err.value.usage.input_tokens,
                    bad_err.value.usage.output_tokens,
                    bad_err.value.usage.request_id,
                ) == (25, 5, expected_id)

        stream_app = gateway(upstream, llm_stream=True, llm_response_mode="json_object")
        async with (
            stream_app.router.lifespan_context(stream_app),
            ProviderClient(transport=httpx.ASGITransport(app=stream_app)) as client,
        ):
            with pytest.raises(ModelError) as sse_err:
                await client.generate([{"role": "user", "content": "sse-empty"}], 300, None)
            assert sse_err.value.code == "MODEL_EMPTY"
            assert not sse_err.value.uncertain
            assert (
                sse_err.value.usage.input_tokens,
                sse_err.value.usage.output_tokens,
                sse_err.value.usage.request_id,
            ) == (25, 5, "req-sse-empty")

            for name, expected_id in [("sse-malformed", "req-sse-bad"), ("sse-bad-delta", "req-sse-bad-delta")]:
                with pytest.raises(ModelError) as sse_bad_err:
                    await client.generate([{"role": "user", "content": name}], 300, None)
                assert sse_bad_err.value.code == "MODEL_PROTOCOL"
                assert not sse_bad_err.value.uncertain
                assert (
                    sse_bad_err.value.usage.input_tokens,
                    sse_bad_err.value.usage.output_tokens,
                    sse_bad_err.value.usage.request_id,
                ) == (25, 5, expected_id)

            null_delta_ok = await client.generate([{"role": "user", "content": "sse-null-delta-ok"}], 300, None)
            assert null_delta_ok.content == "{}"
            assert (
                null_delta_ok.usage.input_tokens,
                null_delta_ok.usage.output_tokens,
                null_delta_ok.usage.request_id,
            ) == (11, 3, "req-sse-null-delta")

    asyncio.run(check())


def test_streaming_interrupt_or_timeout_preserves_known_usage(monkeypatch):
    monkeypatch.setattr(settings(), "provider_gateway_token", TOKEN)

    class BrokenStream(httpx.AsyncByteStream):
        def __init__(self, first_chunk: bytes, exc_factory):
            self.first_chunk = first_chunk
            self.exc_factory = exc_factory

        async def __aiter__(self):
            yield self.first_chunk
            raise self.exc_factory()

    def upstream(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "replacement-model", "max_output_tokens": 500}]})
        scenario = json.loads(request.content)["messages"][0]["content"]
        if scenario == "read-error-with-usage":
            chunk = b'data: {"id":"req-sse-read-err","choices":[{"delta":{"content":"{"}}],"usage":{"prompt_tokens":25,"completion_tokens":5}}\n\n'
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                stream=BrokenStream(chunk, lambda: httpx.ReadError("stream reset", request=request)),
            )
        if scenario == "read-timeout-with-usage":
            chunk = b'data: {"id":"req-sse-timeout","choices":[{"delta":{"content":"{"}}],"usage":{"prompt_tokens":25,"completion_tokens":5}}\n\n'
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                stream=BrokenStream(chunk, lambda: httpx.ReadTimeout("stream timed out", request=request)),
            )
        chunk = b'data: {"id":"req-sse-no-usage","choices":[{"delta":{"content":"{"}}]}\n\n'
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            stream=BrokenStream(chunk, lambda: httpx.ReadError("stream reset before usage", request=request)),
        )

    async def check():
        stream_app = gateway(upstream, llm_stream=True, llm_response_mode="json_object")
        async with (
            stream_app.router.lifespan_context(stream_app),
            ProviderClient(transport=httpx.ASGITransport(app=stream_app)) as client,
        ):
            with pytest.raises(ModelError) as net_err:
                await client.generate([{"role": "user", "content": "read-error-with-usage"}], 300, None)
            assert net_err.value.code == "MODEL_NETWORK"
            assert not net_err.value.uncertain
            assert (
                net_err.value.usage.input_tokens,
                net_err.value.usage.output_tokens,
                net_err.value.usage.request_id,
            ) == (25, 5, "req-sse-read-err")

            with pytest.raises(ModelError) as timeout_err:
                await client.generate([{"role": "user", "content": "read-timeout-with-usage"}], 300, None)
            assert timeout_err.value.code == "MODEL_TIMEOUT"
            assert not timeout_err.value.uncertain
            assert (
                timeout_err.value.usage.input_tokens,
                timeout_err.value.usage.output_tokens,
                timeout_err.value.usage.request_id,
            ) == (25, 5, "req-sse-timeout")

            with pytest.raises(ModelError) as missing_err:
                await client.generate([{"role": "user", "content": "read-error-without-usage"}], 300, None)
            assert missing_err.value.code == "MODEL_NETWORK"
            assert missing_err.value.uncertain
            assert missing_err.value.usage is None

    asyncio.run(check())


@pytest.mark.parametrize("has_usage", [True, False])
def test_total_generation_timeout_preserves_usage_and_settles_wallet(client, monkeypatch, has_usage):
    from conftest import create_project, submit

    from atoms.core.db import one, transaction
    from atoms.runtime import worker
    from atoms.runtime.model import Prepared

    monkeypatch.setattr(settings(), "provider_gateway_token", TOKEN)
    project = create_project(client)
    assert submit(client, project["id"]).status_code == 202
    run = worker.claim("test-leader")
    stopped_streams = []

    class StalledStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            chunk = {"id": "req-total-timeout", "choices": [{"delta": {"content": "{"}}]}
            if has_usage:
                chunk["usage"] = {"prompt_tokens": 25, "completion_tokens": 5}
            try:
                yield ("data: " + json.dumps(chunk) + "\n\n").encode()
                await asyncio.Event().wait()
            finally:
                stopped_streams.append(True)

    def upstream(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "replacement-model", "max_output_tokens": 500}]})
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=StalledStream())

    async def check():
        app = gateway(upstream, llm_stream=True)
        async with app.router.lifespan_context(app), ProviderClient(transport=httpx.ASGITransport(app=app)) as provider:

            async def generate(prepared, limit, *, run_id=None):
                return await provider.generate(prepared.messages, limit, None, run_id=run_id, timeout_seconds=1)

            monkeypatch.setattr(worker, "generate", generate)
            with pytest.raises(ModelError) as caught:
                await worker.paid_request(run, 1, Prepared(MESSAGES, 2000, 300))
            assert caught.value.code == "MODEL_TIMEOUT"
            if has_usage:
                assert not caught.value.uncertain
                usage = caught.value.usage
                assert (usage.input_tokens, usage.output_tokens, usage.request_id) == (25, 5, "req-total-timeout")
            else:
                assert caught.value.uncertain
                assert caught.value.usage is None

    asyncio.run(check())
    assert stopped_streams == [True]
    wallet = client.get("/api/v1/wallet").json()
    with transaction() as conn:
        call = one(conn, "SELECT status, provider_request_id FROM model_calls WHERE run_id=:id", id=run["id"])
    if has_usage:
        assert wallet["spent"] == "0.000900" and wallet["held_units"] == 0
        assert call == {"status": "settled", "provider_request_id": "req-total-timeout"}
    else:
        assert wallet["spent"] == "0.000000" and wallet["held_units"] == 64000
        assert call == {"status": "uncertain", "provider_request_id": None}
