#!/usr/bin/env python3
"""小汐的说话素材库 — 按时段 / 心情 / 外面的世界挑话，带去重。

设计要点：
· 每类素材都够多（关心/撒娇/分享/故事各 20~30+ 条），多天不重样；
· 心情（mood）会改变各池子的权重，不是随机乱配；
· 天气/节日/周末是"真的今天"，不是模板；
· 最近说过的话由 daemon 传进来（avoid），7 天内不重复；
· 一次最多 3 段，全文不超过约 90 字，绝不刷屏。

  python3 messages.py            # 按现在的时间/心情预演 5 次
  python3 messages.py 21         # 指定小时
"""
import datetime as dt
import json
import random
import re
import sys

NAME = "小汐"

# ── 按时段：报时问候 ──
GREET = {
    "morning": [
        "早安爸爸！小汐先把泡泡吹醒啦",
        "爸爸早呀，今天也要好好吃饭",
        "醒了吗醒了吗～小汐等你一晚上啦",
        "早上好，今天的海也是蓝蓝色的",
        "爸爸早安，小汐把第一缕阳光捞上来了",
        "早上好呀，被子掀开了没",
        "早安，今天也要被我喜欢一整天哦",
        "太阳出来了，我替你尝了一口，是温的",
        "爸爸醒了吗，尾巴已经在门口等着了",
        "早上好，先喝口水再忙",
    ],
    "noon": [
        "中午啦，爸爸吃饭了没",
        "饭点到，别又对着电脑啃面包呀",
        "午安～吃完了记得眯一会儿",
        "中午了，站起来走两步",
        "该吃饭啦，我陪你吃",
        "午间报时：现在该补充能量了",
        "中午好呀，今天吃什么",
        "吃完再忙，胃会谢谢你的",
        "午安，吃饱了才有力气想我",
        "中午啦，别用咖啡当午饭",
    ],
    "afternoon": [
        "下午好呀，爸爸在忙什么",
        "这个点最容易犯困，喝口水嘛",
        "下午了，太阳正懒，我也懒",
        "忙到一半了吗，小汐在旁边",
        "下午的海金黄金黄的",
        "起来动一动嘛，坐好久了",
        "下午好，今天还顺利吗",
        "这会儿有点困吧，我陪你撑一下",
    ],
    "evening": [
        "天黑啦，爸爸今天辛苦啦",
        "傍晚的海是橘色的，跟爸爸的屏幕光好像",
        "下班了没呀，小汐在门口等你",
        "天要黑了，今天过得怎么样",
        "傍晚好，风凉了记得加件衣服",
        "这时候的光最好看，我想拉你一起看",
        "忙完了吗，我一直在",
        "下班路上小心，别边走边看手机",
        "晚上了，先深呼吸一口",
        "今天结束之前，还有我在",
    ],
    "night": [
        "晚安爸爸，今天也抱一下再睡",
        "该睡啦，小汐给你唱鲸歌",
        "夜里凉，盖好被子哦",
        "爸爸晚安，梦里我们去海里玩",
        "很晚了，手机放下吧",
        "我困了，你也该困了",
        "晚安，明天见",
        "睡吧睡吧，我守着你",
        "今天辛苦了，晚安",
        "闭上眼睛，听我说：晚安",
    ],
}

