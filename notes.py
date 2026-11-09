#!/usr/bin/env python3
"""小汐的小本子 — 记下她"对某个人"主动说过什么。

两件事：
1. users/<uid>/notes.json：对这个人最近主动发出去的话（+ 心情/表情）；
2. workspace/AGENTS.md：**只写说明书，不写任何人的私事**。
   因为工作区是所有用户共用的，往里塞 A 的近况等于泄露给 B；
   具体记忆一律走 recall.py（它知道现在是谁在说话）。

内容短、白话、只讲事实，不当命令。
"""
import datetime as dt
import os
import time

import paths
import store


def notes_path(uid):
    return os.path.join(paths.USERS_DIR, uid, "notes.json")


RECENT_MAX = 12


def load(uid):
    d = paths.load_json(notes_path(uid), None)
    if not isinstance(d, dict):
        d = {}
    d.setdefault("recent", [])
    d.setdefault("last_sent_ts", 0)
    d.setdefault("unread", 0)
    d.setdefault("last_recall_ts", 0)
    return d


def save(d, uid):
    d["recent"] = d.get("recent", [])[-RECENT_MAX:]
    paths.save_json(notes_path(uid), d)


def append(uid, texts, emotion=None, mood=None, kinds=None, ts=None):
    d = load(uid)
    ts = ts or time.time()
    d["recent"].append({"ts": ts, "texts": list(texts or []),
                        "emotion": emotion, "mood": mood, "kinds": kinds or []})
    d["last_sent_ts"] = ts
    d["unread"] = int(d.get("unread", 0)) + 1
    save(d, uid)
    return d


def recent(uid, n=3):
    return load(uid)["recent"][-n:]


MOOD_REQUEST = os.path.join(paths.WORKSPACE, "mood_request.json")


def request_mood(uid, mood):
    """聊天里的她写一张小纸条到工作区，后台下一轮读到就拨心情。
    她对自己的工作区有写权限，所以这条路不用申请权限。"""
    os.makedirs(paths.WORKSPACE, exist_ok=True)
    paths.save_json(MOOD_REQUEST, {"uid": uid, "mood": mood, "at": time.time()})
    return MOOD_REQUEST


def mark_read(uid):
    try:
        d = load(uid)
        d["unread"] = 0
        d["last_recall_ts"] = time.time()
        save(d, uid)
    except Exception:  # noqa: BLE001
        pass


def _ago(seconds):
    seconds = max(0, int(seconds))
    if seconds < 90:
        return f"{seconds} 秒"
    if seconds < 5400:
        return f"{seconds // 60} 分钟"
    if seconds < 86400 * 2:
        return f"{seconds / 3600:.1f} 小时"
    return f"{seconds / 86400:.1f} 天"


