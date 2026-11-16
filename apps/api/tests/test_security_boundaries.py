import io
import json
from fastapi.testclient import TestClient
from atoms.config import settings
from atoms.main import app
from conftest import create_project, submit


def test_chunked_request_cannot_bypass_body_size_limit(client):
    p = create_project(client)

    def oversized_chunks():
        chunk = json.dumps({"client_key": "chunked-key-" + "a" * (128 * 1024)}).encode()
        yield chunk[:64]
        for _ in range(20):
            yield b" " * (128 * 1024)
        yield chunk[64:]

    response = client.post("/api/v1/projects", content=oversized_chunks(), headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "request_too_large"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"

    # Normal chunked request under limit succeeds cleanly.
    small = json.dumps({"client_key": "valid-chunked-key", "title": "流式测试"}).encode()
    ok = client.post("/api/v1/projects", content=iter([small[:15], small[15:]]), headers={"Content-Type": "application/json"})
    assert ok.status_code == 201
    assert ok.json()["project" if "project" in ok.json() else "id"]


def test_content_type_with_charset_and_mixed_case_accepted(client):
    response = client.post(
        "/api/v1/projects",
        content=json.dumps({"client_key": "charset-json-key", "title": "编码测试"}).encode(),
        headers={"Content-Type": "Application/JSON ; charset=utf-8"},
    )
    assert response.status_code == 201


def test_session_and_run_rate_limits(client, monkeypatch):
    cfg = settings()
    monkeypatch.setattr(cfg, "rate_limit_enabled", True)
    monkeypatch.setattr(cfg, "session_rate_limit_per_hour", 2)
    monkeypatch.setattr(cfg, "run_rate_limit_per_minute", 2)

    headers = {"Origin": "http://localhost:8080", "X-App-Request": "atoms", "X-Real-IP": "198.51.100.7"}
    with TestClient(app, base_url="http://localhost:8080") as first, TestClient(app, base_url="http://localhost:8080") as second, TestClient(app, base_url="http://localhost:8080") as third:
        assert first.post("/api/v1/session", json={}, headers=headers).status_code == 200
        # Re-validating an existing session does not consume a new-visitor slot.
        assert first.post("/api/v1/session", json={}, headers=headers).status_code == 200
        assert second.post("/api/v1/session", json={}, headers=headers).status_code == 200
        blocked = third.post("/api/v1/session", json={}, headers=headers)
        assert blocked.status_code == 429
        assert blocked.json()["detail"]["code"] == "rate_limited"
        # A different IP still works.
        assert third.post("/api/v1/session", json={}, headers={**headers, "X-Real-IP": "198.51.100.8"}).status_code == 200

    p1 = client.post("/api/v1/projects", json={"client_key": "rl-proj-1", "title": "一"}).json()
    p2 = client.post("/api/v1/projects", json={"client_key": "rl-proj-2", "title": "二"}).json()
    p3 = client.post("/api/v1/projects", json={"client_key": "rl-proj-3", "title": "三"}).json()
    run_headers = {"X-Real-IP": "198.51.100.9"}
    r1 = client.post(f"/api/v1/projects/{p1['id']}/runs", json={"prompt": "一", "expected_revision": 0, "base_version_id": None}, headers={**run_headers, "Idempotency-Key": "rl-run-key-1"})
    assert r1.status_code == 202
    # Idempotent replay does not trigger or consume rate limit.
    replay = client.post(f"/api/v1/projects/{p1['id']}/runs", json={"prompt": "一", "expected_revision": 0, "base_version_id": None}, headers={**run_headers, "Idempotency-Key": "rl-run-key-1"})
    assert replay.status_code == 202 and replay.json()["id"] == r1.json()["id"]
    assert client.post(f"/api/v1/projects/{p2['id']}/runs", json={"prompt": "二", "expected_revision": 0, "base_version_id": None}, headers={**run_headers, "Idempotency-Key": "rl-run-key-2"}).status_code == 202
    r3 = client.post(f"/api/v1/projects/{p3['id']}/runs", json={"prompt": "三", "expected_revision": 0, "base_version_id": None}, headers={**run_headers, "Idempotency-Key": "rl-run-key-3"})
    assert r3.status_code == 429
    assert r3.json()["detail"]["code"] == "rate_limited"


def test_client_ip_restores_visitor_behind_trusted_proxies_and_isolates_rate_limits(client, monkeypatch):
    from starlette.requests import Request
    from atoms.security import client_ip

    cfg = settings()
    monkeypatch.setattr(cfg, "rate_limit_enabled", True)
    monkeypatch.setattr(cfg, "session_rate_limit_per_hour", 2)
    monkeypatch.setattr(cfg, "run_rate_limit_per_minute", 2)
    monkeypatch.setattr(cfg, "trusted_proxy_cidrs", "")
    monkeypatch.setattr(cfg, "trust_private_proxies", True)
    monkeypatch.setattr(cfg, "trust_cf_connecting_ip", False)

    def make_request(peer: str, headers: dict[str, str]) -> Request:
        return Request(
            {
                "type": "http",
                "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
                "client": (peer, 12345),
            }
        )

    # Behind private/Docker Nginx + tunnel, peel trusted proxy hops right-to-left and ignore spoofed leftmost hops.
    assert (
        client_ip(
            make_request(
                "172.18.0.5",
                {
                    "X-Real-IP": "172.18.0.6",
                    "X-Forwarded-For": "1.2.3.4, 203.0.113.10, 172.18.0.5, 172.18.0.6",
                    "CF-Connecting-IP": "198.51.100.99",
                },
            )
        )
        == "203.0.113.10"
    )
    # Direct connection from private proxy without X-Real-IP still uses X-Forwarded-For.
    assert client_ip(make_request("10.0.0.8", {"X-Forwarded-For": "[2001:db8::42]:5000, 172.18.0.5"})) == "2001:db8::42"

    # Untrusted public peer IP must ignore X-Forwarded-For and CF-Connecting-IP even if CF trust flag is enabled.
    monkeypatch.setattr(cfg, "trust_cf_connecting_ip", True)
    assert (
        client_ip(
            make_request(
                "198.51.100.50",
                {
                    "X-Real-IP": "198.51.100.50",
                    "X-Forwarded-For": "203.0.113.77",
                    "CF-Connecting-IP": "203.0.113.88",
                },
            )
        )
        == "198.51.100.50"
    )

    # Configured proxy CIDR honors CF-Connecting-IP only when peer matches that CIDR.
    monkeypatch.setattr(cfg, "trusted_proxy_cidrs", "173.245.48.0/20")
    assert (
        client_ip(
            make_request(
                "173.245.48.10",
                {
                    "X-Real-IP": "173.245.48.10",
                    "X-Forwarded-For": "203.0.113.5",
                    "CF-Connecting-IP": "203.0.113.77",
                },
            )
        )
        == "203.0.113.77"
    )
    assert (
        client_ip(
            make_request(
                "198.51.100.50",
                {
                    "X-Real-IP": "198.51.100.50",
                    "CF-Connecting-IP": "203.0.113.77",
                },
            )
        )
        == "198.51.100.50"
    )

    # HTTP rate limits behind a shared tunnel proxy isolate real visitors and block leftmost spoofing.
    monkeypatch.setattr(cfg, "trusted_proxy_cidrs", "")
    monkeypatch.setattr(cfg, "trust_cf_connecting_ip", False)
    base_headers = {"Origin": "http://localhost:8080", "X-App-Request": "atoms", "X-Real-IP": "172.18.0.5"}

    with (
        TestClient(app, base_url="http://localhost:8080") as a1,
        TestClient(app, base_url="http://localhost:8080") as a2,
        TestClient(app, base_url="http://localhost:8080") as a3,
        TestClient(app, base_url="http://localhost:8080") as b1,
    ):
        session_a1 = a1.post("/api/v1/session", json={}, headers={**base_headers, "X-Forwarded-For": "1.1.1.1, 203.0.113.10, 172.18.0.5"})
        assert session_a1.status_code == 200
        a1.headers.update({**base_headers, "X-CSRF-Token": session_a1.json()["csrf_token"]})
        assert a2.post("/api/v1/session", json={}, headers={**base_headers, "X-Forwarded-For": "5.5.5.5, 203.0.113.10, 172.18.0.5"}).status_code == 200
        # Spoofing a new leftmost IP still hits 203.0.113.10's quota.
        blocked_session = a3.post("/api/v1/session", json={}, headers={**base_headers, "X-Forwarded-For": "9.9.9.9, 203.0.113.10, 172.18.0.5"})
        assert blocked_session.status_code == 429
        # Different real visitor behind the same tunnel proxy is unaffected.
        session_b1 = b1.post("/api/v1/session", json={}, headers={**base_headers, "X-Forwarded-For": "203.0.113.11, 172.18.0.5"})
        assert session_b1.status_code == 200
        b1.headers.update({**base_headers, "X-CSRF-Token": session_b1.json()["csrf_token"]})

        # Same isolation holds for run creation rate limits.
        pa1 = a1.post("/api/v1/projects", json={"client_key": "proxy-rl-a1", "title": "A1"}).json()
        pa2 = a1.post("/api/v1/projects", json={"client_key": "proxy-rl-a2", "title": "A2"}).json()
        pa3 = a1.post("/api/v1/projects", json={"client_key": "proxy-rl-a3", "title": "A3"}).json()
        pb1 = b1.post("/api/v1/projects", json={"client_key": "proxy-rl-b1", "title": "B1"}).json()

        assert a1.post(f"/api/v1/projects/{pa1['id']}/runs", json={"prompt": "一", "expected_revision": 0, "base_version_id": None}, headers={"X-Forwarded-For": "8.8.8.8, 203.0.113.10, 172.18.0.5", "Idempotency-Key": "proxy-run-a1"}).status_code == 202
        assert a1.post(f"/api/v1/projects/{pa2['id']}/runs", json={"prompt": "二", "expected_revision": 0, "base_version_id": None}, headers={"X-Forwarded-For": "8.8.4.4, 203.0.113.10, 172.18.0.5", "Idempotency-Key": "proxy-run-a2"}).status_code == 202
        blocked_run = a1.post(f"/api/v1/projects/{pa3['id']}/runs", json={"prompt": "三", "expected_revision": 0, "base_version_id": None}, headers={"X-Forwarded-For": "4.4.4.4, 203.0.113.10, 172.18.0.5", "Idempotency-Key": "proxy-run-a3"})
        assert blocked_run.status_code == 429
        assert blocked_run.json()["detail"]["code"] == "rate_limited"
        assert b1.post(f"/api/v1/projects/{pb1['id']}/runs", json={"prompt": "B1", "expected_revision": 0, "base_version_id": None}, headers={"X-Forwarded-For": "203.0.113.11, 172.18.0.5", "Idempotency-Key": "proxy-run-b1"}).status_code == 202