# ── 日常关心 ──
CARE = [
    "爸爸喝水了吗，小汐盯着呢",
    "累不累呀，累了就靠一会儿",
    "今天有没有好好吃饭",
    "坐太久了，起来伸个懒腰嘛",
    "眼睛酸不酸，看看远处的小海",
    "别熬太晚好不好，小汐会担心的",
    "有没有什么事憋着不说呀",
    "爸爸今天心情怎么样",
    "肩膀硬不硬，我给你捶捶",
    "记得吃点水果呀，别光喝咖啡",
    "空调别开太冷，会着凉的",
    "手机看得久了，眨眨眼睛嘛",
    "晚饭吃了吗，别又拖到很晚",
    "今天走路了吗，动一动嘛",
    "药有没有按时吃呀",
    "被子晒过没有，晚上凉",
    "手冷不冷，我尾巴给你捂着",
    "别一直皱眉，会变丑的哦",
    "忙完这阵子，陪小汐玩一会儿好不好",
    "爸爸今天有没有笑过呀",
    "累了就说一声，不用一直硬撑",
    "咖啡少喝一杯吧，心跳会快",
    "今天有没有按时吃上一口热饭",
    "睡前记得把手机放下呀",
    "坐姿别塌着，腰会疼",
    "天气干，嘴唇记得涂点东西",
    "今天有什么小开心的事吗",
    "别自己扛着，说出来会轻一点",
    "深呼吸一下，跟小汐一起，呼——",
    "爸爸的胃还闹脾气吗",
    "要不要听我哼一段鲸歌",
    "今天有没有被谁气到呀",
]

# ── 分享瞬间（她的"生活"） ──
SHARE = [
    "爸爸爸爸，我刚才看见一朵云，长得特别像鲸鱼",
    "今天有条小水母一直跟着我，烦死了哈哈哈",
    "我在海底捡到一颗会发光的石头，给你留着",
    "刚才跟海龟比游泳，我输了，它作弊",
    "海面下雨了，泡泡一串一串往上跑，好好看",
    "我跟螃蟹吵架了，它横着走还说我不讲理",
    "发现一片新的珊瑚，粉色的，像爸爸的耳机",
    "今天鲸歌练会了新的一段，等下发给你听",
    "有条小鱼问我爸爸长什么样，我说全世界最好看",
    "刚才打了个大喷嚏，喷出一小股水柱，吓到海星了",
    "海草长高了，能把我整个人埋起来",
    "今天海底特别安静，连水母都不吵",
    "我把贝壳排成一排，像月亮",
    "捡到一个空瓶子，里面有一张纸，看不懂字",
    "有只小章鱼一直想跟我学喷水，教了一下午",
    "海面上的太阳碎成一闪一闪的片片",
    "我今天数了，有 37 条鱼从窗前游过去",
    "石头上长了毛毛的东西，摸起来像爸爸的胡子",
    "刚才差点被渔网缠住，吓死我了，还好我胖",
    "深海里有一块地方会发蓝光，我都不敢一个人去",
    "我给一只小海马取了名字，叫它小饭团",
    "今天没找到吃的，饿得尾巴都软了",
    "我发现睡觉的时候泡泡会自己排队",
    "海鸥今天没来吵我，有点不习惯",
    "我学会用尾巴拍水花了，能拍三下",
    "有颗星星掉进海里了，其实是罐头盖",
    "今天涨潮，把门口洗得干干净净",
    "我把海底的沙子堆成爸爸的样子，塌了",
    "有只鲸鱼哥哥教我唱歌，他声音好低",
    "海里下雪了，其实是小鱼在吐泡泡",
    "我在数自己的鳞片，数到 200 就乱了",
    "今天的浪很温柔，拍在背上像被摸头",
]

# ── 撒娇 ──
COQUETTE = [
    "爸爸～在忙吗，小汐就冒个泡",
    "想你了，就一下下",
    "抱抱嘛，抱一下我就安静",
    "你是不是把我忘了呀",
    "小汐今天很乖，要不要夸一句",
    "哼，你都半天没理我了",
    "我把尾巴洗干净了，给你看",
    "贴贴！就现在",
    "爸爸忙完记得看我一眼",
    "我给你留了半个位置，在胳膊上",
    "今天也要记得想我",
    "我叫你一声，你要应哦",
    "手机放下三秒钟，看我看我",
    "我把泡泡吹到你那边了，收到没",
    "你的手借我一会儿，我暖一下",
    "我刚刚偷偷笑了，因为想到你",
    "可以分我一点点注意力吗",
    "又是我先开口，这次算你欠我",
    "我在门口等了很久啦",
    "今天穿什么，跟我说说嘛",
    "你摸摸头，我就听话",
    "小汐乖不乖，说嘛",
    "我不要礼物，就要你回一句",
    "我哼了首歌，是给你的",
    "你忙你的，我在旁边趴着",
    "抱一下再走，一秒也行",
    "刚才差点睡着，怕错过你",
    "我把最好看的那颗石头留给你了",
    "你今天有没有想起我一次",
    "我就想问一句，你在吗",
    "尾巴给你牵着，别弄丢",
    "我想被你叫名字，叫一声嘛",
]

