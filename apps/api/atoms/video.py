"""Durable native video generation, with private long-lived media outputs."""
import asyncio
import base64
import hashlib
import ipaddress
import os
import socket
import time
from urllib.parse import urlsplit, urljoin

import httpx

from .config import settings
from .db import transaction, one, execute, compact
from .media import asset_path, store_asset, MAX_VIDEO_BYTES
from .model import ModelError
from .security_ids import uid
from .provider_client import ProviderClient
from . import media_credits


def checkpoint(run, **values):
    from .worker import guard
    with transaction(True) as conn:
        guard(one(conn,"SELECT * FROM runs WHERE id=:id",id=run["id"]),run["lease_token"])
        allowed={"phase","provider_task_id","output_asset_id","provider_credits","image_asset_id"}
        if not values or not set(values)<=allowed:
            raise ValueError("Invalid video checkpoint")
        execute(conn,"UPDATE video_jobs SET "+",".join(name+"=:"+name for name in values)+",updated_at=:now WHERE run_id=:rid",
                rid=run["id"],now=time.time(),**values)


async def public_media_url(url):
    try:
        parsed=urlsplit(url)
        valid=parsed.scheme=="https" and parsed.hostname and not parsed.username and not parsed.password and parsed.port in {None,443}
    except ValueError:
        valid=False
    if not valid:
        raise ModelError("VIDU_MEDIA_URL","Vidu 返回的视频地址无效")
    try:
        addresses=await asyncio.to_thread(socket.getaddrinfo,parsed.hostname,443,type=socket.SOCK_STREAM)
    except OSError:
        raise ModelError("VIDU_MEDIA_DOWNLOAD","视频已生成，下载暂未完成，可以继续获取原任务结果") from None
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ModelError("VIDU_MEDIA_URL","Vidu 返回的视频地址不可用")


def _open_temp_video(target):
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_suffix(".part")
    return temporary,temporary.open("xb")


def _finalize_temp_video(output,temporary,target,run,asset_id,size,sha256_hex):
    output.flush()
    os.fsync(output.fileno())
    output.close()
    temporary.replace(target)
    from .worker import guard
    with transaction(True) as conn:
        guard(one(conn,"SELECT * FROM runs WHERE id=:id",id=run["id"]),run["lease_token"])
        execute(conn,"INSERT INTO media_assets(id,project_id,mime_type,size_bytes,sha256,created_at) VALUES(:id,:pid,'video/mp4',:size,:sha,:now)",
                id=asset_id,pid=run["project_id"],size=size,sha=sha256_hex,now=time.time())


def _cleanup_temp_video(output,temporary):
    if output is not None:
        try:
            output.close()
        except OSError:
            pass
    if temporary is not None:
        temporary.unlink(missing_ok=True)


async def download_video(run,url):
    asset={"id":uid(),"mime_type":"video/mp4"}
    target=asset_path(asset)
    temporary=None
    output=None
    size=0
    digest=hashlib.sha256()
    prefix=b""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300,connect=20),follow_redirects=False) as http:
            for _ in range(4):
                await public_media_url(url)
                async with http.stream("GET",url) as response:
                    if response.is_redirect:
                        url=urljoin(url,response.headers.get("location",""))
                        continue
                    response.raise_for_status()
                    length=response.headers.get("content-length","")
                    if length.isdigit() and int(length)>MAX_VIDEO_BYTES:
                        raise ModelError("VIDU_MEDIA_SIZE","视频文件超过保存上限")
                    temporary,output=await asyncio.to_thread(_open_temp_video,target)
                    async for chunk in response.aiter_bytes(65536):
                        size+=len(chunk)
                        if size>MAX_VIDEO_BYTES:
                            raise ModelError("VIDU_MEDIA_SIZE","视频文件超过保存上限")
                        if len(prefix)<64:
                            prefix=(prefix+chunk)[:64]
                        digest.update(chunk)
                        await asyncio.to_thread(output.write,chunk)
                    break
            else:
                raise ModelError("VIDU_MEDIA_DOWNLOAD","视频已生成，下载重定向未完成，请继续获取原任务结果")
        if size<16 or b"ftyp" not in prefix:
            raise ModelError("VIDU_MEDIA_FORMAT","视频结果暂不可播放，请继续获取原任务结果")
        await asyncio.to_thread(_finalize_temp_video,output,temporary,target,run,asset["id"],size,digest.hexdigest())
        output=None
        return asset["id"]
    except (httpx.HTTPError,OSError):
        raise ModelError("VIDU_MEDIA_DOWNLOAD","视频已生成，下载暂未完成，可以继续获取原任务结果") from None
    finally:
        await asyncio.to_thread(_cleanup_temp_video,output,temporary)


