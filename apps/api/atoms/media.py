"""Private media assets stored on the same persistent volume as the database."""
import base64
import binascii
import hashlib
import os
import re
import time
from pathlib import Path

from .config import settings
from .db import execute, one
from .security_ids import uid
from .service import error

EXTENSIONS = {"image/png":"png", "image/jpeg":"jpg", "image/webp":"webp", "video/mp4":"mp4"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_VIDEO_BYTES = 250 * 1024 * 1024


def asset_path(asset):
    root = Path(settings().media_root).resolve()
    if not re.fullmatch(r"[a-f0-9]{32}",asset["id"]) or asset["mime_type"] not in EXTENSIONS:
        raise ValueError("Invalid media asset")
    return root / (asset["id"]+"."+EXTENSIONS[asset["mime_type"]])


def owned_asset(conn, pid, asset_id):
    asset = one(conn,"SELECT * FROM media_assets WHERE id=:id AND project_id=:pid",id=asset_id,pid=pid)
    if not asset:
        error(404,"media_not_found","媒体文件不存在或不属于当前项目")
    return asset


def store_asset(conn, pid, content, mime):
    asset = {"id":uid(),"mime_type":mime}
    target = asset_path(asset)
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary = target.with_suffix(".part")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
        execute(conn,"""INSERT INTO media_assets(id,project_id,mime_type,size_bytes,sha256,created_at)
            VALUES(:id,:pid,:mime,:size,:sha,:now)""",id=asset["id"],pid=pid,mime=mime,
                size=len(content),sha=hashlib.sha256(content).hexdigest(),now=time.time())
    finally:
        temporary.unlink(missing_ok=True)
    return owned_asset(conn,pid,asset["id"])


def upload_image(conn,pid,data_url):
    match = re.fullmatch(r"data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=\r\n]+)",data_url)
    if not match:
        error(422,"invalid_image","请选择 PNG、JPEG 或 WebP 图片")
    try:
        content=base64.b64decode(match[2].replace("\r","").replace("\n",""),validate=True)
    except (ValueError,binascii.Error):
        error(422,"invalid_image","图片编码无效，请重新选择")
    if not 16 <= len(content) <= MAX_IMAGE_BYTES:
        error(413,"image_size_limit","首帧图片最大支持 5 MB")
    mime=match[1]
    valid=(mime=="image/png" and content.startswith(b"\x89PNG\r\n\x1a\n")) or (mime=="image/jpeg" and content.startswith(b"\xff\xd8\xff")) or (mime=="image/webp" and content[:4]==b"RIFF" and content[8:12]==b"WEBP")
    if not valid:
        error(422,"invalid_image","图片内容与格式不匹配，请重新选择")
    return store_asset(conn,pid,content,mime)
