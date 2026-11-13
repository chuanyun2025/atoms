import asyncio
import json

import httpx
import pytest

from atoms import worker
from atoms.db import compact
from atoms.exchange_rates import RATES_FILE, parse_exchange_rates, wants_exchange_rates
from conftest import create_project, submit
from test_workflow import VALIDATION


def test_ecb_date_and_reference_values_are_kept():
    xml = b'''<Cube xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref"><Cube time="2026-11-11">
    <Cube currency="USD" rate="1.1127"/><Cube currency="CNY" rate="7.4225"/></Cube></Cube>'''
    snapshot = parse_exchange_rates(xml)
    assert snapshot["observed_on"] == "2026-11-11"
    assert snapshot["base"] == "EUR"
    assert snapshot["rates"] == [{"currency":"USD","rate":"1.1127"},{"currency":"CNY","rate":"7.4225"}]
    assert wants_exchange_rates("做个汇率看板", None)
    assert wants_exchange_rates("Build a forex dashboard", None)
    assert not wants_exchange_rates("做一个简单任务看板", None)


def test_missing_ecb_data_is_an_error():
    with pytest.raises(ValueError,match="缺少观察日期"):
        parse_exchange_rates(b"<empty/>")


def test_worker_supplies_authoritative_data_to_saved_react_sources(client,monkeypatch):
    project=create_project(client)
    assert submit(client,project["id"],"制作外汇网站").status_code==202
    run=worker.claim("test-leader")
    snapshot={"status":"available","source":"欧洲中央银行","base":"EUR","observed_on":"2026-11-11",
              "rates":[{"currency":"USD","rate":"1.1127"}]}

    async def rates():
        return snapshot

    async def generated(run,context,repair,**kwargs):
        assert context["site_format"]=="react"
        assert context["exchange_rates"]==snapshot
        return compact({"schema_version":"2","title":"测试","summary":"测试真实来源替换","files":{
            "src/App.tsx":"export default function App(){return <main/>}",
            "src/styles.css":"body{margin:0}",
            RATES_FILE:'{"rates":[{"currency":"USD","rate":"999"}]}',
        }})

    original=httpx.AsyncClient
    def validate(request):
        artifact=json.loads(request.content)["artifact"]
        assert json.loads(artifact["files"][RATES_FILE])==snapshot
        return httpx.Response(200,json=VALIDATION)
    monkeypatch.setattr(worker,"reference_rates",rates)
    monkeypatch.setattr(worker,"paid_generate",generated)
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs:original(transport=httpx.MockTransport(validate)))
    asyncio.run(worker.execute_run(run))

    project=client.get("/api/v1/projects/"+project["id"]).json()
    version=client.get("/api/v1/projects/"+project["id"]+"/versions/"+project["current_version_id"]).json()
    assert json.loads(version["artifact"]["files"][RATES_FILE])==snapshot