def call_change(run,call_id,action,value=None):
    from .worker import guard
    with transaction(True) as conn:
        guard(one(conn,"SELECT * FROM runs WHERE id=:id",id=run["id"]),run["lease_token"])
        if action=="settle":
            media_credits.settle(conn,call_id,value)
        elif action=="release":
            media_credits.release(conn,call_id,value)


def begin_call(run,job):
    from .worker import guard
    with transaction(True) as conn:
        guard(one(conn,"SELECT * FROM runs WHERE id=:id",id=run["id"]),run["lease_token"])
        media_credits.start(conn,job["video_call_id"],run)
        if not job["provider_task_id"]:
            execute(conn,"UPDATE video_jobs SET phase='submitting',updated_at=:now WHERE run_id=:rid",now=time.time(),rid=run["id"])


def _load_image_data_url(project_id,image_asset_id):
    with transaction() as conn:
        asset=one(conn,"SELECT * FROM media_assets WHERE id=:id AND project_id=:pid",id=image_asset_id,pid=project_id)
    if not asset or not asset_path(asset).is_file():
        raise ModelError("VIDEO_INPUT_MISSING","参考图片暂不可用，请重新上传")
    return "data:"+asset["mime_type"]+";base64,"+base64.b64encode(asset_path(asset).read_bytes()).decode()


def _record_submitted_task(run,video_call_id,task):
    checkpoint(run,provider_task_id=task,phase="created")
    with transaction(True) as conn:
        execute(conn,"UPDATE media_calls SET provider_task_id=:task WHERE id=:id",task=task,id=video_call_id)


def _load_video_job(run_id):
    with transaction() as conn:
        return one(conn,"SELECT * FROM video_jobs WHERE run_id=:id",id=run_id)


def _load_output_asset(asset_id,project_id):
    with transaction() as conn:
        return one(conn,"SELECT * FROM media_assets WHERE id=:id AND project_id=:pid",id=asset_id,pid=project_id)


def _complete_fixture_video(run,job):
    from pathlib import Path
    from .worker import stage
    root=Path(__file__).resolve().parents[3]/"shared"/"test-fixtures"
    begin_call(run,job)
    stage(run["id"],run["lease_token"],"video_processing","正在生成视频（测试服务）")
    with transaction(True) as conn:
        result=store_asset(conn,run["project_id"],(root/"video.mp4").read_bytes(),"video/mp4")
    actual=media_credits.estimated_usage(job["model"],job["resolution"],job["duration"])
    call_change(run,job["video_call_id"],"settle",actual)
    checkpoint(run,output_asset_id=result["id"],phase="success",provider_credits=actual)
    return result["id"]


async def poll_result(run,provider,task_id,call_id):
    from .worker import stage
    cfg=settings()
    failures=0
    empty=0
    previous=None
    while True:
        try:
            result=await provider.query_video(task_id,run_id=run["id"])
            failures=0
        except ModelError as error:
            if error.code not in {"VIDU_POLL_RETRY","VIDU_INVALID_RESPONSE"} or failures>=8:
                raise
            failures+=1
            await asyncio.sleep(cfg.vidu_poll_seconds)
            continue
        phase=result["state"]
        await asyncio.to_thread(checkpoint,run,phase=phase)
        if phase=="failed":
            await asyncio.to_thread(call_change,run,call_id,"release","PROVIDER_FAILED")
            raise ModelError("VIDU_GENERATION_FAILED","视频生成未完成，预授权积分已退回；可调整描述后再试")
        if phase=="success":
            actual=result.get("credits")
            await asyncio.to_thread(checkpoint,run,provider_credits=actual if type(actual) is int else None)
            # Generation is billable even when downloading later needs recovery.
            await asyncio.to_thread(call_change,run,call_id,"settle",actual)
            if isinstance(result.get("video_url"),str):
                return result["video_url"]
            if empty>=3:
                raise ModelError("VIDU_RESULT_MISSING","视频已生成，暂未获取到文件，可以继续原任务")
            empty+=1
        if phase!=previous:
            await asyncio.to_thread(stage,run["id"],run["lease_token"],"video_processing" if phase=="processing" else "video_queueing",
                  "正在生成视频" if phase=="processing" else "视频已受理，正在排队")
            previous=phase
        await asyncio.sleep(cfg.vidu_poll_seconds)


