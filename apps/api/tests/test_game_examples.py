import pytest

from atoms.core.db import one, transaction
from atoms.domains.examples import EXAMPLES


@pytest.mark.parametrize("example_id", sorted(EXAMPLES))
def test_published_example_opens_without_an_original_project(client, example_id):
    # No private project, version, or owner is needed to load a published snapshot.
    client.cookies.clear()
    response = client.get(f"/api/v1/examples/{example_id}/preview-ticket")
    assert response.status_code == 200
    ticket = response.json()
    assert ticket["example_id"] == example_id
    assert "version_id" not in ticket and "project_id" not in ticket
    assert client.get(ticket["url"]).status_code == 403
    frame = client.get(ticket["url"], headers={"Sec-Fetch-Dest": "iframe", "Sec-Fetch-Site": "same-origin"})
    assert frame.status_code == 200
    assert "atoms-runtime-config" in frame.text
    assert "sandbox allow-scripts allow-pointer-lock;" in frame.headers["content-security-policy"]
    assert "allow-same-origin" not in frame.headers["content-security-policy"]
    with transaction() as conn:
        assert one(conn, "SELECT COUNT(*) AS n FROM projects")["n"] == 0
        assert one(conn, "SELECT COUNT(*) AS n FROM model_calls")["n"] == 0


def test_example_tickets_cannot_open_other_examples_or_private_versions(client):
    ticket = client.get("/api/v1/game-examples/jungle-assault/preview-ticket").json()
    headers = {"Sec-Fetch-Dest": "iframe", "Sec-Fetch-Site": "same-origin"}
    other = ticket["url"].replace("/jungle-assault?", "/meadow-journey?")
    assert client.get(other, headers=headers).status_code == 403
    private = ticket["url"].replace("/examples/jungle-assault?", "/versions/private-version?")
    assert client.get(private, headers=headers).status_code == 403
    assert client.get("/api/v1/game-examples/unknown/preview-ticket").status_code == 404