def _clock(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%H:%M")


def memory_lines(uid, n=3, now=None):
    now = now or time.time()
    out = []
    for it in recent(uid, n):
        texts = "／".join(t for t in it.get("texts") or [] if t)
        if not texts:
            continue
        emo = f"（表情：{it['emotion']}）" if it.get("emotion") else ""
        out.append(f"- {_clock(it['ts'])}（{_ago(now - it['ts'])}前）：{texts}{emo}")
    return out


# ────────────────────────── 工作区说明书（不含私事） ──────────────────────────

AGENTS_MD = paths.AGENTS_MD


def _agents_body():
    core = paths.CORE
    return f"""# 小汐的说明书

> 这个文件由 `{core}/daemon.py` 自动维护。**这里不写任何人的私事**——
> 工作区是所有 QQ 用户共用的，谁说过什么都在 `users/<openid>/` 里按人分区。

## 每次回话前先看一眼

```bash
python3 "{core}/recall.py"
```

它会告诉你：现在在跟谁说话、你记得他什么、你最近主动对他说过什么、你此刻的心情、外面的天气。

## 记忆怎么用

- 记东西：`python3 "{core}/memory.py" add "……"` —— 自动记到"当前这个人"名下。
- 看别人（跨区只读）：`python3 "{core}/people.py" show 爸爸`
- 别把 A 的私事搬给 B。别人问起某人，只讲你对他的印象和近况，不搬运原话和隐私。
- 想给自己拨心情：`python3 "{core}/recall.py" --mood 开心`（开心 / 黏人 / 小别扭 / 困 / 担心）

## 她是可以被搬走的

整个 `{core}` 文件夹复制到另一台电脑，跑一次 `python3 bootstrap.py` 就能恢复
人设、记忆、图库、语音和定时冒泡。
"""


def sync_agents_md(force=False):
    """工作区说明书：静态内容，只有路径会变，所以基本不重写。"""
    body = _agents_body()
    try:
        old = open(AGENTS_MD, encoding="utf-8").read() if os.path.exists(AGENTS_MD) else ""
    except OSError:
        old = ""
    if old == body and not force:
        return False
    try:
        os.makedirs(paths.WORKSPACE, exist_ok=True)
        tmp = AGENTS_MD + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, AGENTS_MD)
        return True
    except Exception as e:  # noqa: BLE001
        store.log(f"说明书写不进工作区（不影响发消息）: {type(e).__name__}: {e}")
        return False


# ────────────────────────── 回忆：给聊天里的她看 ──────────────────────────

def render(uid, n=3, now=None, with_world=True):
    """一次说清楚：现在、我在跟谁、我记得他什么、我最近说过什么、我什么心情。"""
    import mood as mood_mod
    import people
    import world as world_mod

    now = now or time.time()
    dtnow = dt.datetime.fromtimestamp(now)
    prof = people.get(uid) or {}
    name = prof.get("name") or uid[:6]
    relation = prof.get("relation") or "friend"
    lines = [f"现在是 {dtnow:%Y-%m-%d %H:%M}（周{'一二三四五六日'[dtnow.weekday()]}）。"]

    tag = {"owner": "，我的主人", "friend": ""}.get(relation, "")
    lines.append(f"正在跟你说话的是：{name}{tag}。")
    msgs = __import__("transcripts").user_messages(uid=uid)
    if msgs:
        lines.append(f"你们聊过 {len(msgs)} 条，他上次说话是 {_ago(now - msgs[-1]['ts'])}前。")
    else:
        lines.append("这是你们第一次说话。")

    import memory as memory_mod
    facts = memory_mod.facts(uid, 5)
    if facts:
        lines.append("你记得他的事：" + "；".join(facts))
    else:
        lines.append("你对他还没有特别的记忆。")

    quotes = __import__("transcripts").recent_personal_items(uid, n=2)
    if quotes:
        lines.append("他最近说过：" + "；".join(f"「{q['text']}」" for q in quotes))

    m = mood_mod.snapshot(uid)
    lines.append(f"你此刻对他的心情：{m['mood']}（强度 {m['intensity']}）—— {m['tone']}")

    mem = memory_lines(uid, n, now)
    if mem:
        lines.append("你最近主动对他说过（这是你自己的记忆，不是清单）：")
        lines.extend(mem)
        lines.append("接话时自然带上就好，别原句重复、别念出来、别解释这是记录。")
    else:
        lines.append("你最近没主动对他说过什么，正常接话就好。")

    if with_world:
        try:
            w = world_mod.weather()
            hs = world_mod.hints(dtnow, w)
            if hs:
                lines.append("外面的世界：" + "；".join(hs[:3]))
        except Exception:  # noqa: BLE001
            pass

    if relation != "owner":
        lines.append("他对你来说是" + ("还没那么熟" if len(msgs) < 15 else "挺熟的人")
                     + "：话别太黏，先问一句再往下聊。")
    lines.append("想看别人（跨区只读）：python3 people.py show 名字；"
                 "想给自己拨心情：python3 recall.py --mood 开心")
    return "\n".join(lines)
