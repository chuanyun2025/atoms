import asyncio
import json
import logging
import re
import signal
import time
from contextlib import nullcontext
import httpx
from .config import settings
from .db import transaction,execute,one,all_rows,compact,add_event,maintenance
from .security import uid
from .service import USER_STOPPED,announce_version,write_version
from .validator_client import validate_artifact
from .artifacts import normalize_artifact,strict_json
from .build_diagnostics import BuildIssue, MODEL_OUTPUT_ERRORS, REPAIR_POLICIES
from .exchange_rates import RATES_FILE, reference_rates, wants_exchange_rates
from .editorial_feed import NEWS_FILE, editorial_snapshot, has_editorial_snapshot, wants_editorial_feed
from .website_starters import MEDIA_FILE, match_website_starter
from .model import generate,prepare,prepare_plan,ModelError
from .provider_client import ProviderClient
from .orchestration import FPS_COVER_FILE, PLAN_FILE, TaskPlan, enforce_plan, game_dimension, game_reference, has_threejs, parse_plan, requests_fps
from .skills import skill_for
from .game_scenes import scene_direction
from .game_benchmarks import BENCHMARKS, genre_preferences, match_genre
from .game_profiles import game_profile
from .game_research import RESEARCH_FILE, find_game_references
from .slide_templates import slide_template_reference
from .slide_decks import render_slide_deck
from .credits import reserve_call,start_call,settle_call,finish_unbilled,finish_model_calls,CreditError

log=logging.getLogger("atoms.worker")
MAX_REPAIR_ROUNDS = 10
MAX_DECISION_ATTEMPTS = 3
VALIDATOR_RETRY_DELAYS = (1, 3, 8)
MODEL_RETRY_DELAYS = (2, 5)
RETRYABLE_MODEL_SERVICE_ERRORS = {"MODEL_CONNECTION","MODEL_RATE_LIMIT","PROVIDER_RATE_LIMIT"}


class LeaseLost(Exception):
    pass


def fail_locked(conn,run,status,code,message):
    if run["status"] not in {"pending","running"}:
        return
    now=time.time()
    finish_model_calls(conn,run["id"],code)
    from .media_credits import finish_run
    finish_run(conn,run["id"],code)
    execute(conn,"UPDATE runs SET status=:status,stage=:status,error_code=:code,error_message=:message,finished_at=:now,lease_until=NULL WHERE id=:id",
            status=status,code=code,message=message[:1200],now=now,id=run["id"])
    execute(conn,"UPDATE projects SET active_run_id=NULL,updated_at=:now WHERE id=:pid AND active_run_id=:rid",
            now=now,pid=run["project_id"],rid=run["id"])
    execute(conn,"INSERT INTO messages(id,project_id,run_id,role,content,created_at) VALUES(:id,:pid,:rid,'assistant',:message,:now)",
            id=uid(),pid=run["project_id"],rid=run["id"],message=message[:1200],now=now)
    add_event(conn,run["id"],status,{"code":code,"message":message[:1200]})
    if code!=USER_STOPPED:
        execute(conn,"UPDATE run_workspace SET compiled_json=NULL,digest=NULL WHERE run_id=:id",id=run["id"])


def recover_expired():
    now=time.time()
    with transaction(True) as conn:
        rows=all_rows(conn,"SELECT * FROM runs WHERE (status='running' AND (lease_until<:now OR started_at<:deadline)) OR (status='pending' AND created_at<:pending)",now=now,deadline=now-settings().run_timeout_seconds,pending=now-settings().pending_timeout_seconds)
        for row in rows:
            if row["status"]=="pending":
                fail_locked(conn,row,"failed","QUEUE_TIMEOUT","排队超时，生成服务未领取任务，请重新生成")
                continue
            timeout=row["started_at"]<now-settings().run_timeout_seconds
            fail_locked(conn,row,"failed" if timeout else "interrupted","TIMEOUT" if timeout else "WORKER_LOST",
                        "任务超过时限，请重试；上一可用版本已保留" if timeout else "生成服务已中断，请重试；上一可用版本已保留")


def acquire_leader(token):
    now=time.time()
    with transaction(True) as conn:
        row=one(conn,"SELECT * FROM worker_status WHERE id=1")
        if row["lease_until"]>now and row["lease_token"]!=token:
            return False
        fixture=settings().test_fixture
        execute(conn,"""UPDATE worker_status SET lease_token=:token,lease_until=:until,heartbeat_at=:now,state='idle',
                model_configured=:fixture,video_configured=:fixture,text_model=:model WHERE id=1""",
                token=token,until=now+30,now=now,fixture=int(fixture),model="test-fixture-only" if fixture else None)
        return True