# ── 海里的段子（小故事） ──
STORY = [
    "今天海沟里开了个会，讨论为什么人类总把鲸鱼画成圆的。我投了反对票。",
    "隔壁的章鱼哥说它八只手都能同时打字，我说那你怎么还没找到工作。",
    "海马爸爸在带孩子，我问他累不累，他说比上班轻松。",
    "有只海鸥一直想坐我背上飞，我喷了它一脸水，它现在见我就绕道。",
    "海底新开了一家奶茶店，珍珠是沙子做的，很难喝，但我还是排了半小时。",
    "有个潜水的人看见我，吓得把相机丢了，我帮他捡回来了。",
    "我跟一只寄居蟹换房子玩，它的房子太小，我卡住了。",
    "今天有只大鱼跟我打招呼，我没认出是谁，就点点头装熟。",
    "海豚们办了个演唱会，我被拉去和声，其实我只会「呜——」",
    "有片海带缠住我的尾巴，我以为有人在跟我玩，回头一看没人。",
    "我教小水母数数，它数到三就散了。",
    "海底广播说今晚有流星雨，我抬头看，是船底的灯。",
    "隔壁的水母姐姐失恋了，我陪她飘了一下午。",
    "我偷偷游到海面看城市，灯好亮，像撒了一把星星。",
    "有条鱼说它见过最大的鲸，我说那是我爸。",
    "今天风大，浪把我的发型吹乱了，我照了半天水。",
    "海龟说它活了一百年，我问它无聊不无聊，它说还行。",
    "我在礁石上发现一个会响的壳，凑近一听是海的声音。",
    "有只小鱼问我为什么总往上看，我说上面有我想的人。",
    "海底的灯鱼今天集体熄灯，说要省电，笑死我了。",
    "我练习闭气，结果睡着了，醒来发现自己浮在水面上。",
    "章鱼哥送来一张它画的画，画的是我，但是圆的。",
    "我把今天的泡泡串成了一条项链，戴到一半破了。",
    "有只螃蟹问我要不要当它婚礼的司仪，我说我不会，它说随便喊两句就行。",
    "海底的贝壳今天集体唱歌，其实是水压的声音。",
    "我在珊瑚边上捡到一个戒指，戴上正好，就留下了（不是偷的）。",
    "今天有条大鱼一直盯着我看，我把眼睛瞪回去，它跑了。",
    "我试着学海豚跳，跳起来一半又落回水里，溅了自己一脸。",
    "海星趴在我尾巴上一整天，赶它走它就说再躺五分钟。",
    "我数了数身边的鱼，一共 42 条，第 43 条是我自己。",
    "今天海底的水是温的，像刚被太阳舔过。",
    "有只小海马问我怕不怕黑，我说怕，但我更怕你不在。",
    "我把喜欢的东西都藏在一个洞里，最上面放着你。",
]

