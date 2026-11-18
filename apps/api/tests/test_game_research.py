import asyncio

import httpx

from atoms.core.config import settings
from atoms.domains import game_research


def test_live_research_keeps_published_genre_matches(monkeypatch):
    monkeypatch.setattr(settings(), "test_fixture", False)
    monkeypatch.setattr(game_research, "_cache", {})
    original = httpx.AsyncClient
    requests = []

    def store(request):
        requests.append(request.url)
        if request.url.path == "/search/results/":
            return httpx.Response(
                200,
                json={"results_html": " ".join(f'<a data-ds-itemkey="App_{number}"></a>' for number in (11, 22, 33))},
            )
        app_id = request.url.params["appids"]
        return httpx.Response(
            200,
            json={
                app_id: {
                    "data": {
                        "type": "game",
                        "genres": [{"id": "9"}],
                        "name": {"11": "Open World Adventure", "22": "Circuit Race", "33": "Future Racing"}[app_id],
                        "short_description": "An adventure in a large city"
                        if app_id == "11"
                        else "Race on closed tracks",
                        "release_date": {"coming_soon": app_id == "33"},
                    }
                }
            },
        )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(store)))
    result = asyncio.run(game_research.find_game_references("racing"))
    assert result["status"] == "live"
    assert requests[0].params["tags"] == "699" and requests[0].params["filter"] == "topsellers"
    assert [game["title"] for game in result["games"]] == ["Circuit Race"]
    assert result["games"][0]["url"].endswith("/app/22/")
