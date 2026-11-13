"""Resolve provider credentials locally or through ECS RAM role and KMS."""
import asyncio
from functools import cached_property
from time import monotonic

from .provider_contract import ModelError
from .provider_settings import ProviderSettings


class ProviderSecrets:
    def __init__(self, config: ProviderSettings):
        self.config = config
        self.cache: dict[str, tuple[float, str]] = {}
        self.lock = asyncio.Lock()

    async def get(self, provider: str) -> str:
        name = getattr(self.config, provider + "_kms_secret_name")
        if not name:
            return getattr(self.config, provider + "_api_key").get_secret_value()
        async with self.lock:
            cached = self.cache.get(name)
            if cached and cached[0] > monotonic():
                return cached[1]
            try:
                secret = await asyncio.to_thread(self.read_kms, name)
                if not isinstance(secret, str) or not secret.strip():
                    raise ValueError("Empty KMS secret")
            except Exception:
                raise ModelError("PROVIDER_SECRET_UNAVAILABLE","供应商凭据暂不可用，请联系管理员") from None
            self.cache[name] = (monotonic() + 300, secret.strip())
            return secret.strip()

    @cached_property
    def kms(self):
        from alibabacloud_credentials.client import Client as CredentialClient
        from alibabacloud_credentials.models import Config as CredentialConfig
        from alibabacloud_kms20160120.client import Client
        from alibabacloud_tea_openapi.models import Config

        credentials = CredentialClient(CredentialConfig(
            type="ecs_ram_role", role_name=self.config.provider_kms_role or None,
            disable_imds_v1=True, connect_timeout=2000, timeout=3000,
        ))
        return Client(Config(
            credential=credentials, region_id=self.config.provider_kms_region,
            endpoint=self.config.provider_kms_endpoint or f"kms.{self.config.provider_kms_region}.aliyuncs.com",
            connect_timeout=2000, read_timeout=4000,
        ))

    def read_kms(self, name: str) -> str:
        from alibabacloud_kms20160120.models import GetSecretValueRequest
        return self.kms.get_secret_value(GetSecretValueRequest(secret_name=name)).body.secret_data
