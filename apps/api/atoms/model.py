import asyncio
import json
from pathlib import Path
from dataclasses import dataclass
import time
from .config import settings
from .db import compact
from .prompts import messages_for
from .skills import GenerationSkill
from .slide_decks import DeckContent
from .provider_contract import ModelError, ModelResult, Usage
from .provider_client import ProviderClient

PLANNING_TIMEOUT = 45
GENERATION_TIMEOUT = 180
COMPLEX_GENERATION_TIMEOUT = 420

@dataclass(frozen=True)
class Prepared:
    messages: list
    input_ceiling: int
    output_limit: int
    slide_content: bool = False
    react_site: bool = False
    response_schema: dict | None = None
    timeout_seconds: int = GENERATION_TIMEOUT


async def native_output_limit():
    config = settings()
    if config.app_env == "test" and config.test_fixture:
        return 393216
    async with ProviderClient() as provider:
        return await provider.text_limit()


async def prepare(context, repair, *, skill: GenerationSkill):
    messages=messages_for(context, repair, skill=skill)
    # A conservative financial authorization, not actual token billing or a context truncation.
    input_ceiling=len(compact(messages).encode("utf-8"))+1024
    # Large requirements, source snapshots and repair candidates can take longer to regenerate.
    complex_build=len(context["request"])>=6000 or input_ceiling>=64_000
    return Prepared(messages,input_ceiling,await native_output_limit(),
                    slide_content=bool(context.get("slide_template")),react_site=context.get("site_format")=="react",
                    timeout_seconds=COMPLEX_GENERATION_TIMEOUT if complex_build else GENERATION_TIMEOUT)

async def prepare_plan(context: dict):
    from .orchestration import plan_contract, plan_messages

    messages=plan_messages(context)
    return Prepared(messages,len(compact(messages).encode("utf-8"))+1024,
                    min(4096,await native_output_limit()),response_schema=plan_contract(context).model_json_schema(),
                    timeout_seconds=PLANNING_TIMEOUT)


async def generate(prepared,output_tokens, *, run_id=None):
    config=settings()
    if config.app_env=="test" and config.test_fixture:
        from .model_fixture import test_artifact

        context=json.loads(prepared.messages[1]["content"])
        repair=json.loads(prepared.messages[2]["content"].split("\n",1)[1]) if len(prepared.messages)>2 else None
        await asyncio.sleep(8 if "[slow]" in context["request"] or ("[slow-build]" in context["request"] and not prepared.response_schema) else .25)
        if prepared.response_schema:
            from .model_fixture import test_plan
            raw=test_plan(context)
        else:
            raw=test_artifact(context,repair)
        return ModelResult(raw,Usage(1200,400,"fixture-"+str(time.time_ns())))
    if prepared.response_schema:
        name, schema = "planner", prepared.response_schema
    elif prepared.slide_content:
        name, schema = "slide_content", DeckContent.model_json_schema()
    else:
        name = "react_artifact" if prepared.react_site else "artifact"
        path = Path(__file__).resolve().parents[3] / "shared" / "contracts" / (name.replace("_", "-") + ".schema.json")
        schema = json.loads(path.read_text("utf-8"))
        schema.pop("$schema", None)
    async with ProviderClient() as provider:
        return await provider.generate(prepared.messages, output_tokens, {"name":name,"schema":schema},
                                       run_id=run_id, timeout_seconds=prepared.timeout_seconds)
