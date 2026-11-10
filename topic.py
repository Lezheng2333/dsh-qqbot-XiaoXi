#!/usr/bin/env python3
"""小汐的话题延续 — 她现在在跟这个人聊什么，别一句一换。

两条信号：
1. 话题标签：用一张"生活话题词表"去匹配最近十几条消息，命中最多的那个就是话题
   （纯字频会选出"左亲亲"这种噪声，所以用词表不用统计）。
2. 话题锚点：他最后一句"有内容"的话（去掉表情/单字/寒暄），原样留着。
   她说"你刚说…"的时候，最好引的就是这一句。

状态存在 users/<uid>/topic.json，守护进程每轮更新，聊天时 recall.py 读。

  python3 topic.py            # 看当前话题
  python3 topic.py --update   # 立刻重算
"""
import datetime as dt
import os
import re
import sys
import time

import paths
import transcripts

# 生活话题词表（命中越多、越近，越可能是当前话题）
LEXICON = {
    "工作": ["上班", "加班", "干活", "单位", "公司", "油库", "应急局", "值班", "开会",
             "项目", "评审", "材料", "汇报", "领导", "同事", "下班", "借调"],
    "做游戏": ["游戏", "github", "GitHub", "开发", "代码", "关卡", "版本", "像素",
               "Unity", "Godot", "引擎", "美术"],
    "吃饭": ["吃", "饭", "火锅", "串串", "外卖", "饿", "宵夜", "早点", "午饭", "晚饭",
             "奶茶", "咖啡", "喝酒"],
    "睡觉": ["睡", "困", "熬夜", "晚安", "早起", "失眠", "起床", "午觉"],
    "天气": ["冷", "热", "下雨", "天气", "降温", "太阳", "风", "雪", "穿"],
    "家人": ["妹妹", "弟弟", "妈", "爸", "家里", "亲戚", "孩子", "老婆", "对象", "爷爷", "奶奶"],
    "感情": ["暗恋", "喜欢", "谈恋爱", "分手", "照片", "同学", "心动", "表白"],
    "身体": ["累", "腰", "眼睛", "头疼", "感冒", "生病", "医院", "吃药", "体检", "疼"],
    "音乐电影": ["歌", "电影", "摇滚", "配乐", "乐队", "演唱会", "剧"],
    "车": ["开车", "车", "腾势", "油门", "停车", "堵车"],
    "心情": ["烦", "难过", "压力", "开心", "郁闷", "焦虑", "崩", "委屈"],
}

# 这些句子不算"话题锚点"：表情、寒暄、单字
CHITCHAT = {"你好", "在吗", "嗨", "嗨嗨", "嗯", "哦", "好", "哈哈", "在", "晚安",
            "早上好", "晚上好", "中午好", "好的", "行", "哈哈哈哈哈"}


def topic_path(uid):
    return os.path.join(paths.USERS_DIR, uid, "topic.json")


def _clean(text):
    text = re.sub(r"【[^】]*】", "", text or "")          # 【表情: 左亲亲】
    text = re.sub(r"- (Image|File): \S+", "", text)      # 附件
    text = re.sub(r"\[图片\]|\[文件\]", "", text)
    return text.strip()


def is_anchor(text):
    t = _clean(text)
    if len(t) < 3 or t in CHITCHAT:
        return False
    if re.fullmatch(r"[\W_]+", t):
        return False
    return True


def anchor_of(uid):
    """他最后一句有内容的话。"""
    for m in reversed(transcripts.user_messages(uid=uid)):
        if is_anchor(m["text"]):
            return {"text": _clean(m["text"])[:40], "ts": m["ts"]}
    return None


def score_topics(uid, limit=14, half_life_min=90, since=None, until=None):
    """按"命中次数 × 时间衰减"给话题打分（可限定时间窗，日记用）。"""
    now = time.time()
    scores = {k: 0.0 for k in LEXICON}
    msgs = transcripts.user_messages(uid=uid)
    if since is not None or until is not None:
        msgs = [m for m in msgs
                if (since is None or m["ts"] >= since) and (until is None or m["ts"] < until)]
    for m in msgs[-limit:]:
        text = _clean(m["text"])
        if not text:
            continue
        age_min = (now - m["ts"]) / 60
        w = 0.5 ** (age_min / half_life_min)
        for name, words in LEXICON.items():
            hits = sum(text.count(w) for w in words)
            if hits:
                scores[name] += w * min(hits, 3)
    return {k: round(v, 2) for k, v in sorted(scores.items(), key=lambda kv: -kv[1]) if v > 0}


def update(uid, now=None):
    """重算当前话题；同一话题会累加 turns，换了就进历史。"""
    now = now or time.time()
    st = paths.load_json(topic_path(uid), None) or {}
    st.setdefault("history", [])
    scores = score_topics(uid)
    top = next(iter(scores), None)
    anchor = anchor_of(uid)

    msgs = transcripts.user_messages(uid=uid)
    latest_msg_ts = msgs[-1]["ts"] if msgs else 0
    last_seen = st.get("last_msg_ts") or 0
    new_msgs = len([m for m in msgs if m["ts"] > last_seen]) if last_seen else 0

    cur = st.get("topic")
    same = (top == cur)
    if same and top:
        # turns 只跟"新消息"涨，不跟 tick 涨
        st["turns"] = int(st.get("turns", 1)) + max(0, new_msgs)
        st["last_ts"] = now
    elif top:
        if cur:
            st["history"].append({"topic": cur, "since": st.get("since"), "till": now})
            st["history"] = st["history"][-20:]
        st = {"topic": top, "since": now, "last_ts": now, "turns": max(1, new_msgs),
              "scores": scores, "history": st.get("history", [])}
    else:
        st.setdefault("turns", 0)

    if anchor:
        st["anchor"] = anchor
    st["last_msg_ts"] = latest_msg_ts
    st["updated"] = now
    paths.save_json(topic_path(uid), st)
    return st


def current(uid):
    st = paths.load_json(topic_path(uid), None)
    if not isinstance(st, dict):
        return update(uid)
    return st


def label(uid):
    """一句话说清"在聊什么"，给聊天和主动消息用。"""
    st = current(uid)
    topic = st.get("topic")
    if not topic:
        return None
    anchor = st.get("anchor") or {}
    age_min = (time.time() - (st.get("last_ts") or 0)) / 60
    text = anchor.get("text")
    # 锚点要跟话题对得上才拿出来（"正在聊天气"配"捡到什么了"会很别扭）
    if text and not any(w in text for w in LEXICON.get(topic, [])):
        text = None
    return {"topic": topic, "anchor": text, "last_line": anchor.get("text"),
            "anchor_hours": round(age_min / 60, 1),
            "turns": st.get("turns", 0), "fresh": age_min < 6 * 60}


def hint(uid):
    """给主动消息用的短提示：只有新鲜话题才返回。"""
    lb = label(uid)
    if not lb or not lb["fresh"]:
        return None
    return lb["topic"]


if __name__ == "__main__":
    import people
    uid = people.current()
    if "--update" in sys.argv:
        update(uid)
    lb = label(uid)
    print(f"当前话题: {lb['topic'] if lb else '还没形成'}（{lb['turns'] if lb else 0} 句，"
          f"{lb['anchor_hours'] if lb else 0} 小时前）")
    if lb and lb.get("anchor"):
        print("话题锚点:", lb["anchor"])
    print("打分:", (current(uid).get("scores") or {}))
