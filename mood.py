#!/usr/bin/env python3
"""小汐的心情 — 跨消息保持的情绪状态机，按人分开。

她对爸爸可以是黏人，对刚认识的陌生人就得收敛；所以心情是"对某个人的心情"。
状态存在 users/<uid>/mood.json，有惯性、会自己淡下去。

心情影响三件事：说什么（话术权重）、发什么表情（情绪标签）、怎么说（voice/rate/pitch）。

  python3 mood.py                    # 看对当前这个人的心情
  python3 mood.py force 开心
  python3 mood.py list               # 所有人各什么心情
"""
import datetime as dt
import json
import os
import random
import sys
import time

import paths
import store

MOODS = ("开心", "黏人", "小别扭", "困", "担心")
HISTORY_MAX = 40

SLOT_BIAS = {
    "开心": {"share": 2.2, "story": 1.7, "care": 1.0, "coquette": 1.0, "greet": 1.1, "mood": 1.6},
    "黏人": {"coquette": 2.6, "share": 1.1, "care": 1.1, "greet": 0.7, "story": 0.5, "mood": 1.8},
    "小别扭": {"coquette": 2.4, "care": 0.9, "story": 0.4, "share": 0.35, "greet": 0.4, "mood": 2.2},
    "困": {"coquette": 1.5, "care": 1.3, "greet": 1.0, "story": 0.45, "share": 0.35, "mood": 2.0},
    "担心": {"care": 3.2, "coquette": 1.1, "greet": 0.7, "share": 0.25, "story": 0.2, "mood": 1.2},
}
# 对"还没熟的人"更收敛：撒娇压到最低，关心不能少
STRANGER_SLOT_BIAS = {"coquette": 0.18, "mood": 0.55, "greet": 1.0,
                      "care": 1.25, "share": 1.0, "story": 1.0}

STICKER_PREF = {
    "开心": ["开心", "夸", "鲸鱼"],
    "黏人": ["撒娇", "鲸鱼", "开心"],
    "小别扭": ["生气", "吃醋", "委屈"],
    "困": ["困", "鲸鱼", "撒娇"],
    "担心": ["委屈", "鲸鱼", "撒娇"],
}

VOICE = {
    "开心": ("zh-CN-XiaoyiNeural", "+10%", "+14Hz"),
    "黏人": ("zh-CN-XiaoxiaoNeural", "-2%", "+12Hz"),
    "小别扭": ("zh-CN-XiaoyiNeural", "+2%", "-6Hz"),
    "困": ("zh-CN-XiaoxiaoNeural", "-14%", "-8Hz"),
    "担心": ("zh-CN-XiaoxiaoNeural", "-6%", "+2Hz"),
}

TONE = {
    "开心": "心情很好，语尾往上飘，会哼歌、甩尾巴、说「耶」",
    "黏人": "想贴着这个人，句子更短更软，句尾爱带「嘛」「好不好」",
    "小别扭": "有点小生气但没真生气，会用「哼」「才不」「随便你」，两句话就软",
    "困": "困了，句子慢、懒，会打哈欠、说错字再改口",
    "担心": "在担心这个人，先问一句，别说教，别长篇",
}

POS = ("哈哈", "开心", "好耶", "喜欢", "棒", "太好了", "嘿嘿", "谢谢", "爱你",
       "抱抱", "乖", "么么", "可爱")
NEG = ("累", "烦", "难过", "加班", "难受", "困死", "焦虑", "压力", "生气",
       "哭", "心情不好", "疼", "崩", "顶不住", "熬夜", "通宵")


def mood_path(uid):
    return os.path.join(paths.USERS_DIR, uid, "mood.json")


def _default():
    hour = dt.datetime.now().hour
    mood = "困" if (hour >= 22 or hour < 2) else ("开心" if 6 <= hour < 10 else "黏人")
    return {"mood": mood, "intensity": 0.5, "since": time.time(),
            "updated": time.time(), "history": [], "counters": {"ignored": 0, "good": 0}}


def load(uid):
    st = paths.load_json(mood_path(uid), None)
    if not isinstance(st, dict) or st.get("mood") not in MOODS:
        st = _default()
    st.setdefault("history", [])
    st.setdefault("counters", {"ignored": 0, "good": 0})
    st.setdefault("intensity", 0.5)
    return st


def save(st, uid):
    st["history"] = st.get("history", [])[-HISTORY_MAX:]
    paths.save_json(mood_path(uid), st)


def _set(st, mood, why, intensity=None):
    changed = st.get("mood") != mood
    if changed:
        st["history"].append({"ts": round(time.time()), "from": st.get("mood"),
                              "to": mood, "why": why})
        st["since"] = time.time()
    st["mood"] = mood
    if intensity is not None:
        st["intensity"] = round(max(0.2, min(1.0, intensity)), 2)
    elif changed:
        st["intensity"] = 0.55
    st["updated"] = time.time()
    return st


