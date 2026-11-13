import asyncio
import json
import logging
import re
import signal
import time
from contextlib import nullcontext
from hashlib import sha256
import httpx
from .config import settings
from .db import transaction,execute,one,all_rows,compact,add_event,maintenance
from .security import uid
from .artifacts import normalize_artifact,strict_json
from .exchange_rates import RATES_FILE, reference_rates, wants_exchange_rates
from .editorial_feed import NEWS_FILE, editorial_snapshot, has_editorial_snapshot, wants_editorial_feed
from .website_starters import MEDIA_FILE, match_website_starter
from .model import generate,prepare,prepare_decision,ModelError
from .orchestration import FPS_COVER_FILE, PLAN_FILE, TaskPlan, enforce_plan, game_dimension, game_reference, has_threejs, parse_decision, requests_fps
from .skills import skill_for
from .game_scenes import scene_direction
from .game_benchmarks import BENCHMARKS, match_genre
from .game_research import RESEARCH_FILE, find_game_references
from .slide_templates import slide_template_reference
from .slide_decks import render_slide_deck
from .credits import reserve_call,settle_call,finish_unbilled,mark_run_uncertain,CreditError

log=logging.getLogger("atoms.worker")
MAX_REPAIR_ROUNDS = 3
MAX_DECISION_ATTEMPTS = 3
VALIDATOR_RETRY_DELAYS = (1, 3, 8)
GAME_REVIEW_TIMEOUT = 25
GAME_REVIEW_SOURCE_LIMIT = 100_000
QUALITY_REPAIR_TIMEOUT = 120


class LeaseLost(Exception):
    pass


def fail_locked(conn,run,status,code,message):
    if run["status"] not in {"pending","running"}:
        return
    now=time.time()
    mark_run_uncertain(conn,run["id"],code)
    from .media_credits import finish_run
    finish_run(conn,run["id"],code)
    execute(conn,"UPDATE runs SET status=:status,stage=:status,error_code=:code,error_message=:message,finished_at=:now,lease_until=NULL WHERE id=:id",
            status=status,code=code,message=message[:1200],now=now,id=run["id"])
    execute(conn,"UPDATE projects SET active_run_id=NULL,updated_at=:now WHERE id=:pid AND active_run_id=:rid",
            now=now,pid=run["project_id"],rid=run["id"])
    execute(conn,"INSERT INTO messages(id,project_id,run_id,role,content,created_at) VALUES(:id,:pid,:rid,'assistant',:message,:now)",
            id=uid(),pid=run["project_id"],rid=run["id"],message=message[:1200],now=now)
    add_event(conn,run["id"],status,{"code":code,"message":message[:1200]})


def recover_expired():
    now=time.time()
    with transaction(True) as conn:
        rows=all_rows(conn,"SELECT * FROM runs WHERE (status='running' AND (lease_until<:now OR started_at<:deadline)) OR (status='pending' AND created_at<:pending)",now=now,deadline=now-settings().run_timeout_seconds,pending=now-settings().pending_timeout_seconds)
        for row in rows:
            timeout=row["status"]=="pending" or row["started_at"]<now-settings().run_timeout_seconds
            fail_locked(conn,row,"failed" if timeout else "interrupted","TIMEOUT" if timeout else "WORKER_LOST",
                        "任务超过时限，请重试；上一可用版本已保留" if timeout else "生成服务已中断，请重试；上一可用版本已保留")


def acquire_leader(token):
    now=time.time()
    with transaction(True) as conn:
        row=one(conn,"SELECT * FROM worker_status WHERE id=1")
        if row["lease_until"]>now and row["lease_token"]!=token:
            return False
        execute(conn,"UPDATE worker_status SET lease_token=:token,lease_until=:until,heartbeat_at=:now,state='idle',model_configured=:configured WHERE id=1",
                token=token,until=now+30,now=now,configured=int(settings().model_configured))
        return True


