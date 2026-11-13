"""Validate the design shipped with a new playable game project."""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

from .artifacts import strict_json

DESIGN_FILE = "src/game/design.json"
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=360)]
ControlId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,39}$")]
KeyName = Annotated[str, StringConstraints(pattern=r"^(?:[a-z0-9]|Arrow(?:Left|Right|Up|Down)|Space|Enter|Shift)$")]


class GameplayCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    label: Description
    key: KeyName | None = None
    with_key: KeyName | None = None
    control: ControlId | None = None
    pointer: Literal["primary"] | None = None
    hold_ms: int = Field(default=0, ge=0, le=1200)
    fresh_start: bool = False
    signal: ControlId
    change: Literal["increase", "decrease", "unchanged", "equals"]
    min_delta: float = Field(default=0.01, gt=0, le=1_000_000)
    value: Description | None = None

    @model_validator(mode="after")
    def check_input(self):
        if sum(item is not None for item in (self.key,self.control,self.pointer))!=1:
            raise ValueError("填写一个键盘按键、可见的按钮 ID 或主鼠标键；持续输入用 hold_ms 声明")
        if self.with_key is not None and (not self.key or self.key==self.with_key or not self.hold_ms):
            raise ValueError("组合键需要不同的主键与辅助键，并指定按住时长")
        if (self.change == "equals") != (self.value is not None):
            raise ValueError("equals 需要 value，其他检查只比较操作前后的状态")
        return self


class GamePlaytest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["turn_based", "realtime"]
    actions: list[ControlId] = Field(max_length=96)
    checks: list[GameplayCheck] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def check_actions(self):
        if self.mode == "turn_based" and not self.actions:
            raise ValueError("回合制游戏需要一条可通关的操作序列")
        if self.mode == "realtime" and self.actions:
            raise ValueError("实时游戏使用空操作序列")
        return self


class GameDesign(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    genre: Description
    objective: Description
    controls: Description
    loop: list[Description] = Field(min_length=3, max_length=6)
    progression: Description
    feedback: Description
    ending: Description
    art_direction: Description
    playtest: GamePlaytest


def validate_game_design(files: dict) -> GameDesign:
    try:
        design=GameDesign.model_validate(strict_json(files[DESIGN_FILE]))
        prior_directions={}
        for check in design.playtest.checks:
            # Earlier manifests could describe a held button without a duration.
            if check.control and not check.hold_ms and re.search(r"按住|长按|\bhold\b",check.label,re.I):
                check.hold_ms=320
                check.fresh_start=True
            if check.signal in ("screen-x","screen-y") and check.change in ("increase","decrease"):
                previous=prior_directions.get(check.signal)
                if check.hold_ms and previous and previous.change!=check.change and "fresh_start" not in check.model_fields_set:
                    check.fresh_start=True
                prior_directions[check.signal]=check
        return design
    except ValidationError as error:
        details = [".".join(map(str, issue["loc"])) + " " + issue["msg"] for issue in error.errors()]
        raise ValueError(f"{DESIGN_FILE} 的字段不符合玩法设计约定：{', '.join(details)}") from None
    except (ValueError,KeyError,TypeError,AttributeError):
        raise ValueError(f"{DESIGN_FILE} 缺失或无法读取") from None
