"""Source-backed genre references used during planning, implementation and review."""

import re
from typing import Literal
from unicodedata import normalize

GameGenre = Literal[
    "fps",
    "arcade_platformer",
    "platformer",
    "tile_merge",
    "match3",
    "tower_defense",
    "racing",
    "falling_blocks",
    "puzzle",
    "strategy",
    "survival",
    "fighting",
    "role_playing",
    "sports",
    "simulation",
    "roguelike",
    "rhythm",
    "card",
    "sandbox",
    "other",
]

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
        "sources": {
            "New Super Mario Bros.": "https://www.nintendo.com/eu/media/downloads/games_8/emanuals/nintendo_ds_21/Manual_NintendoDS_NewSuperMarioBros_EN.pdf"
        },
        "conventions": [
            "横向移动与跳跃可同时操作。适合玩法时，短按与长按产生不同跳跃高度，并清楚表现起跳、落地和碰撞。",
            "用安全的第一处跳跃教授操作，再逐步增加平台间距、障碍或机关。坠落、检查点和终点有明确反馈。",
        ],
    },
    "arcade_platformer": {
        "sources": {"SNOW BROS.": "https://www.toaplangames.co.jp/en/license/license-20.html"},
        "conventions": [
            "固定屏内利用多层平台和敌人位置作决策，清场后切换到新的布局。",
            "捕获、释放和碰撞有不同反馈。雪人兄弟风格可用冻结与雪球连锁呈现这套规则。",
        ],
    },
    "match3": {
        "sources": {"Phaser Games Examples": "https://phaser.io/oss/examples/v4.1.0/games"},
        "conventions": ["相邻交换后检测匹配，依次结算消除、掉落与补位。关卡有可读目标和实际改变胜负的步数或计时。"],
    },
    "tower_defense": {
        "sources": {"Phaser Games Showcase": "https://www.phaser.io/games"},
        "conventions": [
            "敌人沿可读路线推进，波次之间提供调整防线的机会。花费、命中、漏怪和升级都应立即反映到游戏状态。"
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
            "用适合当前视角的构图呈现连贯弯道、边界和路标。按玩法安排可躲避的障碍、可收集的加速资源及驾驶反馈。",
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

SPECIFIC_GENRE_PATTERNS = {
    "arcade_platformer": r"雪人兄弟|泡泡龙(?:街机|闯关)|固定(?:屏|画面).{0,10}(?:平台|清怪|清场)|\bsnow\s*bros\b|\bbubble\s+bobble\b|\b(?:fixed|single)[ -]screen (?:arcade )?platformer\b",
    "match3": r"三消|三连消除|连成三个|宝石迷阵|消消乐|\bmatch[ -]?(?:3|three)\b|\bbejeweled\b|\bcandy crush\b",
    "tile_merge": r"(?<![a-z0-9])2048(?![a-z0-9]|\s*(?:[x×*]\s*\d|px\b|像素|分辨率|分|金币|关|年))|数字滑块|数字合并(?:游戏|方块)|滑动合并方块",
    "tower_defense": r"塔防|植物大战僵尸|保卫萝卜|\btower[ -]defen[cs]e\b|\bplants vs\.? zombies\b",
}

GENRE_PATTERNS = {
    "platformer": r"平台跳跃|横版跳跃|马里奥|滚屏.{0,8}平台|\bplatformer\b|\bmario\b",
    "racing": r"赛车|竞速|卡丁车|跑跑卡丁|\bracing\b|\bkart\b",
    "falling_blocks": r"俄罗斯方块|落块|\btetris\b|\bfalling blocks\b",
    "puzzle": r"解谜|益智|拼图|\bpuzzle\b",
    "strategy": r"策略|战棋|\bstrategy\b",
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


_NEGATED_GENRE = re.compile(
    r"(?:不要|(?<![特区差分性个告])别|不想|不希望|不需要|不做|不搞|不使用|不用|不是|避免|排除|非|\b(?:not|no|without|avoid|don['’]t)\b)"
    r"\s*(?:(?:做成?|制作|生成|开发|选择|类似|像|make|build|create|use)\s*)?"
    r"(?:(?:一个|一款|这种|那种|a\b|an\b)\s*)?[“‘'\"《「]?$",
    re.I,
)
_ALTERNATIVE = re.compile(r"\s*(?:、|[/／]|或者|或是|或|以及|和|及|与|or|and|那种)\s*", re.I)


def genre_preferences(request: str) -> tuple[GameGenre | None, set[GameGenre]]:
    request = normalize("NFKC", request)
    mentions = sorted(
        (match.start(), match.end(), genre)
        for genre, pattern in (SPECIFIC_GENRE_PATTERNS | GENRE_PATTERNS).items()
        for match in re.finditer(pattern, request, re.I)
    )
    choices = {}
    previous_end = 0
    previous_negated = False
    for start, end, genre in mentions:
        between = request[previous_end:start] if start >= previous_end else ""
        negated = bool(_NEGATED_GENRE.search(request[max(0, start - 64) : start])) or (
            previous_negated and bool(_ALTERNATIVE.fullmatch(between))
        )
        choices[genre] = negated
        if end > previous_end:
            previous_end = end
            previous_negated = negated
    excluded = {genre for genre, negated in choices.items() if negated}
    positive = [genre for genre, negated in choices.items() if not negated]
    matches = [genre for genre in positive if genre in SPECIFIC_GENRE_PATTERNS] or positive
    return (matches[0] if len(matches) == 1 else None), excluded


def match_genre(request: str) -> GameGenre | None:
    return genre_preferences(request)[0]
