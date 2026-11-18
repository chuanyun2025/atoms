"""Transport for the isolated artifact compiler and browser checks."""

import httpx

from atoms.core.config import settings


async def validate_artifact(artifact, request_id, kind, lightweight_3d):
    async with httpx.AsyncClient(timeout=65 if lightweight_3d else 23, trust_env=False) as client:
        response = await client.post(
            settings().validator_url + "/internal/validate",
            headers={"Authorization": "Bearer " + settings().service_token},
            json={
                "artifact": artifact,
                "app_origin": settings().app_origin,
                "request_id": request_id,
                "lightweight_3d": lightweight_3d,
                "preview_kind": kind,
            },
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict) or type(payload.get("ok")) is not bool:
            raise httpx.RemoteProtocolError("校验服务返回无效响应", request=response.request)
        return payload
