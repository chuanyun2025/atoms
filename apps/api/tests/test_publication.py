from conftest import create_project
from fastapi.testclient import TestClient
from test_workflow import complete

from atoms.main import app


def test_publication_lifecycle_and_visitor_isolation(client):
    project, _ = complete(client, create_project(client))
    first_version = project["current_version_id"]
    manage = f"/api/v1/projects/{project['id']}/publication"
    assert client.get(manage).json() == {"publication": None}
    first = client.put(manage, json={"action": "publish", "version_id": first_version, "expected_revision": 0})
    assert first.status_code == 200
    publication = first.json()["publication"]
    public_url = "/api/v1/publications/" + publication["slug"]
    assert publication["path"] == "/p/" + publication["slug"]
    assert publication["version_number"] == 1

    with TestClient(app, base_url="http://localhost:8080") as outsider:
        ticket = outsider.get(public_url)
        assert ticket.status_code == 200
        assert ticket.headers["cache-control"] == "no-store"
        assert "set-cookie" not in ticket.headers
        assert set(ticket.json()) == {"title", "url", "instance_id", "channel_nonce", "read_only"}
        iframe_url = ticket.json()["url"]
        iframe = {"sec-fetch-dest": "iframe", "sec-fetch-site": "same-origin"}
        assert outsider.get(iframe_url).status_code == 403
        document = outsider.get(iframe_url, headers=iframe)
        assert document.status_code == 200
        assert "sandbox allow-scripts allow-pointer-lock;" in document.headers["content-security-policy"]
        assert "allow-same-origin" not in document.headers["content-security-policy"]
        assert outsider.get(manage).status_code == 401
        visitor = outsider.post(
            "/api/v1/session",
            json={},
            headers={
                "Origin": "http://localhost:8080",
                "X-App-Request": "atoms",
            },
        ).json()
        outsider.headers.update(
            {"Origin": "http://localhost:8080", "X-App-Request": "atoms", "X-CSRF-Token": visitor["csrf_token"]}
        )
        assert outsider.get(manage).status_code == 404
        assert outsider.put(manage, json={"action": "unpublish", "expected_revision": 1}).status_code == 404

        second, _ = complete(client, project, "更新测试", "publish-second")
        assert client.get(manage).json()["publication"]["version_id"] == first_version
        assert outsider.get(iframe_url, headers=iframe).status_code == 200
        version = second["current_version_id"]
        other, _ = complete(
            client,
            client.post("/api/v1/projects", json={"client_key": "other-project", "title": "其他作品"}).json(),
            request_key="publish-other",
        )
        assert (
            client.put(
                manage, json={"action": "publish", "version_id": other["current_version_id"], "expected_revision": 1}
            ).status_code
            == 404
        )
        assert (
            client.put(manage, json={"action": "publish", "version_id": version, "expected_revision": 0}).status_code
            == 409
        )

        changed = client.put(manage, json={"action": "publish", "version_id": version, "expected_revision": 1}).json()[
            "publication"
        ]
        assert changed["path"] == publication["path"]
        assert changed["version_number"] == 2 and changed["previous_version_number"] == 1
        assert outsider.get(iframe_url, headers=iframe).status_code == 409

        rollback = client.put(manage, json={"action": "rollback", "expected_revision": 2}).json()["publication"]
        assert rollback["version_id"] == first_version
        assert client.get(f"/api/v1/projects/{project['id']}").json()["current_version_id"] == version
        current_ticket = outsider.get(public_url).json()["url"]
        assert (
            client.put(manage, json={"action": "unpublish", "expected_revision": 3}).json()["publication"]["published"]
            is False
        )
        assert outsider.get(public_url).status_code == 410
        assert outsider.get(current_ticket, headers=iframe).status_code == 410
        republished = client.put(
            manage, json={"action": "publish", "version_id": version, "expected_revision": 4}
        ).json()["publication"]
        assert republished["path"] == publication["path"] and republished["published"]