def heartbeat(token, active_leases=(), capabilities=None):
    now=time.time()
    with transaction(True) as conn:
        row=one(conn,"SELECT * FROM worker_status WHERE id=1")
        if row["lease_token"]!=token or row["lease_until"]<=now:
            raise LeaseLost()
        execute(conn,"UPDATE worker_status SET lease_until=:until,heartbeat_at=:now,state=:state WHERE id=1",
                until=now+30,now=now,state="busy" if active_leases else "idle")
        if capabilities is not None:
            execute(conn,"UPDATE worker_status SET model_configured=:text,video_configured=:video,text_model=:model WHERE id=1",
                    text=int(capabilities["text_configured"] is True),video=int(capabilities["video_configured"] is True),
                    model=capabilities.get("text_model"))
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
        if maintenance(conn) or not (leader["model_configured"] or leader["video_configured"]):
            return None
        row=one(conn,"""SELECT r.* FROM runs r JOIN projects p ON p.id=r.project_id WHERE r.status='pending'
            AND ((p.kind='video' AND :video=1) OR (p.kind!='video' AND :code=1)) ORDER BY r.created_at,r.id LIMIT 1""",
            video=leader["video_configured"],code=leader["model_configured"])
        if not row:
            return None
        lease=uid()
        execute(conn,"UPDATE runs SET status='running',stage='read_context',started_at=:now,lease_token=:token,lease_until=:until WHERE id=:id AND status='pending'",now=now,token=lease,until=leader["lease_until"],id=row["id"])
        add_event(conn,row["id"],"read_context",{"message":"读取基础版本与项目上下文"})
        return one(conn,"SELECT * FROM runs WHERE id=:id",id=row["id"])


def user_stopped_runs(run_ids):
    with transaction() as conn:
        rows=all_rows(conn,"""SELECT id FROM runs WHERE status='interrupted' AND error_code=:code
            AND id IN (SELECT value FROM json_each(:ids))""",code=USER_STOPPED,ids=compact(run_ids))
    return {row["id"] for row in rows}


def stage(rid,token,name,message,**details):
    with transaction(True) as conn:
        run=one(conn,"SELECT * FROM runs WHERE id=:id",id=rid)
        guard(run,token)
        execute(conn,"UPDATE runs SET stage=:stage WHERE id=:id",stage=name,id=rid)
        add_event(conn,rid,name,{"message":message,**details})


def read_context(run):
    with transaction() as conn:
        project=one(conn,"SELECT * FROM projects WHERE id=:id",id=run["project_id"])
        base=None
        if run["base_version_id"]:
            version=one(conn,"SELECT a.raw_json FROM versions v JOIN artifacts a ON v.artifact_id=a.id WHERE v.id=:id",id=run["base_version_id"])
            base=json.loads(version["raw_json"])
            if plan_source:=base.get("files",{}).get(PLAN_FILE):
                try:
                    base["files"][PLAN_FILE]=TaskPlan.model_validate_json(plan_source).model_dump_json()
                except (TypeError,ValueError):
                    pass
        messages=all_rows(conn,"SELECT role,content FROM messages WHERE project_id=:id AND run_id!=:rid ORDER BY created_at DESC LIMIT 6",id=run["project_id"],rid=run["id"])
        resume=None
        if run.get("retry_of_run_id"):
            source=one(conn,"""SELECT r.error_message,c.raw_content,c.diagnostics,c.attempt,w.source_json
                FROM runs r LEFT JOIN run_candidates c ON c.run_id=r.id
                LEFT JOIN run_workspace w ON w.run_id=r.id
                WHERE r.id=:id AND r.project_id=:pid AND r.owner_id=:owner""",
                id=run["retry_of_run_id"],pid=run["project_id"],owner=run["owner_id"])
            if source:
                resume={"candidate":source["raw_content"],"diagnostics":source["diagnostics"] or source["error_message"] or "上次构建未完成",
                        "attempt":source["attempt"] or 0,
                        "plan_source":json.loads(source["source_json"] or "{}").get("files",{}).get(PLAN_FILE)}
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


