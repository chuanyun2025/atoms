import hashlib
import json
import re
import time
from fastapi import HTTPException
from .config import settings
from .db import all_rows, one, execute, compact, add_event, maintenance
from .security import uid
from .credits import require_balance,CreditError
from .slide_templates import slide_template_reference


def error(status,code,message):
    raise HTTPException(status, detail={"code":code,"message":message})


def project(conn, project_id, owner):
    row = one(conn,"SELECT * FROM projects WHERE id=:id AND owner_id=:owner",id=project_id,owner=owner)
    if not row:
        error(404,"project_not_found","项目不存在或不属于当前访客")
    return row


def mutable(conn):
    if maintenance(conn):
        error(503,"maintenance","系统维护中，暂时只读")


def check_revision(row,expected):
    if row["revision"] != expected:
        error(409,"revision_conflict","项目已在其他页面更新，请刷新后重试")


def owned_version(conn, project_id, version_id):
    row = one(conn,"SELECT v.*,a.raw_json,a.compiled_json,a.digest,a.validation_json FROM versions v JOIN artifacts a ON v.artifact_id=a.id WHERE v.id=:id AND v.project_id=:project",id=version_id,project=project_id)
    if not row:
        error(404,"version_not_found","版本不存在")
    return row


def public_version(row, files=False):
    result = {k:row[k] for k in ["id","project_id","number","parent_version_id","source_run_id","title","summary","created_at"]}
    if files:
        result["artifact"] = json.loads(row["raw_json"])
        result["validation_report"] = json.loads(row["validation_json"])
    return result


def public_run(row):
    return {key:row[key] for key in ["id","project_id","prompt","base_version_id","status","stage","created_at","started_at","finished_at","model_calls","error_code","error_message","result_version_id","retry_of_run_id"]}


def create_project(conn, owner, data):
    if data.slide_template_id and (data.kind != "slides" or slide_template_reference(data.slide_template_id) is None):
        error(422,"invalid_slide_template","请选择可用的幻灯片模板")
    existing = one(conn,"SELECT * FROM projects WHERE owner_id=:owner AND client_key=:key",owner=owner,key=data.client_key)
    if existing:
        if existing["slide_template_id"] != data.slide_template_id:
            error(409,"project_key_conflict","该创建请求已绑定其他模板，请刷新后重试")
        return existing
    mutable(conn)
    now, pid = time.time(), uid()
    execute(conn,"""INSERT INTO projects(id,owner_id,client_key,title,kind,slide_template_id,created_at,updated_at)
                 VALUES(:id,:owner,:key,:title,:kind,:template,:now,:now)""",
            id=pid,owner=owner,key=data.client_key,title=data.title.strip(),kind=data.kind,
            template=data.slide_template_id,now=now)
    execute(conn,"INSERT INTO app_states(project_id,updated_at) VALUES(:id,:now)",id=pid,now=now)
    return project(conn,pid,owner)


