"""Short generation and review guidance for related game genres."""

_PROFILES = (
    ("动作与闯关", {"fps", "platformer", "fighting", "survival", "roguelike"},
     "围绕清晰的操控、反馈和挑战设计完整一局。视角、地图、资源、敌人与胜负机制按本次需求选择。",
     "用实际输入核对主动作、反馈和进程。按已实现的机制检查碰撞与目标，接受同等可用的输入和关卡设计。"),
    ("竞速与体育", {"racing", "sports"},
     "突出操控响应、可读的场地和比赛目标。按子类型选择视角、计时、得分或赛程，场地有自己的路线和地标。",
     "验证方向或动作符合直觉、比赛状态能推进并有明确结果。按所选赛制验收，奖励、障碍、圈数和对手都是设计选项。"),
    ("解谜与节奏", {"puzzle", "falling_blocks", "rhythm"},
     "让玩家能读懂规则、合法操作和反馈。通过关卡、节拍或逐步变化的局势建立挑战，允许不同解法。",
     "用真实操作验证核心规则及状态变化。适合确定性回放的玩法验证一条可达的路径，接受其他有效路线。"),
    ("策略与经营", {"strategy", "simulation", "card", "role_playing", "sandbox"},
     "提供可理解的选择、资源或世界状态，让玩家看到决策后果。回合制、实时、沙盒及目标结构按需求选择。",
     "验证关键决策真实改变状态，且规则、反馈和下一步可理解。开放式玩法按其目标核对，回合与资源机制按实际设计检查。"),
)


def game_profile(genre: str | None) -> dict:
    for name,genres,generation,review in _PROFILES:
        if genre in genres:
            return {"name":name,"generation":generation,"review":review}
    return {"name":"通用游戏","generation":"明确目标、主要输入、规则、反馈和可继续的流程。",
            "review":"按原始需求核对游戏的实际核心行为和可操作性，接受与目标相符的不同实现。"}
