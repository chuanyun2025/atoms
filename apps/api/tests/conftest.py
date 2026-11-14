import os
import tempfile
from pathlib import Path

TEMP = tempfile.TemporaryDirectory(prefix="atoms-tests-")
os.environ.update(APP_ENV="test",SESSION_SECRET="test-session-secret-"*4,SERVICE_TOKEN="test-service-token-"*4,
                  DATABASE_URL="sqlite:///"+str(Path(TEMP.name)/"test.db").replace("\\","/"),
                  TEST_FIXTURE="true",APP_ORIGIN="http://localhost:8080",COOKIE_SECURE="false",MEDIA_ROOT=str(Path(TEMP.name)/"media"))
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from atoms.main import app
from atoms.db import transaction,execute
from atoms.worker import acquire_leader

command.upgrade(Config("alembic.ini"),"head")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    from atoms import worker
    from atoms.artifacts import strict_json
    from atoms.model_fixture import test_decision
    from atoms.orchestration import TaskPlan, TaskReview
    async def decision(run,role,context):
        return (TaskPlan if role=="planner" else TaskReview).model_validate(strict_json(test_decision(role,context)))
    monkeypatch.setattr(worker,"agent_decision",decision)
    with transaction(True) as conn:
        for name in ["video_jobs","credit_ledger","media_calls","media_assets","run_workspace","run_candidates","model_calls","credit_wallets","system_settings","quota_windows","app_states","project_actions","request_keys","run_events","publications","versions","artifacts","messages","runs","projects","visitors"]:
            execute(conn,"DELETE FROM "+name)
        execute(conn,"UPDATE worker_status SET lease_token=NULL,lease_until=0,heartbeat_at=0")
    acquire_leader("test-leader")
    yield


@pytest.fixture
def client():
    with TestClient(app,base_url="http://localhost:8080") as value:
        auth=value.post("/api/v1/session",json={},headers={"Origin":"http://localhost:8080","X-App-Request":"atoms"}).json()
        value.headers.update({"Origin":"http://localhost:8080","X-App-Request":"atoms","X-CSRF-Token":auth["csrf_token"]})
        yield value


def create_project(client):
    response=client.post("/api/v1/projects",json={"client_key":"project-test-key","title":"测试项目"})
    assert response.status_code==201,response.text
    return response.json()


def submit(client,pid,prompt="创建计数器",revision=0,base=None,request_key="request-test-key"):
    return client.post("/api/v1/projects/"+pid+"/runs",json={"prompt":prompt,"expected_revision":revision,"base_version_id":base},
                       headers={"Idempotency-Key":request_key})
