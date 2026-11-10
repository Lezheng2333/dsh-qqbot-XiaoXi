#!/usr/bin/env python3
"""小汐的日记 — 每天给每个聊过的人写一页，跨天的记忆就靠它。

不是让模型写（那要多一次 LLM），而是从聊天记录里抽：
当天聊到的话题、他说的几句原话、她回的几句、当天的消息数。
recall.py 会把它念成一句"昨天你们聊了……"，她自己就知道昨天发生过什么。

  python3 journal.py            # 看最近几天
  python3 journal.py --build    # 立刻补写今天和昨天
"""
import datetime as dt
import os
import re
import sys
import time

import paths
import topic as topic_mod
import transcripts

KEEP_DAYS = 60


def journal_dir(uid):
    return os.path.join(paths.USERS_DIR, uid, "journal")


def day_path(uid, date):
    return os.path.join(journal_dir(uid), f"{date}.json")


def _clean(text):
    text = re.sub(r"【[^】]*】", "", text or "")
    text = re.sub(r"- (Image|File): \S+", "", text)
    text = re.sub(r"\[图片\]|\[文件\]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _date_of(ts):
    return dt.datetime.fromtimestamp(ts).date().isoformat()


META_MARKS = ("看起来你的消息", "报错", "```", "traceback", "我先看", "让我看",
              "工具", "权限", "命令执行", "读取失败")


def _her_line_ok(text):
    t = _clean(text)
    if not (4 <= len(t) <= 60):
        return False
    if any(k in t for k in META_MARKS):
        return False
    if t.startswith(("http", "/Users/", "$")):
        return False
    return True


def _uniq(items, n):
    out = []
    for x in items:
        x = _clean(x)[:34]
        if not x or x in out:
            continue
        out.append(x)
        if len(out) >= n:
            break
    return out


def build(uid, date=None, mood=None):
    """抽一天的：话题、他的原话、她说的话、消息数。"""
    date = date or dt.date.today().isoformat()
    users = [m for m in transcripts.user_messages(uid=uid) if _date_of(m["ts"]) == date]
    hers = [m for m in transcripts.assistant_messages(uid=uid) if _date_of(m["ts"]) == date]
    if not users and not hers:
        return None

    # 当天的话题：把词表打分限制在这一天
    scores = topic_mod.score_topics(uid, limit=200, half_life_min=600,
                                    since=_day_start(date), until=_day_end(date))
    topics = [k for k, v in scores.items() if v > 0][:3]

    personal = [m["text"] for m in users if transcripts.looks_personal(m["text"])]
    quotes = _uniq(personal or [m["text"] for m in users], 4)
    # 她的话取"最后几句"更代表当天，并且滤掉工具/报错/半截消息那种
    good = [m["text"] for m in reversed(hers) if _her_line_ok(m["text"])]
    lines = list(reversed(_uniq(good, 3)))

    return {
        "date": date,
        "users": len(users),
        "hers": len(hers),
        "topics": topics,
        "his_words": quotes,
        "her_lines": lines,
        "mood": (mood or {}).get("mood") if isinstance(mood, dict) else mood,
        "first_at": users[0]["ts"] if users else None,
        "last_at": users[-1]["ts"] if users else None,
        "built_at": time.time(),
    }


def _day_start(date):
    d = dt.datetime.fromisoformat(date)
    return d.timestamp()


def _day_end(date):
    d = dt.datetime.fromisoformat(date) + dt.timedelta(days=1)
    return d.timestamp()


def write(uid, date=None, mood=None):
    date = date or dt.date.today().isoformat()
    day = build(uid, date, mood)
    if not day:
        return None
    paths.save_json(day_path(uid, date), day)
    _prune(uid)
    return day


def _prune(uid):
    d = journal_dir(uid)
    if not os.path.isdir(d):
        return
    files = sorted(f for f in os.listdir(d) if f.endswith(".json"))
    for f in files[:-KEEP_DAYS]:
        try:
            os.remove(os.path.join(d, f))
        except OSError:
            pass


def ensure(uid, mood=None):
    """补写今天（30 分钟内更新过就跳过）和昨天。"""
    today = dt.date.today()
    p = day_path(uid, today.isoformat())
    fresh = os.path.exists(p) and (time.time() - os.path.getmtime(p)) < 1800
    if not fresh:
        write(uid, today.isoformat(), mood)
    y = (today - dt.timedelta(days=1)).isoformat()
    if not os.path.exists(day_path(uid, y)):
        write(uid, y, mood)


def recent(uid, n=3):
    d = journal_dir(uid)
    if not os.path.isdir(d):
        return []
    files = sorted((f for f in os.listdir(d) if f.endswith(".json")), reverse=True)
    out = []
    for f in files[:n]:
        day = paths.load_json(os.path.join(d, f), None)
        if day:
            out.append(day)
    return out


def _rel(date, today=None):
    today = today or dt.date.today()
    delta = (today - dt.date.fromisoformat(date)).days
    return {0: "今天", 1: "昨天", 2: "前天"}.get(delta, f"{delta} 天前")


def lines(uid, n=2, today=None):
    """给 recall 用的两行：昨天/前天你们聊了什么。"""
    out = []
    for day in recent(uid, n + 1):
        if day["date"] == (today or dt.date.today()).isoformat():
            continue
        bits = []
        if day.get("topics"):
            bits.append("聊到 " + "/".join(day["topics"]))
        if day.get("his_words"):
            bits.append("他说「" + "」「".join(day["his_words"][:2]) + "」")
        if day.get("her_lines"):
            bits.append("你回的是「" + day["her_lines"][0] + "」")
        if bits:
            out.append(f"{_rel(day['date'], today)}（{day['date']}）：" + "；".join(bits))
        if len(out) >= n:
            break
    return out


if __name__ == "__main__":
    import people
    uid = people.current()
    if "--build" in sys.argv:
        print("今天:", bool(write(uid)))
        y = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        print("昨天:", bool(write(uid, y)))
    for ln in lines(uid, 3):
        print("·", ln)
    print("--- 原始 ---")
    for day in recent(uid, 3):
        print(day["date"], day["topics"], day["users"], "条")