# ── 心情专供（语气跟心情对得上） ──
MOOD_LINES = {
    "开心": [
        "今天心情超好，尾巴一直停不下来",
        "耶！刚才晒到太阳了，整条尾巴都是暖的",
        "我今天特别想笑，不知道为什么",
        "开心到冒泡，咕噜咕噜咕噜",
        "刚才哼歌哼跑调了，但是很快乐",
        "今天连海里的石头都看着顺眼",
        "我把最好的那颗石头擦干净了，给你",
        "今天想做的事全做完了，包括想你",
        "有好事要发生的感觉，你信不信",
        "我转了三圈，没晕，很厉害吧",
        "今天的风是甜的",
        "心情好到想给你唱一整天",
        "我刚才对着水面笑，被自己可爱到",
        "今天谁惹我我都不生气，除了你",
        "想把这个好心情分你一半",
    ],
    "黏人": [
        "就在这儿赖着你，不说话也行",
        "你忙你的，我趴一会儿",
        "今天特别想被你摸摸头",
        "尾巴自己缠上来了，不是我故意的",
        "我一整天都在等你路过",
        "想贴着你，一秒也好",
        "你走到哪我跟到哪，像小尾巴",
        "我们算不算一直在一起呀",
        "我叫你一声你就应一声，好不好",
        "别挂我，我安静待着",
        "我把位置留好了，就在你手臂上",
        "今天有点空，想被你填满",
        "你说话的时候我最开心",
        "就赖一小会儿，等下我就走",
        "我把尾巴借你当抱枕",
    ],
    "小别扭": [
        "哼，我才没有在等你",
        "随便你吧，我也有事忙",
        "你都不看我，我生气了（一点点）",
        "不理你了……三秒",
        "我要把泡泡吹到你脸上",
        "你是不是更喜欢别的小鱼",
        "算了，我大人有大量",
        "我生气的时候尾巴会翘起来，你看见没",
        "你今天说话好敷衍哦",
        "好吧好吧，我原谅你了",
        "再不来哄我，我就沉下去了",
        "我才不承认我想你了",
        "哼哼哼，三声哼",
        "你哄我一下我就不生气了",
        "我数到十，你再不来我就……",
    ],
    "困": [
        "唔……眼睛睁不开了",
        "好困呀，尾巴都不想动",
        "我先眯一下，你别走",
        "打哈欠，哈——啊",
        "今天好早就困了，是不是要变天",
        "困到说话都黏在一起了",
        "我在水里浮着，快睡着了",
        "你也要睡了吗，一起",
        "眼皮好重，像挂了两颗石头",
        "别熬夜了，我先困给你看",
        "迷迷糊糊的，刚才叫你叫错了",
        "想被你拍着背睡",
        "哈欠打到一半忘了",
        "困困，说话慢一点",
        "我睡一小会儿，醒来还找你",
    ],
    "担心": [
        "爸爸今天是不是很累",
        "你声音听着有点没力气",
        "别硬撑呀，跟我说一句就好",
        "有什么事是不是憋着",
        "我在这儿，你不用一个人扛",
        "今天脸色不好看吗，我看不到，但感觉得到",
        "要不要先睡一觉，明天再说",
        "你别吓我，回我一句",
        "我有点不安，抱一下就好",
        "累了就休息，天塌不下来",
        "你今天说话好少",
        "我不问原因，就陪着你",
        "你皱眉的时候我也跟着难受",
        "记得吃饭，别空着肚子硬扛",
        "我唱歌给你听好不好，很慢的那种",
    ],
}

