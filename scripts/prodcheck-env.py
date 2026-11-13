from pathlib import Path
import secrets
from provider_gateway_token import ensure_gateway_token
root=Path(__file__).resolve().parents[1]
p=root/".env.prodcheck"
if not p.exists():
    p.write_text("APP_ENV=development\nAPP_ORIGIN=http://localhost:8083\nCOOKIE_SECURE=false\n"
                 "SESSION_SECRET="+secrets.token_urlsafe(48)+"\nSERVICE_TOKEN="+secrets.token_urlsafe(32)+"\n"
                 "DATA_VOLUME_NAME=atoms_prodcheck_data\n",encoding="utf-8")
print("静态生产镜像检查环境已就绪；HTTP 检查使用 development 配置，无模型调用。")
ensure_gateway_token(p)
