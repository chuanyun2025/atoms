from functools import lru_cache
from decimal import Decimal
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, model_validator
from urllib.parse import urlsplit


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../../.env.local", extra="ignore")
    app_env: str = "development"
    app_origin: str = "http://localhost:8080"
    cookie_secure: bool = False
    session_secret: str = ""
    service_token: str = ""
    database_url: str = "sqlite:///./atoms.db"
    validator_url: str = "http://validator:9000"
    provider_gateway_url: str = "http://provider-gateway:8100"
    provider_gateway_token: str = ""
    provider_gateway_timeout_seconds: int = Field(default=1510,gt=0)
    vidu_model: str = "viduq3-pro"
    vidu_resolution: str = "540p"
    vidu_poll_seconds: float = 5
    vidu_credit_price_cny: Decimal = Field(default=Decimal("0.03125"),gt=0,le=100)
    media_root: str = "./.media"
    run_concurrency: int = Field(default=1, ge=1, le=8)
    run_timeout_seconds: int = 3600
    pending_timeout_seconds: int = 3600
    read_only_mode: bool = False
    test_fixture: bool = False

    @model_validator(mode="after")
    def validate_provider(self):
        if self.vidu_model!="viduq3-pro" or self.vidu_resolution not in {"540p","720p","1080p"} or not 1<=self.vidu_poll_seconds<=60:
            raise ValueError("Vidu 模型、分辨率或轮询间隔无效")
        origin=urlsplit(self.app_origin)
        if origin.scheme not in {"http","https"} or not origin.hostname or origin.username or origin.password or origin.query or origin.fragment or self.app_origin!=origin.scheme+"://"+origin.netloc:
            raise ValueError("APP_ORIGIN 必须是精确站点 origin，不能包含路径或末尾斜杠")
        gateway=urlsplit(self.provider_gateway_url)
        if gateway.scheme not in {"http","https"} or not gateway.hostname or gateway.username or gateway.password or gateway.path not in {"","/"} or gateway.query or gateway.fragment:
            raise ValueError("网关地址必须是无凭据的服务 URL")
        return self


@lru_cache
def settings():
    value = Settings()
    if len(value.session_secret) < 32 or len(value.service_token) < 24:
        raise RuntimeError("请先运行 scripts/init_env.py，配置服务随机密钥")
    if value.app_env != "test" and value.test_fixture:
        raise RuntimeError("测试产物只能在 APP_ENV=test 使用")
    if value.app_env == "production" and (not value.cookie_secure or not value.app_origin.startswith("https://")):
        raise RuntimeError("生产环境必须配置 HTTPS APP_ORIGIN 和安全 Cookie")
    return value