def heartbeat(token, active_leases=()):
    now=time.time()
    with transaction(True) as conn:
        row=one(conn,"SELECT * FROM worker_status WHERE id=1")
        if row["lease_token"]!=token or row["lease_until"]<=now:
            raise LeaseLost()
        execute(conn,"UPDATE worker_status SET lease_until=:until,heartbeat_at=:now,state=:state,model_configured=:configured WHERE id=1",
                until=now+30,now=now,state="busy" if active_leases else "idle",configured=int(settings().model_configured))
        for run_id, run_token in active_leases:
            execute(conn,"""UPDATE runs SET lease_until=:until WHERE id=:id AND lease_token=:token
                AND status='running' AND lease_until>:now AND started_at>:deadline""",
                until=now+30,id=run_id,token=run_token,now=now,deadline=now-settings().run_timeout_seconds)


def guard(run,token):
    now=time.time()
    if not run or run["status"]!="running" or run["lease_token"]!=token or run["lease_until"]<=now or run["started_at"]+settings().run_timeout_seconds<=now:
        raise LeaseLost()


def claim(token):
    now=time.time()
    with transaction(True) as conn:
        leader=one(conn,"SELECT * FROM worker_status WHERE id=1")
        if leader["lease_token"]!=token or leader["lease_until"]<=now:
            raise LeaseLost()
        if maintenance(conn) or not (settings().model_configured or settings().video_configured):
            return None
        row=one(conn,"""SELECT r.* FROM runs r JOIN projects p ON p.id=r.project_id WHERE r.status='pending'
            AND ((p.kind='video' AND :video=1) OR (p.kind!='video' AND :code=1)) ORDER BY r.created_at,r.id LIMIT 1""",
            video=int(settings().video_configured),code=int(settings().model_configured))
        if not row:
            return None
        lease=uid()
        execute(conn,"UPDATE runs SET status='running',stage='read_context',started_at=:now,lease_token=:token,lease_until=:until WHERE id=:id AND status='pending'",now=now,token=lease,until=leader["lease_until"],id=row["id"])
        add_event(conn,row["id"],"read_context",{"message":"读取基础版本与项目上下文"})
        return one(conn,"SELECT * FROM runs WHERE id=:id",id=row["id"])


def stage(rid,token,name,message):
    with transaction(True) as conn:
        run=one(conn,"SELECT * FROM runs WHERE id=:id",id=rid)
        guard(run,token)
        execute(conn,"UPDATE runs SET stage=:stage WHERE id=:id",stage=name,id=rid)
        add_event(conn,rid,name,{"message":message})


def read_context(run):
    with transaction() as conn:
        project=one(conn,"SELECT * FROM projects WHERE id=:id",id=run["project_id"])
        base=None
        if run["base_version_id"]:
            version=one(conn,"SELECT a.raw_json FROM versions v JOIN artifacts a ON v.artifact_id=a.id WHERE v.id=:id",id=run["base_version_id"])
            base=json.loads(version["raw_json"])
        messages=all_rows(conn,"SELECT role,content FROM messages WHERE project_id=:id AND run_id!=:rid ORDER BY created_at DESC LIMIT 6",id=run["project_id"],rid=run["id"])
        resume=None
        if run.get("retry_of_run_id"):
            source=one(conn,"""SELECT r.error_message,c.raw_content,c.diagnostics,c.attempt
                FROM runs r LEFT JOIN run_candidates c ON c.run_id=r.id
                WHERE r.id=:id AND r.project_id=:pid AND r.owner_id=:owner""",
                id=run["retry_of_run_id"],pid=run["project_id"],owner=run["owner_id"])
            if source:
                resume={"candidate":source["raw_content"],"diagnostics":source["diagnostics"] or source["error_message"] or "上次构建未完成",
                        "attempt":source["attempt"] or 0}
    context = {"project_title":project["title"],"project_kind":project["kind"],"request":run["prompt"],
               "base_artifact":base,"recent_messages":list(reversed(messages)),
               "continuing_failed_build":bool(run.get("retry_of_run_id")),"_resume":resume}
    if base is None:
        template = slide_template_reference(project["slide_template_id"])
        if template:
            context["slide_template"] = template
    return context


