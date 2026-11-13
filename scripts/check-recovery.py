"""Hard-kill only the named disposable E2E worker; verify lease recovery."""
import subprocess
import time
import uuid
import httpx

base="http://localhost:8082"
client=httpx.Client(base_url=base,trust_env=False)
headers={"Origin":base,"X-App-Request":"atoms"}
session=client.post("/api/v1/session",json={},headers=headers).raise_for_status().json()
headers["X-CSRF-Token"]=session["csrf_token"]
client.headers.update(headers)
p=client.post("/api/v1/projects",json={"client_key":str(uuid.uuid4()),"title":"崩溃恢复检查"}).raise_for_status().json()
def submit(prompt,revision,version):
    return client.post("/api/v1/projects/"+p["id"]+"/runs",json={"prompt":prompt,"expected_revision":revision,"base_version_id":version},headers={"Idempotency-Key":str(uuid.uuid4())}).raise_for_status().json()
def wait_run(rid,statuses,timeout=45):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        run=client.get("/api/v1/runs/"+rid).raise_for_status().json()
        if run["status"] in statuses:return run
        time.sleep(.3)
    raise AssertionError("Run did not reach "+str(statuses))
first=submit("生成计数器",0,None)
stable=wait_run(first["id"],{"succeeded"})
slow=submit("[slow] 慢请求崩溃检查",1,stable["result_version_id"])
assert wait_run(slow["id"],{"running"})["status"]=="running"
for _ in range(100):
    if client.get("/api/v1/runs/"+slow["id"]).json()["model_calls"]==1:break
    time.sleep(.05)
else:
    raise AssertionError("Call was not authorized before the crash")
assert client.get("/api/v1/wallet").json()["held_units"]>0
command=["docker","compose","--env-file",".env.test","-p","atoms-e2e"]
subprocess.run(command+["kill","-s","SIGKILL","worker"],check=True,stdout=subprocess.DEVNULL)
subprocess.run(command+["up","-d","--no-deps","worker"],check=True,stdout=subprocess.DEVNULL)
interrupted=wait_run(slow["id"],{"interrupted"})
assert interrupted["error_code"]=="WORKER_LOST"
current=client.get("/api/v1/projects/"+p["id"]).raise_for_status().json()
assert current["active_run_id"] is None and current["revision"]==1 and current["current_version_id"]==stable["result_version_id"]
pending=client.get("/api/v1/wallet/transactions").json()["pending"]
frozen=next(call for call in pending if call["run_id"]==slow["id"])
assert frozen["status"]=="uncertain" and client.get("/api/v1/wallet").json()["held_units"]>0
# The deterministic fixture has no supplier charge; exercise the operator-only release.
subprocess.run(command+["exec","-T","api","python","-m","atoms.ops","credits-reconcile",frozen["id"],"--release"],check=True,stdout=subprocess.DEVNULL)
assert client.get("/api/v1/wallet").json()["held_units"]==0
for _ in range(40):
    if client.get("/api/v1/capabilities").json()["worker_available"]:break
    time.sleep(.5)
next_run=submit("恢复后继续修改",1,current["current_version_id"])
assert wait_run(next_run["id"],{"succeeded"})["result_version_id"]!=current["current_version_id"]
assert client.get("/api/v1/wallet").json()["spent"]=="0.112000"
print("Hard kill / lease / wallet hold / operator reconciliation / retry: PASS")
