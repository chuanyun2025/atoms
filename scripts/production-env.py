"""Prepare ignored production env with fresh random server secrets."""
from pathlib import Path
import secrets
root=Path(__file__).resolve().parents[1]
target=root/".env.production"
if not target.exists():
    value=(root/"deploy/production.env.example").read_text("utf-8")
    for name,size in [("SESSION_SECRET",48),("SERVICE_TOKEN",32)]:
        value=value.replace(name+"=\n",name+"="+secrets.token_urlsafe(size)+"\n")
    target.write_text(value,encoding="utf-8")
    print("已生成 .env.production。请填写真实域名、模型密钥；随机服务密钥未输出。")
else:
    print(".env.production 已存在，已保留。")