def keep_candidate(run,raw,diagnostics,attempt):
    now=time.time()
    with transaction(True) as conn:
        guard(one(conn,"SELECT * FROM runs WHERE id=:id",id=run["id"]),run["lease_token"])
        execute(conn,"""INSERT INTO run_candidates(run_id,raw_content,diagnostics,attempt,created_at,updated_at)
            VALUES(:id,:raw,:diagnostics,:attempt,:now,:now)
            ON CONFLICT(run_id) DO UPDATE SET raw_content=excluded.raw_content,
            diagnostics=excluded.diagnostics,attempt=excluded.attempt,updated_at=excluded.updated_at""",
            id=run["id"],raw=raw,diagnostics=diagnostics[:2000],attempt=attempt,now=now)


def commit(run,artifact,validation):
    now=time.time()
    with transaction(True) as conn:
        current=one(conn,"SELECT * FROM runs WHERE id=:id",id=run["id"])
        guard(current,run["lease_token"])
        project=one(conn,"SELECT * FROM projects WHERE id=:id",id=run["project_id"])
        if project["active_run_id"]!=run["id"] or project["revision"]!=run["expected_revision"] or project["current_version_id"]!=run["base_version_id"]:
            raise ModelError("COMMIT_CONFLICT","项目基础版本已变化，未覆盖现有版本")
        compiled=validation["compiled"]
        aid,vid=uid(),uid()
        number=one(conn,"SELECT COALESCE(MAX(number),0)+1 n FROM versions WHERE project_id=:id",id=run["project_id"])["n"]
        execute(conn,"INSERT INTO artifacts(id,raw_json,compiled_json,digest,compiler_version,sdk_version,validation_json,created_at) VALUES(:id,:raw,:compiled,:digest,:compiler,:sdk,:report,:now)",
                id=aid,raw=compact(artifact),compiled=compact(compiled),digest=compiled["digest"],compiler=compiled["compiler_version"],sdk=compiled["sdk_version"],report=compact(validation["report"]),now=now)
        execute(conn,"INSERT INTO versions(id,project_id,number,artifact_id,parent_version_id,source_run_id,title,summary,created_at) VALUES(:id,:pid,:number,:artifact,:parent,:run,:title,:summary,:now)",
                id=vid,pid=run["project_id"],number=number,artifact=aid,parent=run["base_version_id"],run=run["id"],title=artifact["title"],summary=artifact["summary"],now=now)
        execute(conn,"UPDATE projects SET current_version_id=:vid,revision=revision+1,active_run_id=NULL,title=:title,updated_at=:now WHERE id=:id",
                vid=vid,title=artifact["title"] if not run["base_version_id"] else project["title"],now=now,id=run["project_id"])
        execute(conn,"UPDATE runs SET status='succeeded',stage='completed',result_version_id=:vid,finished_at=:now,lease_until=NULL WHERE id=:id",vid=vid,now=now,id=run["id"])
        execute(conn,"INSERT INTO messages(id,project_id,run_id,role,content,created_at) VALUES(:id,:pid,:rid,'assistant',:summary,:now)",
                id=uid(),pid=run["project_id"],rid=run["id"],summary=artifact["summary"],now=now)
        add_event(conn,run["id"],"completed",{"version_id":vid,"version_number":number,"message":artifact["summary"]})
        execute(conn,"DELETE FROM run_candidates WHERE run_id=:id",id=run["id"])


def fail(run,code,message,status="failed"):
    with transaction(True) as conn:
        current=one(conn,"SELECT * FROM runs WHERE id=:id",id=run["id"])
        guard(current,run["lease_token"])
        fail_locked(conn,current,status,code,message)


async def paid_generate(run,context,repair,*,skill):
    prepared=await prepare(context,repair,skill=skill)
    return await paid_request(run,await asyncio.to_thread(next_call_attempt,run),prepared)


def next_call_attempt(run):
    with transaction() as conn:
        return one(conn,"SELECT COALESCE(MAX(attempt),0)+1 n FROM model_calls WHERE run_id=:id",id=run["id"])["n"]


async def agent_decision(run,role,context):
    for _ in range(1 if role == "reviewer" else MAX_DECISION_ATTEMPTS):
        prepared=await prepare_decision(role,context)
        try:
            raw=await paid_request(run,await asyncio.to_thread(next_call_attempt,run),prepared)
            return parse_decision(role,strict_json(raw))
        except ValueError as error:
            feedback="上一轮的决策 JSON 不符合约定。按给定结构修正后重新提交。"+str(error)[:500]
        except ModelError as error:
            if not recoverable_model_output(error):
                raise
            feedback=str(error)
        context={**context,"decision_feedback":feedback}
    raise ModelError("AGENT_RESPONSE_INVALID","规划或审核服务未返回可用的决策")


