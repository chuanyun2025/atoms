from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectCreate(StrictModel):
    client_key: str = Field(min_length=8,max_length=100)
    title: str = Field(default="未命名项目",min_length=1,max_length=80)
    kind: Literal["web", "game", "slides", "video"] = "web"
    slide_template_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{0,63}$")


class VideoOptions(StrictModel):
    image_asset_id: str | None = Field(default=None,pattern=r"^[a-f0-9]{32}$")
    duration: int = Field(default=5,ge=1,le=16)
    audio: bool = True


class ImageUpload(StrictModel):
    data_url: str = Field(min_length=30,max_length=7_000_000)


class RunCreate(StrictModel):
    prompt: str = Field(min_length=1,max_length=100000)
    expected_revision: int = Field(ge=0)
    base_version_id: str | None = None
    retry_of_run_id: str | None = Field(default=None,min_length=1,max_length=100)
    video: VideoOptions | None = None

    @field_validator("prompt")
    @classmethod
    def nonempty(cls,value):
        if not value.strip():
            raise ValueError("请输入具体需求")
        return value.strip()


class Restore(StrictModel):
    expected_revision: int = Field(ge=0)


class StatePatch(StrictModel):
    expected_revision: int = Field(ge=0)
    version_id: str | None = None
    set: dict[str,Any] = Field(default_factory=dict,max_length=128)
    remove: list[str] = Field(default_factory=list,max_length=128)