def _sentiment(texts):
    joined = " ".join(texts)
    return (sum(joined.count(k) for k in POS), sum(joined.count(k) for k in NEG))


def tick(uid, now=None, reply_rate=0.5, ignored_streak=0, last_user_ts=0.0,
         recent_texts=None, familiar=True, rand=None):
    """按外部信号漂一下心情，落盘并返回快照。familiar=False（陌生人）更收敛。"""
    rng = rand or random
    now = now or dt.datetime.now()
    hour = now.hour
    st = load(uid)
    prev = st["mood"]
    since_min = (time.time() - st.get("since", 0)) / 60
    silent_hours = ((time.time() - last_user_ts) / 3600) if last_user_ts else 0.0
    pos, neg = _sentiment((recent_texts or [])[-3:])

    decay = min(0.25, (time.time() - st.get("updated", time.time())) / 3600 * 0.08)
    st["intensity"] = round(max(0.2, st.get("intensity", 0.5) - decay), 2)

    pick, why = None, ""
    if ignored_streak >= 2 and silent_hours >= 3:
        pick, why = ("小别扭" if rng.random() < 0.55 else
                     "担心" if rng.random() < 0.6 else "黏人"), \
            f"连着 {ignored_streak} 次没被回，这个人 {silent_hours:.1f} 小时没说话"
    elif silent_hours >= 7 and reply_rate >= 0.35:
        pick, why = ("担心" if rng.random() < 0.6 else "黏人"), f"{silent_hours:.1f} 小时没说话了"
    elif neg > 0 and neg >= pos:
        pick, why = ("担心" if rng.random() < 0.75 else "黏人"), "最近的消息听着有点累/不开心"
    elif pos > 0 and pos > neg:
        pick, why = ("开心" if rng.random() < 0.55 else "黏人"), "刚才聊得挺开心"
    elif hour >= 22 or hour < 2:
        pick, why = ("困" if rng.random() < 0.8 else "黏人"), "这个点了，困"
    elif 6 <= hour < 10 and silent_hours < 10:
        pick, why = ("开心" if rng.random() < 0.6 else "黏人"), "早上的海很亮"
    else:
        if since_min >= 150 and rng.random() < 0.18:
            pick = rng.choice(["黏人", "开心", "困"])
            why = f"{prev} 待了 {since_min / 60:.1f} 小时，自己漂了一下"

    # 对不认识的人：不撒娇、不闹别扭
    if pick and not familiar and pick in ("黏人", "小别扭"):
        pick, why = "开心", why + "（不熟，收着点）"

    if pick:
        st = _set(st, pick, why)
        if pick != prev:
            store.log(f"对 {uid[:6]}… 的心情: {prev} → {pick}（{why}，强度 {st['intensity']}）")
    else:
        st["updated"] = time.time()

    save(st, uid)
    return snapshot(uid, st)


def snapshot(uid, st=None):
    st = st or load(uid)
    mood = st["mood"]
    voice, rate, pitch = VOICE.get(mood, VOICE["黏人"])
    return {
        "uid": uid,
        "mood": mood,
        "intensity": st.get("intensity", 0.5),
        "since": st.get("since"),
        "since_min": round((time.time() - st.get("since", time.time())) / 60),
        "tone": TONE.get(mood, ""),
        "slot_bias": SLOT_BIAS.get(mood, {}),
        "sticker_pref": STICKER_PREF.get(mood, ["鲸鱼"]),
        "voice": {"voice": voice, "rate": rate, "pitch": pitch},
        "counters": st.get("counters", {}),
    }


def bias_for(uid, snap=None, familiar=True):
    """把这个人的熟悉程度乘进话术权重。"""
    snap = snap or snapshot(uid)
    bias = dict(snap.get("slot_bias") or {})
    if not familiar:
        for k, mult in STRANGER_SLOT_BIAS.items():
            if k in bias:
                bias[k] *= mult
        bias.setdefault("coquette", 0.15)
    return bias


def force(uid, mood):
    if mood not in MOODS:
        raise SystemExit(f"心情只能是 {'/'.join(MOODS)}")
    st = _set(load(uid), mood, "手动拨了一下", intensity=0.8)
    save(st, uid)
    return snapshot(uid, st)


if __name__ == "__main__":
    import people
    args = sys.argv[1:]
    if args and args[0] == "list":
        rows = {u: (people.get(u) or {}).get("name") for u in people.profiles()}
        print(json.dumps({n or u: load(u)["mood"] for u, n in rows.items()},
                         ensure_ascii=False, indent=1))
    elif args and args[0] == "force" and len(args) > 1:
        print(json.dumps(force(people.current(), args[1]), ensure_ascii=False, indent=1))
    else:
        s = snapshot(people.current())
        print(json.dumps({k: s[k] for k in ("mood", "intensity", "since_min", "tone")},
                         ensure_ascii=False, indent=1))