def recoverable_model_output(error):
    return not error.uncertain and error.code in {"MODEL_EMPTY","MODEL_TRUNCATED","MODEL_PROTOCOL"}


async def paid_request(run,attempt,prepared):
    call=await asyncio.to_thread(reserve_call,run,attempt,prepared.input_ceiling,prepared.output_limit)
    try:
        result=await generate(prepared,call["output_limit"])
    except ModelError as e:
        if e.usage:
            await asyncio.to_thread(settle_call,call,e.usage.input_tokens,e.usage.output_tokens,e.usage.request_id)
        else:
            await asyncio.to_thread(finish_unbilled,call,e.code,e.uncertain)
        raise
    except asyncio.CancelledError:
        await asyncio.shield(asyncio.to_thread(finish_unbilled,call,"CALL_INTERRUPTED",True))
        raise
    except Exception:
        await asyncio.to_thread(finish_unbilled,call,"CALL_UNKNOWN",True)
        raise
    await asyncio.to_thread(settle_call,call,result.usage.input_tokens,result.usage.output_tokens,result.usage.request_id)
    return result.content


def recent_game_scenes(run):
    with transaction() as conn:
        rows=all_rows(conn,"""SELECT a.raw_json FROM projects p JOIN versions v ON v.id=p.current_version_id
            JOIN artifacts a ON a.id=v.artifact_id WHERE p.owner_id=:owner AND p.kind='game' AND p.id!=:project
            ORDER BY p.created_at DESC LIMIT 12""",owner=run["owner_id"],project=run["project_id"])
    return [json.loads(row["raw_json"])["files"] for row in rows]


async def validate_candidate(run,raw,attempt,*,slide_template=None,react=False,site_files=None,website_starter=None,preview_kind="web",retain=True):
    rid,token=run["id"],run["lease_token"]
    if len(raw.encode())>32*1024*1024:
        raise ValueError("代码超过传输资源保护")
    # Save before parsing or starting a browser so failure/restart retains the work.
    if retain:
        await asyncio.to_thread(keep_candidate,run,raw,"",attempt)
    message = "重新检查保留的代码，不重复生成" if attempt==0 else "检查 JSON 格式和产物契约"
    await asyncio.to_thread(stage,rid,token,"validating",message)
    try:
        artifact=strict_json(raw)
        if not isinstance(artifact,dict):
            raise ValueError("产物必须是完整 JSON 对象")
        rendered_deck=bool(slide_template and (attempt>0 or "slides" in artifact))
        artifact=render_slide_deck(artifact,slide_template) if rendered_deck else normalize_artifact(artifact)
        if react and (attempt>0 or website_starter) and artifact.get("schema_version")=="1":
            raise ValueError("此项目需要 schema_version 2 和 React TSX 源码")
        files=artifact.get("files")
        if artifact.get("schema_version")=="2" and isinstance(files,dict):
            # Platform data overrides model output at these known paths.
            files.pop(RATES_FILE,None)
            files.pop(MEDIA_FILE,None)
            files.update(site_files or {})
        game=preview_kind=="game"
        if game and artifact.get("schema_version")=="2" and isinstance(files,dict):
            sources="\n".join(source for path,source in files.items() if path.endswith((".ts",".tsx")) and isinstance(source,str))
            if FPS_COVER_FILE not in files and re.search(r"['\"][^'\"\n]*shot-cover(?:\.ts)?['\"]",sources):
                files[FPS_COVER_FILE]=game_reference("first-person")["files"][FPS_COVER_FILE]
        lightweight_3d=game and has_threejs(artifact)
        await asyncio.to_thread(stage,rid,token,"browser_check","检查预览和主要操作")
        timeout=65 if lightweight_3d else 23
        async with httpx.AsyncClient(timeout=timeout,trust_env=False) as client:
            response=await client.post(settings().validator_url+"/internal/validate",
                headers={"Authorization":"Bearer "+settings().service_token},
                json={"artifact":artifact,"app_origin":settings().app_origin,"request_id":rid,
                      "lightweight_3d":lightweight_3d,"preview_kind":preview_kind})
            response.raise_for_status()
            validation=response.json()
        if not validation.get("ok"):
            diagnostic=validation.get("error","产物未通过检查")
            # During a rolling update an older validator still returns these service errors as 200.
            if diagnostic in {"浏览器效果验收超时", "隔离浏览器进程未正常完成", "隔离浏览器无法启动，请检查 Chromium 系统沙箱配置"}:
                if retain:
                    await asyncio.to_thread(keep_candidate,run,raw,diagnostic,attempt)
                raise ModelError("VALIDATOR_UNAVAILABLE","浏览器检查暂不可用，已保留本次代码")
            raise ValueError(diagnostic)
        if validation.get("report",{}).get("acceptance")!="smoke" or not validation["report"].get("ready"):
            raise ModelError("VALIDATOR_UNAVAILABLE","启动检查未完成，已保留本次代码")
        if rendered_deck:
            validation["report"]["slide_renderer"]="template-deck-v1"
        if website_starter:
            validation["report"]["website_starter"] = website_starter["id"]
        return artifact,validation
    except (ValueError,TypeError,KeyError) as e:
        diagnostics=str(e)[:2000]
        if retain:
            await asyncio.to_thread(keep_candidate,run,raw,diagnostics,attempt)
        raise ValueError(diagnostics) from None
    except httpx.HTTPError as error:
        if isinstance(error,httpx.HTTPStatusError) and error.response.status_code < 500 and error.response.status_code != 429:
            raise ModelError("VALIDATOR_REJECTED","校验服务无法接受请求，已保留本次构建内容") from None
        if retain:
            await asyncio.to_thread(keep_candidate,run,raw,"独立校验服务暂不可用",attempt)
        raise ModelError("VALIDATOR_UNAVAILABLE","独立校验服务暂不可用，请稍后继续；本次代码已保留") from None