def create_run(conn, owner, project_id, data, idempotency_key, ip):
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{8,100}",idempotency_key):
        error(400,"invalid_idempotency_key","提交凭证无效")
    omitted={name for name in ("retry_of_run_id","video") if getattr(data,name) is None}
    request_body=data.model_dump(exclude=omitted)
    request_hash = hashlib.sha256(compact({"project_id":project_id,**request_body}).encode()).hexdigest()
    previous = one(conn,"SELECT * FROM request_keys WHERE owner_id=:owner AND key=:key",owner=owner,key=idempotency_key)
    if previous:
        if previous["request_hash"] != request_hash:
            error(409,"idempotency_conflict","同一提交凭证不能用于不同请求")
        return public_run(one(conn,"SELECT * FROM runs WHERE id=:id",id=previous["run_id"]))
    row = project(conn,project_id,owner)
    now = time.time()
    worker = one(conn,"SELECT * FROM worker_status WHERE id=1")
    video_job=None
    source_job=None
    if row["kind"]=="video":
        from .media import owned_asset
        from .schemas import VideoOptions
        if not worker or not worker["video_configured"]:
            error(503,"video_not_configured","视频服务尚未连接，请联系管理员")
        if len(data.prompt)>20000:
            error(422,"video_prompt_limit","视频描述不能超过 20000 字")
        if data.retry_of_run_id:
            source_job=one(conn,"SELECT j.* FROM video_jobs j JOIN runs r ON r.id=j.run_id WHERE j.run_id=:id AND r.owner_id=:owner AND r.project_id=:pid",
                           id=data.retry_of_run_id,owner=owner,pid=project_id)
        options=data.video or VideoOptions()
        video_job={**options.model_dump(),"model":settings().vidu_model,"resolution":settings().vidu_resolution,
                   "phase":"pending","provider_task_id":None,"output_asset_id":None,"provider_credits":None,
                   "input_mode":"image" if options.image_asset_id else "text"}
        if source_job:
            if source_job["phase"]=="submitting" and not source_job["provider_task_id"]:
                error(409,"video_submission_uncertain","上次提交结果待核对，请联系管理员，避免重复扣费")
            for name in ("duration","audio","input_mode","image_asset_id"):
                video_job[name]=source_job[name]
            if source_job["provider_task_id"] and source_job["phase"]!="failed":
                for name in ("model","resolution","phase","provider_task_id","output_asset_id","provider_credits"):
                    video_job[name]=source_job[name]
        if video_job["image_asset_id"]:
            asset=owned_asset(conn,project_id,video_job["image_asset_id"])
            if not asset["mime_type"].startswith("image/"):
                error(422,"invalid_image","参考图必须是图片")
    elif data.video is not None:
        error(422,"invalid_video_options","只有视频项目可以使用视频参数")
    mutable(conn)
    check_revision(row,data.expected_revision)
    if row["active_run_id"]:
        error(409,"run_active","当前项目已有生成任务，请等待完成")
    if row["current_version_id"] != data.base_version_id:
        error(409,"base_version_conflict","基础版本已变化，请刷新")
    recoverable=False
    if data.retry_of_run_id:
        source=one(conn,"SELECT * FROM runs WHERE id=:id AND owner_id=:owner AND project_id=:pid",id=data.retry_of_run_id,owner=owner,pid=project_id)
        if not source:
            error(404,"run_not_found","上次构建不存在或不属于当前项目")
        if source["status"] not in {"failed","interrupted"}:
            error(409,"run_not_retryable","该次构建无需修复，请查看当前结果")
        if source["base_version_id"]!=row["current_version_id"]:
            error(409,"retry_base_changed","项目已更新，请基于当前版本继续描述修改")
        if source["prompt"]!=data.prompt:
            error(409,"retry_prompt_changed","继续修复会沿用原始需求；修改需求后请正常提交")
        recoverable=bool(one(conn,"SELECT run_id FROM run_candidates WHERE run_id=:id",id=source["id"]))
    if row["kind"]!="video" and (not worker or not worker["model_configured"]):
        error(503,"model_not_configured","文本生成服务尚未连接，请联系管理员")
    if not worker or worker["heartbeat_at"] < now-20 or worker["lease_until"] < now:
        error(503,"worker_unavailable","生成服务正在启动，请稍后重试")
    try:
        if not recoverable and row["kind"]!="video":
            require_balance(conn,owner)
    except CreditError as e:
        error(402,e.code,str(e))
    rid = uid()
    execute(conn,"""INSERT INTO runs(id,project_id,owner_id,prompt,base_version_id,expected_revision,status,stage,created_at,retry_of_run_id)
    VALUES(:id,:project,:owner,:prompt,:base,:revision,'pending','accepted',:now,:retry)""",
            id=rid,project=project_id,owner=owner,prompt=data.prompt,base=data.base_version_id,revision=data.expected_revision,now=now,retry=data.retry_of_run_id)
    if video_job:
        from . import media_credits
        try:
            video_call=media_credits.reuse(conn,source_job["video_call_id"],rid,owner) if source_job and source_job["video_call_id"] and video_job["provider_task_id"] else None
            if not video_call:
                video_call=media_credits.reserve(conn,rid,owner,"video",media_credits.estimated_usage(video_job["model"],video_job["resolution"],video_job["duration"]))
        except CreditError as exc:
            error(402,exc.code,str(exc))
        execute(conn,"""INSERT INTO video_jobs(run_id,image_asset_id,model,resolution,duration,audio,phase,
            provider_task_id,output_asset_id,provider_credits,input_mode,video_call_id,updated_at)
            VALUES(:rid,:image_asset_id,:model,:resolution,:duration,:audio,:phase,:provider_task_id,:output_asset_id,
            :provider_credits,:input_mode,:video_call,:now)""",
            rid=rid,now=now,video_call=video_call,**video_job)
    execute(conn,"INSERT INTO request_keys(owner_id,key,request_hash,run_id,created_at) VALUES(:owner,:key,:hash,:id,:now)",owner=owner,key=idempotency_key,hash=request_hash,id=rid,now=now)
    execute(conn,"INSERT INTO messages(id,project_id,run_id,role,content,created_at) VALUES(:id,:project,:run,'user',:prompt,:now)",id=uid(),project=project_id,run=rid,prompt="继续修复上一轮应用" if data.retry_of_run_id else data.prompt,now=now)
    execute(conn,"UPDATE projects SET active_run_id=:run,updated_at=:now WHERE id=:id",run=rid,now=now,id=project_id)
    add_event(conn,rid,"accepted",{"message":"需求已接收，等待生成服务"})
    return public_run(one(conn,"SELECT * FROM runs WHERE id=:id",id=rid))