def publish_source(run, artifact):
    files = artifact.get("files")
    if not isinstance(files, dict) or not files or any(not isinstance(value, str) for value in files.values()):
        return
    source = compact({"schema_version":artifact.get("schema_version"),"files":files})
    with transaction(True) as conn:
        guard(one(conn,"SELECT * FROM runs WHERE id=:id",id=run["id"]),run["lease_token"])
        changed = execute(conn,"""INSERT INTO run_workspace(run_id,source_json,source_revision) VALUES(:id,:source,1)
            ON CONFLICT(run_id) DO UPDATE SET source_json=excluded.source_json,source_revision=run_workspace.source_revision+1
            WHERE run_workspace.source_json!=excluded.source_json""",id=run["id"],source=source)
        if changed.rowcount:
            add_event(conn,run["id"],"source_ready",{"message":"源码已可查看"})


def publish_preview(run, compiled):
    with transaction(True) as conn:
        guard(one(conn,"SELECT * FROM runs WHERE id=:id",id=run["id"]),run["lease_token"])
        changed = execute(conn,"""UPDATE run_workspace SET compiled_json=:compiled,digest=:digest
            WHERE run_id=:id AND digest IS NULL""",id=run["id"],compiled=compact(compiled),digest=compiled["digest"])
        if changed.rowcount:
            add_event(conn,run["id"],"preview_ready",{"message":"临时预览已可体验"})


def commit(run,artifact,validation):
    now=time.time()
    with transaction(True) as conn:
        current=one(conn,"SELECT * FROM runs WHERE id=:id",id=run["id"])
        guard(current,run["lease_token"])
        project=one(conn,"SELECT * FROM projects WHERE id=:id",id=run["project_id"])
        if project["active_run_id"]!=run["id"] or project["revision"]!=run["expected_revision"] or project["current_version_id"]!=run["base_version_id"]:
            raise ModelError("COMMIT_CONFLICT","项目基础版本已变化，未覆盖现有版本")
        vid,number=write_version(conn,project,run,artifact,validation,now)
        announce_version(conn,run,vid,number,artifact["summary"],now)
        execute(conn,"DELETE FROM run_candidates WHERE run_id=:id",id=run["id"])
        execute(conn,"DELETE FROM run_workspace WHERE run_id=:id",id=run["id"])


def fail(run,code,message,status="failed"):
    with transaction(True) as conn:
        current=one(conn,"SELECT * FROM runs WHERE id=:id",id=run["id"])
        guard(current,run["lease_token"])
        if code=="MODEL_TIMEOUT":
            phase={"planning":"规划","generating":"生成代码","repairing":"修复代码"}.get(current["stage"])
            if phase:
                message=phase+"时，"+message
        fail_locked(conn,current,status,code,message)


async def paid_generate(run,context,repair,*,skill):
    prepared=await prepare(context,repair,skill=skill)
    return await paid_request(run,await asyncio.to_thread(next_call_attempt,run),prepared)


def next_call_attempt(run):
    with transaction() as conn:
        return one(conn,"SELECT COALESCE(MAX(attempt),0)+1 n FROM model_calls WHERE run_id=:id",id=run["id"])["n"]


async def retry_model_service(run, operation, phase, message, **details):
    rid,token=run["id"],run["lease_token"]
    for delay in MODEL_RETRY_DELAYS:
        try:
            return await operation()
        except ModelError as error:
            if error.uncertain or error.usage or error.code not in RETRYABLE_MODEL_SERVICE_ERRORS:
                raise
            wait_message="模型连接暂不可用，等待重试" if error.code=="MODEL_CONNECTION" else "模型服务限流，等待重试"
            await asyncio.to_thread(stage,rid,token,"model_wait",wait_message,code=error.code)
            await asyncio.sleep(delay)
            await asyncio.to_thread(stage,rid,token,phase,message,**details)
    return await operation()


async def agent_plan(run,context):
    async def request():
        prepared=await prepare_plan(context)
        return await paid_request(run,await asyncio.to_thread(next_call_attempt,run),prepared)

    for _ in range(MAX_DECISION_ATTEMPTS):
        try:
            raw=await retry_model_service(run,request,"planning","主 Agent 解析目标并规划实现")
            return parse_plan(strict_json(raw),context=context)
        except ValueError as error:
            feedback="上一轮的决策 JSON 不符合约定。按给定结构修正后重新提交。"+str(error)[:500]
        except ModelError as error:
            if not recoverable_model_output(error):
                raise
            feedback=str(error)
        context={**context,"decision_feedback":feedback}
    raise ModelError("AGENT_RESPONSE_INVALID","规划服务未返回可用的实现计划")