async def validate_with_retry(run,raw,attempt,*,validator_slot=None,**options):
    async with validator_slot if validator_slot is not None else nullcontext():
        for delay in VALIDATOR_RETRY_DELAYS:
            try:
                return await validate_candidate(run,raw,attempt,**options)
            except ModelError as error:
                if error.code!="VALIDATOR_UNAVAILABLE":
                    raise
                await asyncio.to_thread(stage,run["id"],run["lease_token"],"validating","等待校验服务恢复，随后复查当前版本")
                await asyncio.sleep(delay)
        return await validate_candidate(run,raw,attempt,**options)


async def deliver(run,artifact,validation):
    await asyncio.to_thread(stage,run["id"],run["lease_token"],"committing","保存代码快照和新版本")
    await asyncio.to_thread(commit,run,artifact,validation)


async def review_game(run, context, artifact, smoke):
    files = {path: source for path, source in artifact["files"].items()
             if path.endswith((".html", ".js", ".ts", ".tsx", ".css"))}
    if sum(len(source) for source in files.values()) > GAME_REVIEW_SOURCE_LIMIT:
        return {"status":"unavailable","reason":"source_budget"}
    try:
        async with asyncio.timeout(GAME_REVIEW_TIMEOUT):
            review = await agent_decision(run,"reviewer",{
                "request":context["request"],
                "task_plan":context.get("task_plan"),
                "browser_evidence":smoke,
                "artifact":{"files":files},
            })
    except (TimeoutError, ModelError, CreditError) as error:
        log.info("Game review unavailable for %s: %s",run["id"],getattr(error,"code",type(error).__name__))
        return {"status":"unavailable"}
    findings = [finding.model_dump() for finding in review.findings
                if finding.path in files and finding.excerpt in files[finding.path]]
    if not review.accepted and findings:
        return {"status":"issue","findings":findings}
    return {"status":"no_issue" if review.accepted and not review.findings else "unconfirmed"}


def quality_feedback(report):
    smoke = report.get("smoke",{})
    if smoke.get("status") == "issue":
        return smoke["diagnostic"]
    return "\n".join(
        f'{item["path"]}: {item["problem"]}\n相关源码: {item["excerpt"]}'
        for item in report.get("source_review",{}).get("findings",[])
    )


