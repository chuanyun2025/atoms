"""Real model smoke test. Does not send requests when model is unconfigured."""
import time
import uuid
from decimal import Decimal

import httpx

base="http://localhost:8080"
client=httpx.Client(base_url=base,trust_env=False,timeout=15)
headers={"Origin":base,"X-App-Request":"atoms"}
session=client.post("/api/v1/session",json={},headers=headers).raise_for_status().json()
headers["X-CSRF-Token"]=session["csrf_token"]
client.headers.update(headers)
cap=client.get("/api/v1/capabilities").raise_for_status().json()
if not cap["model_configured"] or not cap["worker_available"]:
    raise SystemExit("真实模型尚未配置或 Worker 未就绪；未发送模型请求。请配置 .env.local 后重新创建服务。")
project=client.post("/api/v1/projects",json={"client_key":str(uuid.uuid4()),"title":"真实模型冒烟检查"}).raise_for_status().json()
run=client.post("/api/v1/projects/"+project["id"]+"/runs",headers={"Idempotency-Key":str(uuid.uuid4())},
                json={"prompt":"创建一个中文计数器，有加一、减一、重置按钮；显示当前数值；使用 atoms.storage 保存数值，刷新后恢复。简洁绿色界面。","expected_revision":0,"base_version_id":None}).raise_for_status().json()
last=""
for _ in range(200):
    state=client.get("/api/v1/runs/"+run["id"]).raise_for_status().json()
    if state["stage"]!=last:
        print(state["stage"],flush=True);last=state["stage"]
    if state["status"]=="succeeded":
        version=client.get("/api/v1/projects/"+project["id"]+"/versions/"+state["result_version_id"]).raise_for_status().json()
        artifact=version["artifact"]
        assert artifact["schema_version"] == "2" and artifact["files"].get("src/App.tsx")
        wallet=client.get("/api/v1/wallet").raise_for_status().json()
        ledger=client.get("/api/v1/wallet/transactions").raise_for_status().json()
        assert wallet["held_units"] == 0 and Decimal(wallet["spent"]) > 0
        assert any(
            entry["kind"] == "consumption" and entry["run_id"] == run["id"] and entry["amount_units"] < 0
            for entry in ledger["items"]
        )
        print("真实模型响应、产物校验、隔离启动与版本交付：PASS")
        print("Actual token charge: "+wallet["spent"]+" credits; available: "+wallet["available"])
        print("后续请在浏览器验证计数交互和刷新保存；脚本不替代业务验收。")
        break
    if state["status"] in {"failed","interrupted"}:
        raise SystemExit(state["error_code"]+": "+state["error_message"])
    time.sleep(1)
else:
    raise SystemExit("等待任务超时，请在工作台查看持久任务状态")