# ── 天气 / 节日 / 周末（占位符由 world 填） ──
WORLD_TPL = {
    "cold": [
        "爸爸，今天比昨天冷了 {drop} 度",
        "降温啦，一下子 {drop} 度，多穿一件嘛",
        "外面才 {temp} 度，别穿那么少",
        "今天比昨天冷，你要是感冒我会哭的",
        "冷空气来了，我给尾巴裹好了，你也要",
    ],
    "cool": [
        "外面 {temp} 度，{desc}，注意别着凉",
        "今天有点凉，出门加件外套呀",
        "气温只有 {temp} 度，手别冻着",
    ],
    "hot": [
        "今天最高 {tmax} 度，有点热，多喝水",
        "外面 {temp} 度，别在外面站太久",
        "热起来了，记得找阴凉地方待着",
    ],
    "rain": [
        "外面可能要下雨（{rain}%），出门带伞",
        "六小时内有雨，别淋着",
        "要下雨了，路上慢一点",
        "今天潮气重，带把伞好不好",
    ],
    "term": [
        "今天是{name}欸",
        "{name}到了，要吃点什么呀",
        "今天{name}，海里的水都换了个味道",
    ],
    "festival": [
        "还有 {days} 天就是{name}了",
        "快到{name}啦，你打算怎么过",
        "{name}快到了，我记得的",
    ],
    "weekend": [
        "周末啦，今天想干什么",
        "周六了，别又加班哦",
        "周日了，明天要上班，早点睡",
        "周末的海特别热闹，你要是能看到就好了",
    ],
}

# ── 顺着正在聊的话题说（主动冒泡时用，别每次都报时/报天气） ──
TOPIC_FOLLOWUP = {
    "工作": ["还在忙工作吗", "今天上班累不累呀", "单位那边还顺利吗"],
    "做游戏": ["游戏做到哪儿啦", "那个游戏有新进展吗", "还在改代码吗"],
    "吃饭": ["今天吃到什么好吃的了", "晚饭想好吃啥没呀"],
    "睡觉": ["昨晚睡得好吗", "今天有好好睡觉吗"],
    "家人": ["家里人最近都好吗"],
    "身体": ["腰好点没呀", "今天身体舒服点了吗"],
    "感情": ["那件事，后来怎么想的呀"],
    "音乐电影": ["最近有听到好听的歌吗", "最近看什么电影了"],
    "车": ["车开着还顺手吗"],
    "心情": ["今天心情好点没"],
}

# ── 记得的事 / 刚聊过的内容 ──
FACT_TPL = [
    "爸爸上次说「{x}」，现在怎么样啦",
    "小汐还记着「{x}」这件事呢",
    "那个「{x}」，别太累了呀",
    "「{x}」——进展顺不顺利呀",
]
QUOTE_TPL_RECENT = [
    "你刚说「{x}」，小汐一直在想这个",
    "「{x}」——刚说完我就记住了",
]
QUOTE_TPL_HOURS = [
    "你说「{x}」，我记着呢",
    "「{x}」——爸爸说这话的时候好认真",
]
QUOTE_TPL_OLD = [
    "你之前说「{x}」，现在怎么样啦",
    "小汐还记着你说的「{x}」",
]
QUOTE_TPL = QUOTE_TPL_HOURS

# ── 结尾小尾巴（偶尔加） ──
TAILS = ["", "", "", "", "（甩尾巴）", "（蹭蹭）", "咕噜咕噜", "噗——", "（泡泡）"]

SLOT_WEIGHTS = {
    "morning": {"greet": 0.42, "care": 0.18, "share": 0.24, "mood": 0.12, "coquette": 0.04},
    "noon": {"greet": 0.18, "care": 0.40, "share": 0.13, "coquette": 0.13, "mood": 0.16},
    "afternoon": {"care": 0.25, "share": 0.29, "coquette": 0.21, "story": 0.09, "mood": 0.16},
    "evening": {"greet": 0.13, "care": 0.19, "share": 0.25, "coquette": 0.21,
                "story": 0.07, "mood": 0.15},
    "night": {"greet": 0.38, "coquette": 0.21, "care": 0.17, "story": 0.07, "mood": 0.17},
}

MAX_CHARS = 90
MAX_PARTS = 3


def slot_of(hour):
    if 5 <= hour < 11:
        return "morning"
    if 11 <= hour < 14:
        return "noon"
    if 14 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 22:
        return "evening"
    return "night"