def recoverable_model_output(error):
    return not error.uncertain and error.code in MODEL_OUTPUT_ERRORS


async def paid_request(run,attempt,prepared):
    call=await asyncio.to_thread(reserve_call,run,attempt,prepared.input_ceiling,prepared.output_limit)
    # Authorize dispatch against the run's live state before yielding to the model request.
    start_call(call)
    try:
        result=await generate(prepared,call["output_limit"],run_id=run["id"])
    except ModelError as e:
        if e.usage:
            await asyncio.shield(asyncio.to_thread(settle_call,call,e.usage.input_tokens,e.usage.output_tokens,e.usage.request_id))
        else:
            await asyncio.shield(asyncio.to_thread(finish_unbilled,call,e.code,e.uncertain))
        raise
    except asyncio.CancelledError:
        await asyncio.shield(asyncio.to_thread(finish_unbilled,call,"CALL_INTERRUPTED",True))
        raise
    except Exception:
        await asyncio.to_thread(finish_unbilled,call,"CALL_UNKNOWN",True)
        raise
    await asyncio.shield(asyncio.to_thread(settle_call,call,result.usage.input_tokens,result.usage.output_tokens,result.usage.request_id))
    return result.content


def recent_game_scenes(run):
    with transaction() as conn:
        rows=all_rows(conn,"""SELECT a.raw_json FROM projects p JOIN versions v ON v.id=p.current_version_id
            JOIN artifacts a ON a.id=v.artifact_id WHERE p.owner_id=:owner AND p.kind='game' AND p.id!=:project
            ORDER BY p.created_at DESC LIMIT 12""",owner=run["owner_id"],project=run["project_id"])
    return [json.loads(row["raw_json"])["files"] for row in rows]


async def validate_candidate(run,raw,attempt,*,slide_template=None,react=False,site_files=None,website_starter=None,preview_kind="web",required_game_dimension=None,validator_slot=None):
    rid,token=run["id"],run["lease_token"]
    if len(raw.encode())>32*1024*1024:
        raise BuildIssue("ARTIFACT_LIMIT","代码超过传输资源保护")
    # Save before parsing or starting a browser so failure/restart retains the work.
    await asyncio.to_thread(keep_candidate,run,raw,"",attempt)
    message = "重新检查保留的代码，不重复生成" if attempt==0 else "检查 JSON 格式和产物契约"
    await asyncio.to_thread(stage,rid,token,"validating",message)
    try:
        try:
            artifact=strict_json(raw)
        except ValueError as error:
            raise BuildIssue("ARTIFACT_JSON_INVALID",str(error),subject=getattr(error,"msg",None)) from None
        if not isinstance(artifact,dict):
            raise BuildIssue("ARTIFACT_SCHEMA_INVALID","产物必须是完整 JSON 对象")
        rendered_deck=bool(slide_template and (attempt>0 or "slides" in artifact))
        if rendered_deck:
            try:
                artifact=render_slide_deck(artifact,slide_template)
            except ValueError as error:
                raise BuildIssue("ARTIFACT_SCHEMA_INVALID",str(error)) from None
        else:
            artifact=normalize_artifact(artifact)
        if react and (attempt>0 or website_starter) and artifact.get("schema_version")=="1":
            raise BuildIssue("ARTIFACT_SCHEMA_INVALID","此项目需要 schema_version 2 和 React TSX 源码")
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
        await asyncio.to_thread(publish_source,run,artifact)
        lightweight_3d=game and has_threejs(artifact)
        if required_game_dimension=="2d" and lightweight_3d:
            raise BuildIssue("ARTIFACT_REQUIREMENT","本次游戏需要 2D 渲染。请用 DOM 或 Canvas 2D 实现并移除 Three.js 引用")
        async with validator_slot if validator_slot is not None else nullcontext():
            await asyncio.to_thread(stage,rid,token,"browser_check","检查预览能否启动")
            validation=await validate_artifact(artifact,rid,preview_kind,lightweight_3d)
        if not validation.get("ok"):
            issue=BuildIssue.from_validator(validation)
            # During a rolling update an older validator still returns these service errors as 200.
            if str(issue) in {"浏览器效果验收超时", "隔离浏览器进程未正常完成", "隔离浏览器无法启动，请检查 Chromium 系统沙箱配置"}:
                await asyncio.to_thread(keep_candidate,run,raw,str(issue),attempt)
                raise ModelError("VALIDATOR_UNAVAILABLE","浏览器检查暂不可用，已保留本次代码")
            raise issue
        report=validation.get("report")
        compiled=validation.get("compiled")
        if (not isinstance(report,dict) or report.get("acceptance")!="startup" or report.get("ready") is not True
                or not isinstance(compiled,dict) or not isinstance(compiled.get("digest"),str)):
            raise ModelError("VALIDATOR_UNAVAILABLE","启动检查未完成，已保留本次代码")
        await asyncio.to_thread(publish_preview,run,compiled)
        if rendered_deck:
            validation["report"]["slide_renderer"]="template-deck-v1"
        if website_starter:
            validation["report"]["website_starter"] = website_starter["id"]
        return artifact,validation
    except BuildIssue as error:
        await asyncio.to_thread(keep_candidate,run,raw,str(error),attempt)
        raise
    except httpx.HTTPError as error:
        if isinstance(error,httpx.HTTPStatusError) and error.response.status_code==413:
            issue=BuildIssue("ARTIFACT_LIMIT","源码超过校验服务的大小限制")
            await asyncio.to_thread(keep_candidate,run,raw,str(issue),attempt)
            raise issue from None
        if isinstance(error,httpx.HTTPStatusError) and error.response.status_code < 500 and error.response.status_code != 429:
            raise ModelError("VALIDATOR_REJECTED","校验服务无法接受请求，已保留本次构建内容") from None
        await asyncio.to_thread(keep_candidate,run,raw,"独立校验服务暂不可用",attempt)
        raise ModelError("VALIDATOR_UNAVAILABLE","独立校验服务暂不可用，请稍后继续；本次代码已保留") from None