async def execute_run(run, *, validator_slot=None):
    rid,token=run["id"],run["lease_token"]
    context=await asyncio.to_thread(read_context,run)
    if context["project_kind"]=="video":
        from .video import execute_video
        artifact,validation=await execute_video(run,context)
        await asyncio.to_thread(commit,run,artifact,validation)
        return
    resume=context.pop("_resume",None)
    skill=skill_for(context["project_kind"])
    slide_template=context.get("slide_template")
    base=context["base_artifact"]
    fps_request=requests_fps(context)
    game=context["project_kind"]=="game"
    dimension=game_dimension(context) if game else None
    react=context["project_kind"] in ("web","game") and (base is None or base.get("schema_version")=="2" or dimension=="3d")
    starter=None
    site_files={}
    if react:
        context["site_format"]="react"
    if react and context["project_kind"]=="web":
        starter=match_website_starter(context["request"]) if base is None else None
        if wants_exchange_rates(context["request"],base):
            rates=await reference_rates()
            context["exchange_rates"]=rates
            site_files[RATES_FILE]=compact(rates)
        base_files=(base or {}).get("files",{})
        if wants_editorial_feed(context["request"]) or has_editorial_snapshot(base_files.get(NEWS_FILE)):
            feed=await editorial_snapshot()
            context["editorial_feed"]=feed
            site_files[NEWS_FILE]=compact(feed)
        media=starter.media_for(context["request"]) if starter else base_files.get(MEDIA_FILE)
        if media:
            site_files[MEDIA_FILE]=media
            context["starter_media_keys"]=list(json.loads(media))
            if base:
                context["base_artifact"]={**base,"files":{name:source for name,source in base_files.items() if name!=MEDIA_FILE}}
        if starter:
            context["website_starter"]=starter.reference()
    website_starter=context.get("website_starter")
    validation_options={"preview_kind":context["project_kind"],"validator_slot":validator_slot,
                        "slide_template":slide_template,"react":react,"site_files":site_files,
                        "website_starter":website_starter}
    coordinated=react
    plan=None
    context["fps_required"]=fps_request
    if context["project_kind"]=="game":
        await asyncio.to_thread(stage,rid,token,"researching","查找同类热门游戏及玩法资料")
        genre="fps" if fps_request else match_genre(context["request"])
        if not genre and base:
            try:
                genre=strict_json(base.get("files",{}).get(PLAN_FILE,"{}")).get("game_genre")
            except (ValueError,AttributeError):
                pass
        research=await find_game_references(genre or "other")
        context["game_research"]=research
        if coordinated:
            site_files[RESEARCH_FILE]=json.dumps(research,ensure_ascii=False,indent=2)
        if base is None and not resume:
            previous_scenes=await asyncio.to_thread(recent_game_scenes,run)
            recent_directions=[]
            for files in previous_scenes:
                try:
                    direction=TaskPlan.model_validate_json(files.get(PLAN_FILE,"{}")).scene_direction
                except ValueError:
                    continue
                if direction:
                    recent_directions.append(direction)
            context["scene_direction"]=scene_direction(run["project_id"],genre,recent_directions)

    def apply_plan(value):
        nonlocal plan,skill
        plan=enforce_plan(value,context)
        if context.get("scene_direction") and not plan.scene_direction:
            plan=plan.model_copy(update={"scene_direction":context["scene_direction"]})
        context["task_plan"]=plan.model_dump()
        if game:
            skill=skill_for("game", threejs=plan.rendering=="threejs")
            context["fps_required"]=plan.experience=="first_person_3d"
        site_files[PLAN_FILE]=json.dumps(plan.model_dump(),ensure_ascii=False,indent=2)

    repair=None
    fallback=None
    quality_deadline=None
    if resume:
        repair=resume
        if resume.get("candidate"):
            try:
                retained=strict_json(resume["candidate"])
                retained_files=retained.get("files",{}) if isinstance(retained,dict) else {}
                if coordinated and isinstance(retained_files,dict) and retained_files.get(PLAN_FILE):
                    try:
                        saved_plan=TaskPlan.model_validate_json(retained_files[PLAN_FILE])
                    except (ValueError, TypeError):
                        saved_plan=None
                    if saved_plan:
                        apply_plan(saved_plan)
                artifact,validation=await validate_with_retry(run,resume["candidate"],0,**validation_options)
            except ValueError as e:
                repair={"candidate":resume["candidate"],"diagnostics":str(e)}
            else:
                if plan:
                    validation["report"]["task_plan"]=plan.model_dump()
                validation["report"]["generation_skill"]={"kind":skill.kind,"revision":skill.revision}
                await deliver(run,artifact,validation)
                return
    if coordinated and plan is None:
        await asyncio.to_thread(stage,rid,token,"planning","主 Agent 解析目标并规划实现")
        planning_context={name:value for name,value in context.items() if name not in ("website_starter","starter_media_keys")}
        if context["project_kind"]=="game":
            planning_context["game_dimension"]=dimension
            planning_context["game_benchmarks"]={genre:BENCHMARKS[genre]} if genre in BENCHMARKS else {}
        apply_plan(await agent_decision(run,"planner",planning_context))
    if plan and context["project_kind"]=="game" and plan.game_genre not in (None,"other",context["game_research"]["genre"]):
        research=await find_game_references(plan.game_genre)
        context["game_research"]=research
        site_files[RESEARCH_FILE]=json.dumps(research,ensure_ascii=False,indent=2)
    failed_candidates={}
    for repair_round in range(1 if repair else 0, MAX_REPAIR_ROUNDS + 1):
        attempt=repair_round+1
        await asyncio.to_thread(stage,rid,token,"repairing" if repair else "generating","建设中")
        if repair:
            repair={**repair,"round":repair_round}
        try:
            async with asyncio.timeout_at(quality_deadline):
                raw=await paid_generate(run,context,repair,skill=skill)
        except (ModelError, CreditError, TimeoutError) as error:
            if fallback:
                break
            if not isinstance(error,ModelError):
                raise
            if not recoverable_model_output(error) or repair_round==MAX_REPAIR_ROUNDS:
                raise
            repair={"candidate":(repair or {}).get("candidate"),"diagnostics":str(error)}
            continue
        if coordinated:
            try:
                candidate=strict_json(raw)
            except ValueError:
                candidate=None
            if isinstance(candidate,dict) and isinstance(candidate.get("files"),dict):
                candidate["files"][PLAN_FILE]=json.dumps(plan.model_dump(),ensure_ascii=False,indent=2)
                raw=compact(candidate)
        try:
            async with asyncio.timeout_at(quality_deadline):
                artifact,validation=await validate_with_retry(run,raw,attempt,retain=fallback is None,**validation_options)
        except (ModelError, TimeoutError):
            if fallback:
                break
            raise
        except (ValueError,TypeError,KeyError) as e:
            if fallback:
                break
            diagnostics=str(e)[:2000]
            previous=failed_candidates.setdefault(diagnostics,set())
            repeated=bool(previous)
            repair={"candidate":raw,"diagnostics":diagnostics,"repeated_failure":repeated}
            if repeated:
                repair["repair_strategy"]="根据具体错误定位构建、启动或操作失败的原因，换一种实现修复，保留已正常工作的功能。"
            await asyncio.to_thread(keep_candidate,run,raw,diagnostics,attempt)
            if repair_round==MAX_REPAIR_ROUNDS:
                raise ModelError("VALIDATION_FAILED","代码未通过校验："+str(e)[:1000]) from None
            fingerprint=sha256(raw.encode()).digest()
            if fingerprint in previous:
                raise ModelError("VALIDATION_FAILED","同一版本重复出现运行故障："+diagnostics[:1000]) from None
            previous.add(fingerprint)
            continue
        report = validation["report"]
        if fallback:
            original_report = fallback[1]["report"]
            if artifact["files"] == fallback[0]["files"] or quality_feedback(report):
                break
            if original_report.get("smoke",{}).get("status") == "issue" and report.get("smoke",{}).get("status") != "observed":
                break
            findings = original_report.get("source_review",{}).get("findings",[])
            if any(item["excerpt"] in artifact["files"].get(item["path"],"") for item in findings):
                break
            fallback = None
            report["quality_repair"] = "candidate_rechecked"
            break
        remaining = run["started_at"] + settings().run_timeout_seconds - time.time() - 5
        if game and repair_round < MAX_REPAIR_ROUNDS and remaining > GAME_REVIEW_TIMEOUT:
            report["source_review"] = await review_game(run,context,artifact,report.get("smoke",{}))
        feedback = quality_feedback(report)
        remaining = run["started_at"] + settings().run_timeout_seconds - time.time() - 5
        if not feedback or repair_round == MAX_REPAIR_ROUNDS or remaining <= 0:
            break
        fallback = (artifact,validation)
        quality_deadline = asyncio.get_running_loop().time() + min(QUALITY_REPAIR_TIMEOUT,remaining)
        repair = {"candidate":raw,"diagnostics":feedback,"quality_repair":True}
        continue
    if fallback:
        artifact,validation = fallback
        validation["report"]["quality_repair"] = "kept_runnable_candidate"
    if plan:
        validation["report"]["task_plan"]=plan.model_dump()
    validation["report"]["generation_skill"]={"kind":skill.kind,"revision":skill.revision}
    await deliver(run,artifact,validation)