def write_version(conn, project, run, artifact, validation, now):
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
    return vid, number


def announce_version(conn, run, vid, number, summary, now):
    execute(conn,"INSERT INTO messages(id,project_id,run_id,role,content,created_at) VALUES(:id,:pid,:rid,'assistant',:summary,:now)",
            id=uid(),pid=run["project_id"],rid=run["id"],summary=summary,now=now)
    add_event(conn,run["id"],"completed",{"version_id":vid,"version_number":number,"message":summary})


def restore_version(conn,owner,pid,vid,expected):
    row = project(conn,pid,owner)
    mutable(conn)
    owned_version(conn,pid,vid)
    if row["current_version_id"] == vid:
        return row
    check_revision(row,expected)
    if row["active_run_id"]:
        error(409,"run_active","生成期间不能恢复版本")
    now = time.time()
    execute(conn,"INSERT INTO project_actions(id,project_id,action,from_version_id,to_version_id,created_at) VALUES(:id,:project,'restore',:old,:new,:now)",
            id=uid(),project=pid,old=row["current_version_id"],new=vid,now=now)
    execute(conn,"UPDATE projects SET current_version_id=:vid,revision=revision+1,updated_at=:now WHERE id=:id",vid=vid,now=now,id=pid)
    return project(conn,pid,owner)


KEY = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def app_state(conn,pid):
    row = one(conn,"SELECT * FROM app_states WHERE project_id=:id",id=pid)
    return {"revision":row["revision"],"values":json.loads(row["values_json"])}


def patch_state(conn,owner,pid,data):
    row=project(conn,pid,owner)
    mutable(conn)
    if data.version_id and row["current_version_id"]!=data.version_id:
        error(409,"preview_version_changed","当前代码版本已变化，请重新加载预览后再保存数据")
    state = app_state(conn,pid)
    if state["revision"] != data.expected_revision:
        error(409,"state_conflict","业务数据已在其他页面更新，请重新加载预览")
    values = state["values"]
    for key in [*data.set,*data.remove]:
        if not KEY.fullmatch(key) or key in {"__proto__","constructor","prototype"}:
            error(422,"invalid_storage_key","业务数据键无效")
    for key,value in data.set.items():
        try:
            size = len(compact(value).encode())
        except (ValueError,TypeError):
            error(422,"invalid_storage_value","业务数据必须为有效 JSON")
        if size>16384:
            error(413,"storage_item_limit","单项业务数据不能超过 16 KiB")
        values[key] = value
    for key in data.remove:
        values.pop(key,None)
    if len(values)>128 or len(compact(values).encode())>65536:
        error(413,"storage_limit","项目业务数据最多 128 项、总计 64 KiB")
    execute(conn,"UPDATE app_states SET values_json=:values,revision=revision+1,updated_at=:now WHERE project_id=:id",
            values=compact(values),now=time.time(),id=pid)
    return app_state(conn,pid)