async def validate_with_retry(run,raw,attempt,**options):
    for delay in VALIDATOR_RETRY_DELAYS:
        try:
            return await validate_candidate(run,raw,attempt,**options)
        except ModelError as error:
            if error.code!="VALIDATOR_UNAVAILABLE":
                raise
            await asyncio.to_thread(stage,run["id"],run["lease_token"],"validator_wait","等待校验服务恢复，随后复查已有草稿",code=error.code)
            await asyncio.sleep(delay)
    return await validate_candidate(run,raw,attempt,**options)


async def deliver(run,artifact,validation):
    await asyncio.to_thread(stage,run["id"],run["lease_token"],"committing","保存代码快照和新版本")
    await asyncio.to_thread(commit,run,artifact,validation)


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
    validation_options={"preview_kind":context["project_kind"],"validator_slot":validator_slot,"required_game_dimension":dimension,
                        "slide_template":slide_template,"react":react,"site_files":site_files,
                        "website_starter":website_starter}
    coordinated=react
    plan=None
    context["fps_required"]=fps_request
    if context["project_kind"]=="game":
        await asyncio.to_thread(stage,rid,token,"researching","查找同类热门游戏及玩法资料")
        requested_genre,excluded_genres=genre_preferences(context["request"])
        genre="fps" if fps_request else requested_genre
        if base:
            base_plan=None
            base_genre=None
            try:
                base_plan=TaskPlan.model_validate_json(base.get("files",{}).get(PLAN_FILE,"{}"))
            except (ValueError,TypeError,AttributeError):
                pass
            else:
                base_genre=base_plan.game_genre
            if base_genre in (None,"other","puzzle"):
                base_genre=match_genre(base.get("title","")) or base_genre
            if base_genre not in excluded_genres:
                context["base_game_genre"]=base_genre
                if base_plan and base_plan.mechanics and (genre is None or genre==base_genre):
                    context["base_mechanics"]=base_plan.mechanics.model_dump()
        genre=genre or context.get("base_game_genre")
        context["game_genre_hint"]=genre
        skill=skill_for("game",threejs=dimension=="3d",game_genre=genre)
        context["game_profile"]=game_profile(genre)
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
            skill=skill_for("game",threejs=plan.rendering=="threejs",game_genre=plan.game_genre)
            context["fps_required"]=plan.experience=="first_person_3d"
            context["game_profile"]=game_profile(plan.game_genre)
        site_files[PLAN_FILE]=json.dumps(plan.model_dump(),ensure_ascii=False,indent=2)

    repair=None
    failed_issues={}
    if resume:
        plan_source=resume.pop("plan_source",None)
        repair=resume
        if coordinated and plan_source:
            try:
                apply_plan(TaskPlan.model_validate_json(plan_source))
            except ValueError:
                pass
        if resume.get("candidate"):
            try:
                retained=strict_json(resume["candidate"])
            except ValueError:
                retained=None
            try:
                retained_files=retained.get("files",{}) if isinstance(retained,dict) else {}
                if coordinated and plan is None and isinstance(retained_files,dict) and retained_files.get(PLAN_FILE):
                    try:
                        saved_plan=TaskPlan.model_validate_json(retained_files[PLAN_FILE])
                    except (ValueError, TypeError):
                        saved_plan=None
                    if saved_plan:
                        apply_plan(saved_plan)
                artifact,validation=await validate_with_retry(run,resume["candidate"],0,**validation_options)
            except BuildIssue as issue:
                repair=issue.repair(resume["candidate"],failed_issues,remaining=True)
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
        apply_plan(await agent_plan(run,planning_context))
        await asyncio.to_thread(stage,rid,token,"plan_ready","构建计划已整理",
                                summary=plan.visual_direction[:220],items=[item[:180] for item in plan.requirements[:3]])
    if plan and context["project_kind"]=="game" and plan.game_genre not in (None,"other",context["game_research"]["genre"]):
        research=await find_game_references(plan.game_genre)
        context["game_research"]=research
        site_files[RESEARCH_FILE]=json.dumps(research,ensure_ascii=False,indent=2)
    if plan and game and dimension=="2d" and base is None and not (resume and resume.get("candidate")):
        reference={"match3":"match-three","tower_defense":"tower-defense"}.get(plan.game_genre)
        if plan.game_genre=="arcade_platformer" and re.search(r"雪人兄弟|\bsnow\s*bros\b",context["request"],re.I):
            reference="snowball-arcade"
        if reference:
            context["game_reference"]=game_reference(reference)
    async def generate_candidate():
        return await paid_generate(run,context,repair,skill=skill)

    for repair_round in range(1 if repair else 0, MAX_REPAIR_ROUNDS + 1):
        attempt=repair_round+1
        phase="repairing" if repair else "generating"
        message="正在生成代码"
        details={}
        if repair:
            diagnostic=repair.get("diagnostic") or {}
            label=REPAIR_POLICIES[diagnostic.get("category","validation")][0]
            message=f"{label}（第 {repair_round}/{MAX_REPAIR_ROUNDS} 轮）"
            details={"diagnostic":diagnostic,"round":repair_round}
            repair={**repair,"round":repair_round}
        await asyncio.to_thread(stage,rid,token,phase,message,**details)
        try:
            raw=await retry_model_service(run,generate_candidate,phase,message,**details)
        except ModelError as error:
            if not recoverable_model_output(error):
                raise
            issue=BuildIssue(error.code,str(error))
            repair=issue.repair((repair or {}).get("candidate"),failed_issues,remaining=repair_round<MAX_REPAIR_ROUNDS)
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
            artifact,validation=await validate_with_retry(run,raw,attempt,**validation_options)
        except BuildIssue as issue:
            repair=issue.repair(raw,failed_issues,remaining=repair_round<MAX_REPAIR_ROUNDS)
            continue
        break
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
            capabilities = None
            if not settings().test_fixture:
                try:
                    async with asyncio.timeout(3), ProviderClient() as provider:
                        capabilities = await provider.capabilities()
                except (ModelError,TimeoutError):
                    capabilities = {"text_configured":False,"video_configured":False}
            await asyncio.to_thread(heartbeat, token, leases, capabilities)
            await asyncio.to_thread(recover_expired)
            await asyncio.sleep(5)

    pulse_task = asyncio.create_task(pulse())
    stopped = asyncio.create_task(stop.wait())
    log.info("Worker ready with %d generation slots", limit)
    try:
        while not stop.is_set():
            if pulse_task.done():
                await pulse_task
            if active:
                cancelled=await asyncio.to_thread(user_stopped_runs,[run["id"] for run in active.values()])
                for task,run in active.items():
                    if run["id"] in cancelled and not (task.done() or task.cancelling()):
                        task.cancel()
            while len(active) < limit and not stop.is_set() and not pulse_task.done():
                run = await asyncio.to_thread(claim, token)
                if run is None:
                    break
                task = asyncio.create_task(run_in_slot(run, validator_slot))
                active[task] = run
            done, _ = await asyncio.wait(
                [*active, pulse_task, stopped],
                timeout=1 if len(active) == limit else .5,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done & active.keys():
                del active[task]
                if not task.cancelled():
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
