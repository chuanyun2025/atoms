"""Settings read only by the internal provider gateway."""
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderSettings(BaseSettings):
    model_config = SettingsConfigDict(hide_input_in_errors=True)
    provider_gateway_token: SecretStr
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_response_mode: str = "text"
    llm_thinking_mode: str = ""
    llm_token_limit_param: str = "max_tokens"
    llm_provider_max_output_tokens: int = Field(default=393216, gt=0)
    llm_request_timeout_seconds: int = Field(default=1500, gt=0)
    llm_stream: bool = False
    vidu_api_key: SecretStr = SecretStr("")
    vidu_base_url: str = "https://api.vidu.cn"
    vidu_model: str = Field(default="viduq3-pro", pattern=r"^[A-Za-z0-9._-]{1,128}$")
    provider_max_concurrency: int = Field(default=3, ge=1, le=32)
    provider_requests_per_minute: int = Field(default=120, ge=1)
    provider_kms_region: str = ""
    provider_kms_endpoint: str = ""
    provider_kms_role: str = ""
    llm_kms_secret_name: str = ""
    vidu_kms_secret_name: str = ""

    @model_validator(mode="after")
    def check_config(self):
        if len(self.provider_gateway_token.get_secret_value()) < 24:
            raise ValueError("Provider gateway token is required")
        if self.llm_base_url:
            url = urlsplit(self.llm_base_url)
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("Text provider requires an HTTPS URL without credentials or query parameters")
        vidu = urlsplit(self.vidu_base_url)
        if vidu.scheme != "https" or vidu.netloc not in {"api.vidu.cn","api.vidu.com","api.vidu.cn:443","api.vidu.com:443"} or vidu.path not in {"","/"} or vidu.query or vidu.fragment:
            raise ValueError("Vidu requires its official HTTPS endpoint")
        if self.llm_response_mode not in {"text","json_object","json_schema"} or self.llm_thinking_mode not in {"","enabled","disabled"} or self.llm_token_limit_param not in {"max_tokens","max_completion_tokens"}:
            raise ValueError("Unsupported text provider options")
        if (self.llm_kms_secret_name or self.vidu_kms_secret_name) and not self.provider_kms_region:
            raise ValueError("KMS region is required when using KMS secrets")
        return self