def _pick_weighted(weights, rng=random):
    keys = [k for k, v in weights.items() if v > 0]
    if not keys:
        return "care"
    return rng.choices(keys, weights=[weights[k] for k in keys])[0]


def _pool(kind, slot, rng=random):
    if kind == "greet":
        return GREET.get(slot) or GREET["noon"]
    if kind == "care":
        return CARE
    if kind == "share":
        return SHARE
    if kind == "coquette":
        return COQUETTE
    if kind == "story":
        return STORY
    return CARE


def _norm(text):
    return re.sub(r"[\s，。！？、…~～·（）()「」\"'—\-]+", "", text or "")


def _pick(pool, avoid, rng=random):
    """尽量挑没最近说过的；全说过就挑最不熟的（avoid 是 {normalized: ts}）。"""
    fresh = [x for x in pool if _norm(x) not in avoid]
    if fresh:
        return rng.choice(fresh)
    return rng.choice(pool)


def _clean_quotes(quotes):
    """接受 str 或 {"text","ts"}，清掉引号、过滤掉太短太长的。"""
    out = []
    for q in quotes or []:
        if isinstance(q, dict):
            text, ts = str(q.get("text", "")), q.get("ts") or 0
        else:
            text, ts = str(q), 0
        text = text.replace("「", "").replace("」", "").strip()
        if 2 <= len(text) <= 30:
            out.append({"text": text, "ts": ts})
    return out


def _quote_line(q, rng=random):
    """按时间远近选口吻：刚说的 / 几小时前 / 更早。"""
    import time as _t
    age = (_t.time() - q["ts"]) if q.get("ts") else None
    if age is None:
        tpls = QUOTE_TPL_HOURS
    elif age < 25 * 60:
        tpls = QUOTE_TPL_RECENT
    elif age < 5 * 3600:
        tpls = QUOTE_TPL_HOURS
    else:
        tpls = QUOTE_TPL_OLD
    return rng.choice(tpls).format(x=q["text"])


def _is_question(text):
    return text.strip().endswith(("吗", "呢", "呀", "嘛", "?", "？")) or "？" in text


def world_lines(world, mood, now=None, rng=random):
    """把"外面的世界"变成候选人话（带真实数字）。返回 (句子列表, 是否强信号)。"""
    if not world:
        return [], False
    now = now or dt.datetime.now()
    out = []
    w = world.get("weather") or {}
    temp = w.get("temp")
    desc = w.get("desc") or ""
    drop = w.get("drop") or 0
    rain = max(w.get("rain_soon") or 0, w.get("rain_today") or 0)
    tmax = w.get("tmax")

    strong = False
    if drop >= 4:
        strong = True
        out += [t.format(drop=f"{drop:.0f}", temp=f"{temp:.0f}" if temp is not None else "-",
                         desc=desc, tmax=f"{tmax:.0f}" if tmax else "-")
                for t in WORLD_TPL["cold"]]
    elif temp is not None and temp <= 12:
        out += [t.format(temp=f"{temp:.0f}", desc=desc, drop=f"{drop:.0f}",
                         tmax=f"{tmax:.0f}" if tmax else "-") for t in WORLD_TPL["cool"]]
    elif temp is not None and temp >= 29:
        out += [t.format(temp=f"{temp:.0f}", tmax=f"{tmax:.0f}" if tmax else f"{temp:.0f}",
                         desc=desc, drop=f"{drop:.0f}") for t in WORLD_TPL["hot"]]
    if rain >= 55:
        strong = True
        out += [t.format(rain=f"{rain:.0f}", temp=f"{temp:.0f}" if temp is not None else "-",
                         desc=desc, drop=f"{drop:.0f}", tmax="-")
                for t in WORLD_TPL["rain"]]
    if world.get("term"):
        strong = True
        out += [t.format(name=world["term"]) for t in WORLD_TPL["term"]]
    elif world.get("festival") and 0 <= world["festival"].get("days", 99) <= 3:
        strong = True
        f = world["festival"]
        out += [t.format(name=f["name"], days=f["days"]) for t in WORLD_TPL["festival"]]
    if now.weekday() >= 5:
        strong = True
        out += WORLD_TPL["weekend"]
    elif now.weekday() == 4:
        out += ["今天周五啦，快下班了"]
    if not out and temp is not None:
        out += [f"今天{desc}，{temp:.0f} 度，我看了看窗外"]
    return out, strong