async def finish_failed_run(run, code, message, status="failed"):
    try:
        await asyncio.to_thread(fail, run, code, message, status)
    except LeaseLost:
        # An expired lease is finalized by recover_expired, never by a stale executor.
        pass


async def run_in_slot(run, validator_slot):
    log.info("Run started %s", run["id"])
    try:
        async with asyncio.timeout(settings().run_timeout_seconds):
            await execute_run(run, validator_slot=validator_slot)
    except TimeoutError:
        await finish_failed_run(run, "TIMEOUT", "任务超过执行时限，请重试")
    except (ModelError, CreditError) as error:
        await finish_failed_run(run, error.code, str(error))
    except LeaseLost:
        pass
    except Exception:
        log.exception("Run failed unexpectedly %s", run["id"])
        await finish_failed_run(run, "INTERNAL_ERROR", "生成服务发生内部错误，上一可用版本已保留")


async def main():
    token = uid()
    while not await asyncio.to_thread(acquire_leader, token):
        await asyncio.sleep(5)
    stop=asyncio.Event()
    loop=asyncio.get_running_loop()
    for name in ("SIGINT","SIGTERM"):
        try:
            loop.add_signal_handler(getattr(signal,name),stop.set)
        except NotImplementedError:
            pass
    active = {}
    limit = settings().run_concurrency
    # The validator has one Chromium slot. Waiting here doesn't block model or video work.
    validator_slot = asyncio.Semaphore(1)

    async def pulse():
        while True:
            leases = tuple((run["id"], run["lease_token"]) for run in active.values())
            await asyncio.to_thread(heartbeat, token, leases)
            await asyncio.to_thread(recover_expired)
            await asyncio.sleep(5)

    pulse_task = asyncio.create_task(pulse())
    stopped = asyncio.create_task(stop.wait())
    log.info("Worker ready with %d generation slots", limit)
    try:
        while not stop.is_set():
            if pulse_task.done():
                await pulse_task
            while len(active) < limit and not stop.is_set() and not pulse_task.done():
                run = await asyncio.to_thread(claim, token)
                if run is None:
                    break
                task = asyncio.create_task(run_in_slot(run, validator_slot))
                active[task] = run
            done, _ = await asyncio.wait(
                [*active, pulse_task, stopped],
                timeout=None if len(active) == limit else .5,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done & active.keys():
                del active[task]
                await task
    finally:
        stopped.cancel()
        for task in active:
            task.cancel()
        try:
            await asyncio.gather(*active, return_exceptions=True)
            for run in active.values():
                await finish_failed_run(run, "WORKER_STOPPED", "生成服务停止，任务已中断", "interrupted")
        finally:
            pulse_task.cancel()
            await asyncio.gather(pulse_task, stopped, return_exceptions=True)
            with transaction(True) as conn:
                execute(conn,"UPDATE worker_status SET lease_until=0,state='offline' WHERE id=1 AND lease_token=:token",token=token)


if __name__=="__main__":
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(main())
