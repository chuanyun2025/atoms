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

@dataclass(frozen=True)
class Prepared:
    messages: list
    input_ceiling: int
    output_limit: int
    slide_content: bool = False
    react_site: bool = False
    decision_role: str | None = None
    response_schema: dict | None = None


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
    return Prepared(messages,input_ceiling,await native_output_limit(),
                    slide_content=bool(context.get("slide_template")),react_site=context.get("site_format")=="react")

async def prepare_decision(role: str, context: dict):
    from .orchestration import TaskPlan, TaskReview, decision_messages

    messages=decision_messages(role,context)
    schema=(TaskPlan if role=="planner" else TaskReview).model_json_schema()
    return Prepared(messages,len(compact(messages).encode("utf-8"))+1024,
                    min(4096,await native_output_limit()),decision_role=role,response_schema=schema)


async def generate(prepared,output_tokens, *, run_id=None):
    config=settings()
    if config.app_env=="test" and config.test_fixture:
        from .model_fixture import test_artifact

        context=json.loads(prepared.messages[1]["content"])
        repair=json.loads(prepared.messages[2]["content"].split("\n",1)[1]) if len(prepared.messages)>2 else None
        slow_review=prepared.decision_role=="reviewer" and "[slow-review]" in context["request"]
        await asyncio.sleep(8 if "[slow]" in context["request"] or slow_review else .25)
        if prepared.decision_role:
            from .model_fixture import test_decision
            raw=test_decision(prepared.decision_role,context)
        else:
            raw=test_artifact(context,repair)
        return ModelResult(raw,Usage(1200,400,"fixture-"+str(time.time_ns())))
    if prepared.response_schema:
        name, schema = prepared.decision_role, prepared.response_schema
    elif prepared.slide_content:
        name, schema = "slide_content", DeckContent.model_json_schema()
    else:
        name = "react_artifact" if prepared.react_site else "artifact"
        path = Path(__file__).resolve().parents[3] / "shared" / "contracts" / (name.replace("_", "-") + ".schema.json")
        schema = json.loads(path.read_text("utf-8"))
        schema.pop("$schema", None)
    async with ProviderClient() as provider:
        return await provider.generate(prepared.messages, output_tokens, {"name":name,"schema":schema}, run_id=run_id)
