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
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    llm_response_mode: str = "text"
    llm_thinking_mode: str = ""
    llm_token_limit_param: str = "max_tokens"
    llm_provider_max_output_tokens: int = 393216
    llm_request_timeout_seconds: int = 1500
    vidu_api_key: str = ""
    vidu_base_url: str = "https://api.vidu.cn"
    vidu_model: str = "viduq3-pro"
    vidu_resolution: str = "540p"
    vidu_poll_seconds: float = 5
    vidu_credit_price_cny: Decimal = Field(default=Decimal("0.03125"),gt=0,le=100)
    media_root: str = "./.media"
    run_concurrency: int = Field(default=3, ge=1, le=8)
    run_timeout_seconds: int = 3600
    pending_timeout_seconds: int = 3600
    read_only_mode: bool = False
    test_fixture: bool = False

    @model_validator(mode="after")
    def validate_provider(self):
        vidu=urlsplit(self.vidu_base_url)
        if vidu.scheme!="https" or vidu.hostname not in {"api.vidu.cn","api.vidu.com"} or vidu.username or vidu.password or vidu.query or vidu.fragment or vidu.path not in {"","/"} or vidu.port not in {None,443}:
            raise ValueError("VIDU_BASE_URL 必须是官方 HTTPS API 地址")
        if self.vidu_model!="viduq3-pro" or self.vidu_resolution not in {"540p","720p","1080p"} or not 1<=self.vidu_poll_seconds<=60:
            raise ValueError("Vidu 模型、分辨率或轮询间隔无效")
        origin=urlsplit(self.app_origin)
        if origin.scheme not in {"http","https"} or not origin.hostname or origin.username or origin.password or origin.query or origin.fragment or self.app_origin!=origin.scheme+"://"+origin.netloc:
            raise ValueError("APP_ORIGIN 必须是精确站点 origin，不能包含路径或末尾斜杠")
        if self.llm_base_url:
            url=urlsplit(self.llm_base_url)
            if url.username or url.password or url.query or url.fragment or not url.hostname:
                raise ValueError("模型基址必须是不含凭据、查询参数或片段的 URL")
            if url.scheme!="https" and not (self.app_env!="production" and url.scheme=="http" and url.hostname in {"localhost","127.0.0.1","::1"}):
                raise ValueError("模型服务应使用 HTTPS，本地测试服务可使用回环 HTTP")
        return self

    @property
    def model_configured(self):
        return bool(self.llm_base_url and self.llm_model and self.llm_api_key) or (
            self.app_env == "test" and self.test_fixture
        )

    @property
    def video_configured(self):
        return bool(self.vidu_api_key) or (self.app_env == "test" and self.test_fixture)


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