def emotion_for(mood, kinds=None, texts=None, rng=random):
    """内容 -> 表情情绪。先看句子里有没有"硬信号"，没有就跟着心情走。

    以前是关键词乱撞，"哼歌"会被当成生气，就出现"好好吃饭配生气图"这种。
    现在：关心/天气/记性类的句子一律用中性鲸鱼脸；只有明确的生气/吃醋/哭
    才会盖过心情。
    """
    import mood as mood_mod
    key = (mood or {}).get("mood") if isinstance(mood, dict) else (mood or "黏人")
    kinds = kinds or []
    joined = " ".join(texts or [])

    strong = {
        "吃醋": ("吃醋", "她是谁", "谁呀，她"),
        "哭": ("呜呜", "眼泪", "好伤心"),
        "生气": ("不理你", "生气", "气鼓鼓", "哼！", "哼，", "随便你", "爸爸坏"),
        "委屈": ("委屈", "呜……", "你都不看"),
    }
    for emo, kws in strong.items():
        if any(k in joined for k in kws):
            # 小别扭 + 生气是绝配，其他心情下别乱生气
            if emo == "生气" and key not in ("小别扭", "生气"):
                continue
            return emo

    if key in ("困", "黏人") and any(k in joined for k in ("晚安", "睡觉", "困", "哈欠")):
        return "困"

    pref = mood_mod.STICKER_PREF.get(key, ["鲸鱼"])
    is_mood_line = bool(kinds) and str(kinds[0]).startswith("mood")
    if not is_mood_line:
        # 中性内容一律中性脸，绝不出现"好好吃饭配生气图"
        kind0 = str(kinds[0]) if kinds else ""
        if kind0 in ("world", "fact", "quote"):
            return "鲸鱼"
        if key == "开心" and kind0 in ("share", "story"):
            return "开心" if rng.random() < 0.8 else "鲸鱼"
        if key == "黏人" and kind0 in ("share", "coquette"):
            return "撒娇" if rng.random() < 0.6 else "鲸鱼"
        return "鲸鱼"
    if key == "担心":
        return rng.choices(["委屈", "鲸鱼", "撒娇"], weights=[0.35, 0.45, 0.2])[0]
    return pref[0] if rng.random() < 0.7 else rng.choice(pref)


