"""Exercise online backup and offline restore only on atoms-e2e."""
import json
import subprocess
import time
import uuid
from pathlib import Path
import httpx

root=Path(__file__).resolve().parents[1]
session=json.loads((root/"test-results/e2e-session.json").read_text("utf-8"))
client=httpx.Client(base_url="http://localhost:8082",trust_env=False)
for cookie in session["cookies"]:
    client.cookies.set(cookie["name"],cookie["value"])
def snapshot():
    projects=client.get("/api/v1/projects").raise_for_status().json()["items"]
    return {"projects":[(p,client.get("/api/v1/projects/"+p["id"]+"/app-state").raise_for_status().json()) for p in projects],
            "wallet":client.get("/api/v1/wallet").raise_for_status().json(),"ledger":client.get("/api/v1/wallet/transactions").raise_for_status().json()}
before=snapshot()
command=["docker","compose","--env-file",".env.test","-p","atoms-e2e"]
backup="/var/lib/atoms/verification-"+uuid.uuid4().hex+".db"
def run(*args):
    subprocess.run(command+list(args),cwd=root,check=True)
run("exec","-T","api","python","-m","atoms.ops","maintenance","on")
run("exec","-T","api","python","-m","atoms.ops","backup",backup)
run("exec","-T","api","python","-m","atoms.ops","restore",backup)
run("stop","api","worker")
try:
    run("run","--rm","--no-deps","api","python","-m","atoms.ops","restore",backup,"--offline","--confirm-restore")
    run("run","--rm","--no-deps","api","python","-m","atoms.ops","maintenance","off")
finally:
    run("up","-d","--no-deps","api","worker")
for _ in range(40):
    try:
        client.get("/health/live").raise_for_status()
        break
    except httpx.HTTPError:
        time.sleep(.5)
assert snapshot()==before
print("SQLite backup / offline restore / projects / wallet / ledger equality: PASS")