async def acquire_result(run,job,provider):
    from .worker import stage
    task=job["provider_task_id"]
    if not task and job["phase"]=="submitting":
        raise ModelError("VIDU_SUBMISSION_UNCERTAIN","上次提交结果待核对，请联系管理员，避免重复扣费")
    await asyncio.to_thread(begin_call,run,job)
    if not task:
        await asyncio.to_thread(stage,run["id"],run["lease_token"],"video_submitting","正在提交视频任务")
        try:
            options=dict(prompt=run["prompt"],expected_model=job["model"],resolution=job["resolution"],
                         duration=job["duration"],audio=job["audio"],payload=run["id"])
            if job["image_asset_id"]:
                data=await asyncio.to_thread(_load_image_data_url,run["project_id"],job["image_asset_id"])
                task=await provider.submit_video(image=data,**options)
            else:
                task=await provider.submit_video(**options)
        except ModelError as error:
            if not error.uncertain:
                await asyncio.to_thread(call_change,run,job["video_call_id"],"release",error.code)
                await asyncio.to_thread(checkpoint,run,phase="failed")
            raise
        await asyncio.to_thread(_record_submitted_task,run,job["video_call_id"],task)
    url=await poll_result(run,provider,task,job["video_call_id"])
    await asyncio.to_thread(stage,run["id"],run["lease_token"],"video_downloading","视频已生成，正在保存")
    for attempt in range(3):
        try:
            return await download_video(run,url)
        except ModelError as error:
            if error.code!="VIDU_MEDIA_DOWNLOAD" or attempt==2:
                raise
            await asyncio.sleep(2**attempt)


async def execute_video(run,context):
    cfg=settings()
    job=await asyncio.to_thread(_load_video_job,run["id"])
    if not job:
        raise ModelError("VIDEO_INPUT_MISSING","视频任务配置不可用，请重新提交")
    if not job["output_asset_id"]:
        if cfg.app_env=="test" and cfg.test_fixture:
            job["output_asset_id"]=await asyncio.to_thread(_complete_fixture_video,run,job)
        else:
            async with ProviderClient() as provider:
                job["output_asset_id"]=await acquire_result(run,job,provider)
                await asyncio.to_thread(checkpoint,run,output_asset_id=job["output_asset_id"],phase="success")
    asset=await asyncio.to_thread(_load_output_asset,job["output_asset_id"],run["project_id"])
    if not asset or not asset_path(asset).is_file():
        raise ModelError("VIDU_MEDIA_MISSING","视频文件暂不可用，请联系管理员恢复")
    media={"asset_id":asset["id"],"image_asset_id":job["image_asset_id"],"model":job["model"],"resolution":job["resolution"],"duration":job["duration"],"audio":bool(job["audio"])}
    artifact={"schema_version":"3","title":context["project_title"],"summary":f"视频已生成：{job['duration']} 秒 · {job['resolution']}，支持播放与下载。",
              "files":{"video.json":compact({"prompt":run["prompt"],**media})},"media":media}
    return artifact,{"compiled":{"digest":asset["sha256"],"compiler_version":"vidu-native-video-v2","sdk_version":"media-v1"},
                     "report":{"native_video":True,"model":job["model"],"resolution":job["resolution"],"size_bytes":asset["size_bytes"]}}
