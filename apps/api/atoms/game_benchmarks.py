"""Source-backed genre references used during planning, implementation and review."""

import re
from typing import Literal

GameGenre = Literal["fps", "platformer", "racing", "falling_blocks", "puzzle", "strategy", "survival",
                    "fighting", "role_playing", "sports", "simulation", "roguelike", "rhythm", "card", "sandbox", "other"]

BENCHMARKS = {
    "fps": {
        "sources": {
            "Counter-Strike 2": "https://www.counter-strike.net/cs2",
            "VALORANT": "https://playvalorant.com/en-us/news/game-updates/valorant-patch-notes-3-04/",
        },
        "conventions": [
            "桌面开局后移动鼠标即可转向，左键开火，WASD 移动，R 换弹，Esc 释放鼠标并暂停。触屏提供独立的视角手势与射击控件。",
            "敌人开火在场景中呈现可追踪的曳光或可见飞行弹丸，能看出火力来源。反馈与命中、掩体遮挡及受击一致。",
            "关卡需要可识别的路线与掩体，敌人、武器、命中和回合进程要有清晰的视觉反馈。",
        ],
    },
    "platformer": {
        "sources": {"New Super Mario Bros.": "https://www.nintendo.com/eu/media/downloads/games_8/emanuals/nintendo_ds_21/Manual_NintendoDS_NewSuperMarioBros_EN.pdf"},
        "conventions": [
            "横向移动与跳跃可同时操作。适合玩法时，短按与长按产生不同跳跃高度，并清楚表现起跳、落地和碰撞。",
            "用安全的第一处跳跃教授操作，再逐步增加平台间距、障碍或机关。坠落、检查点和终点有明确反馈。",
        ],
    },
    "racing": {
        "sources": {
            "Gran Turismo 7": "https://blog.playstation.com/2022/02/02/gran-turismo-7-state-of-play-recap-and-your-first-few-hours-with-the-game/",
            "Forza Horizon 6": "https://store.steampowered.com/app/2483190/Forza_Horizon_6/",
            "Mario Kart": "https://www.nintendo.com/eu/media/downloads/games_8/emanuals/nintendo_8/Manual_Nintendo64_MarioKart64_EN.pdf",
        },
        "conventions": [
            "加速、制动和转向是独立的连续输入。车辆速度、转弯反馈和赛道边界清楚可辨。",
            "检查点按顺序通过并更新圈数或剩余时间。离开赛道可恢复，终点给出明确成绩，画面能看清下一个弯道。",
            "常规街机竞速采用低位跟车透视，赛道有连贯弯道、边界和路标。用不同车道安排可躲避的障碍、可收集的加速资源及驾驶反馈。",
        ],
    },
    "falling_blocks": {
        "sources": {"Tetris Marathon": "https://play.tetris.com/games/marathon/"},
        "conventions": [
            "左右移动、旋转、软降和硬降各有明确操作，旋转和落地遵守边界与已有方块碰撞。",
            "方块落定后生成下一块，满行立即清除并反馈分数，随进度提升速度，堆至顶部结束。",
        ],
    },
}

GENRE_PATTERNS = {
    "platformer": r"平台跳跃|横版跳跃|马里奥|\bplatformer\b|\bmario\b",
    "racing": r"赛车|竞速|卡丁车|跑跑卡丁|\bracing\b|\bkart\b",
    "falling_blocks": r"俄罗斯方块|落块|\btetris\b|\bfalling blocks\b",
    "puzzle": r"解谜|益智|拼图|\bpuzzle\b",
    "strategy": r"策略|塔防|战棋|\bstrategy\b|tower defense",
    "survival": r"生存|\bsurvival\b",
    "fighting": r"格斗|拳皇|街霸|\bfighting\b",
    "role_playing": r"角色扮演|\brpg\b",
    "sports": r"足球|篮球|网球|\b(?:soccer|basketball|tennis)\b",
    "simulation": r"模拟经营|城市建造|\bsimulation\b",
    "roguelike": r"肉鸽|\brogue(?:like|lite)\b|\bhades\b",
    "rhythm": r"音游|音乐节奏|节奏游戏|\brhythm\b",
    "card": r"卡牌|牌组|\bdeckbuild(?:ing|er)\b|card game",
    "sandbox": r"沙盒|我的世界|\bsandbox\b|\bminecraft\b",
}


def match_genre(request: str) -> GameGenre | None:
    matches = [genre for genre, pattern in GENRE_PATTERNS.items() if re.search(pattern, request, re.I)]
    return matches[0] if len(matches) == 1 else None