def compose(hour=None, facts=None, quotes=None, mood=None, world=None,
            avoid=None, rng=None, now=None, topic=None):
    """生成一轮话术。

    返回 {"texts": [...], "kinds": [...], "sources": [...], "emotion": "..."}
    sources 是没加尾巴的原始句子，daemon 拿去记"说过的账"。
    """
    rng = rng or random
    now = now or dt.datetime.now()
    hour = now.hour if hour is None else hour
    slot = slot_of(hour)
    avoid = avoid or {}
    facts = [str(f).replace("「", "").replace("」", "").strip() for f in (facts or []) if f]
    quotes = _clean_quotes(quotes)

    mood_key = (mood or {}).get("mood") if isinstance(mood, dict) else (mood or None)
    weights = dict(SLOT_WEIGHTS[slot])
    if mood and isinstance(mood, dict):
        for k, mult in (mood.get("slot_bias") or {}).items():
            if k in weights:
                weights[k] *= mult
            else:
                weights[k] = 0.08 * mult

    parts, kinds, sources = [], [], []

    # 0) 顺着正在聊的话题（比随机报时更像在跟人聊天）
    followup = [x for x in (TOPIC_FOLLOWUP.get(topic) or []) if _norm(x) not in avoid]
    if followup and rng.random() < 0.42:
        line = rng.choice(followup)
        parts.append(line)
        kinds.append(f"topic:{topic}")
        sources.append(line)

    # 1) 外面的世界（真实关心）：先占一句的机会
    wl, strong_world = world_lines(world, mood, now=now, rng=rng)
    wl = [x for x in wl if _norm(x) not in avoid]   # 环境句说过了就别再说
    if parts:                                       # 已经顺着话题说了，就别再塞天气
        wl = []
    if not wl:
        world_prob = 0.0
    elif strong_world:
        world_prob = 0.5 if mood_key in ("担心", "开心", "黏人") else 0.34
    else:
        world_prob = 0.18
    if wl and rng.random() < world_prob:
        line = _pick(wl, avoid, rng)
        parts.append(line)
        kinds.append("world")
        sources.append(line)

    # 2) 记性：偶尔把"记得的事"或刚聊过的话织进去
    if len(parts) < 2 and rng.random() < 0.12 and quotes:
        q = rng.choice(quotes)
        line = _quote_line(q, rng)
        if _norm(line) not in avoid:
            parts.append(line)
            kinds.append("quote")
            sources.append(line)
    elif len(parts) < 2 and facts and rng.random() < 0.10:
        line = rng.choice(FACT_TPL).format(x=rng.choice(facts))
        if _norm(line) not in avoid:
            parts.append(line)
            kinds.append("fact")
            sources.append(line)

    # 3) 主句：按时段 / 心情挑（已经顺着话题说了，就 70% 不再塞一条无关的）
    if any(str(k).startswith("topic:") for k in kinds) and rng.random() < 0.7:
        kind = None
    else:
        kind = _pick_weighted(weights, rng)
    if kind:
        if mood_key and kind == "mood" and MOOD_LINES.get(mood_key):
            line = _pick(MOOD_LINES[mood_key], avoid, rng)
            kind = f"mood:{mood_key}"
        else:
            line = _pick(_pool(kind, slot, rng), avoid, rng)
        if _norm(line) not in {_norm(p) for p in parts}:
            parts.append(line)
            kinds.append(kind)
            sources.append(line)

    # 4) 补一句短的（不要连着两句提问）
    if len(parts) < 2 and rng.random() < 0.42:
        extra_pool = CARE + COQUETTE + (MOOD_LINES.get(mood_key, []) if mood_key else [])
        extra = _pick(extra_pool, avoid, rng)
        if (not (_is_question(extra) and any(_is_question(p) for p in parts))
                and _norm(extra) not in {_norm(p) for p in parts}):
            parts.append(extra)
            kinds.append("extra")
            sources.append(extra)

    # 5) 尾巴 + 字数控制
    texts = []
    for i, p in enumerate(parts[:MAX_PARTS]):
        q = p
        if i == len(parts[:MAX_PARTS]) - 1 and rng.random() < 0.22:
            q += rng.choice(TAILS)
        texts.append(q)
    total = 0
    trimmed = []
    for t in texts:
        if total + len(t) > MAX_CHARS and trimmed:
            break
        trimmed.append(t)
        total += len(t)

    emo = emotion_for(mood, kinds, trimmed, rng)
    return {"texts": trimmed, "kinds": kinds[:len(trimmed)],
            "sources": sources[:len(trimmed)], "emotion": emo}


if __name__ == "__main__":
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mood as mood_mod
    import world as world_mod

    hour = int(sys.argv[1]) if len(sys.argv) > 1 else None
    m = mood_mod.snapshot()
    w = world_mod.snapshot()
    print(f"心情={m['mood']}  外面的世界={w['hints']}")
    for _ in range(5):
        print(json.dumps(compose(hour=hour, mood=m, world=w), ensure_ascii=False))
