"""Use an ignored E2E session to verify persistence through container restart."""
import json
import subprocess
import sys
import time
from pathlib import Path
import httpx

root=Path(__file__).resolve().parents[1]
session=json.loads((root/"test-results/e2e-session.json").read_text("utf-8"))
client=httpx.Client(base_url="http://localhost:8082",trust_env=False)
for cookie in session["cookies"]:
    client.cookies.set(cookie["name"],cookie["value"],path=cookie["path"])
def state():
    projects=client.get("/api/v1/projects").raise_for_status().json()["items"]
    return {"projects":[(p["id"],p["revision"],p["current_version_id"],client.get("/api/v1/projects/"+p["id"]+"/app-state").raise_for_status().json()) for p in projects],
            "wallet":client.get("/api/v1/wallet").raise_for_status().json(),"ledger":client.get("/api/v1/wallet/transactions").raise_for_status().json()}
before=state()
assert before["projects"] and before["projects"][0][1]>0
subprocess.run(["docker","compose","--env-file",".env.test","-p","atoms-e2e","up","-d","--no-deps","--force-recreate","api","worker"],cwd=root,check=True,stdout=subprocess.DEVNULL)
for _ in range(40):
    try:
        client.get("/health/live").raise_for_status()
        break
    except httpx.HTTPError:
        time.sleep(.5)
assert state()==before
print("Container restart / versions / business data / wallet / ledger persistence: PASS")
