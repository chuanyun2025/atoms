"""Transport for the isolated artifact compiler and browser checks."""
import httpx
from .config import settings


async def validate_artifact(artifact, request_id, kind, lightweight_3d, *, require_game_playtest=False):
    timeout = 65 if lightweight_3d else 31 if kind == "game" else 23
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        response = await client.post(
            settings().validator_url + "/internal/validate",
            headers={"Authorization": "Bearer " + settings().service_token},
            json={"artifact": artifact, "app_origin": settings().app_origin, "request_id": request_id,
                  "lightweight_3d": lightweight_3d, "preview_kind": kind,
                  "require_game_playtest": require_game_playtest},
        )
        response.raise_for_status()
        return response.json()
