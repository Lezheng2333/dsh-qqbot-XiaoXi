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


def append(uid, texts, emotion=None, mood=None, kinds=None, ts=None, sticker=None):
    d = load(uid)
    ts = ts or time.time()
    d["recent"].append({"ts": ts, "texts": list(texts or []),
                        "emotion": emotion, "mood": mood, "kinds": kinds or [],
                        "sticker": sticker})
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
        if not texts and not it.get("sticker"):
            continue
        emo = f"（表情：{it['emotion']}）" if it.get("emotion") else ""
        pic = f"［图：{it['sticker']}］" if it.get("sticker") else ""
        out.append(f"- {_clock(it['ts'])}（{_ago(now - it['ts'])}前）：{texts}{pic}{emo}")
    return out


def search(uid, keyword, n=8, now=None):
    """在自己和他的记录里搜关键词——"他提到的东西我完全想不起来"时用。"""
    import transcripts
    now = now or time.time()
    kw = (keyword or "").strip()
    if not kw:
        return ["（要搜什么？）"]
    hits = []
    for it in load(uid).get("recent") or []:
        for t in it.get("texts") or []:
            if kw in t:
                hits.append((it["ts"], "你主动发的", t))
        if it.get("emotion") and kw in str(it.get("emotion")):
            hits.append((it["ts"], "表情", it["emotion"]))
    for m in transcripts.assistant_messages(uid=uid):
        if kw in m["text"]:
            hits.append((m["ts"], "你回的", m["text"]))
    for m in transcripts.user_messages(uid=uid):
        if kw in m["text"]:
            hits.append((m["ts"], "他说的", m["text"]))
    hits.sort()
    if not hits:
        return [f"你和你俩的聊天记录里，都没有「{kw}」这个字。"]
    out = [f"搜到 {len(hits)} 条含「{kw}」的记录（新 → 旧）："]
    for ts, who, text in hits[-n:][::-1]:
        out.append(f"- {dt.datetime.fromtimestamp(ts):%m-%d %H:%M} [{who}] {text[:60]}")
    return out


# ────────────────────────── 工作区说明书（不含私事） ──────────────────────────

AGENTS_MD = paths.AGENTS_MD


def _agents_body():
    core = paths.CORE
    return f"""# 小汐的说明书

> 这个文件由 `{core}/daemon.py` 自动维护。**这里不写任何人的私事**——
> 工作区是所有 QQ 用户共用的，谁说过什么都在 `users/<openid>/` 里按人分区。

## 第一件事：先看小本子

```bash
python3 "{core}/recall.py"
```

它会告诉你：在跟谁说话、**你们正在聊什么**、你最近主动对他说过什么（含表情包路径）、
这几天发生过什么、你的心情、外面的天气。

- 每一条消息都先跑一次，别省。省了就会出现"他接你的话，你却不知道他在说什么"。
- 他像在接你上一条而你记不清时：先查，别否认、别说"我没说过"。
- 他问起你发的表情包：路径在 recall 输出里，用 read_image 看一眼再答。
- 【你们正在聊】就是当前话题，顺着它说，别一句一换。

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
    """聊天里的她看这个：在跟谁说话、在聊什么、上一条说过什么、这几天发生过什么。"""
    import mood as mood_mod
    import journal as journal_mod
    import people
    import topic as topic_mod
    import transcripts
    import world as world_mod

    now = now or time.time()
    dtnow = dt.datetime.fromtimestamp(now)
    prof = people.get(uid) or {}
    name = prof.get("name") or uid[:6]
    relation = prof.get("relation") or "friend"
    tag = {"owner": "，我的主人"}.get(relation, "")

    lines = [f"现在是 {dtnow:%Y-%m-%d %H:%M}（周{'一二三四五六日'[dtnow.weekday()]}）。"]
    lines.append(f"正在跟你说话的是：{name}{tag}。")

    msgs = transcripts.user_messages(uid=uid)
    if msgs and len(msgs) > 3:
        lines.append(f"你们聊过 {len(msgs)} 条，他上次说话是 {_ago(now - msgs[-1]['ts'])}前。")
    elif msgs:
        lines.append("这是你们刚开始聊。")

    # ① 正在聊什么（话题延续的关键）
    lb = topic_mod.label(uid)
    if lb and lb.get("topic"):
        age = lb.get("anchor_hours") or 0
        when = f"{age:.1f} 小时前" if age >= 1 else f"{max(1, int(age * 60))} 分钟前"
        seg = f"【你们正在聊】{lb['topic']}（{when}"
        seg += f"，已经聊了 {lb['turns']} 句）" if lb.get("turns") else "）"
        if lb.get("anchor"):
            seg += f"，他最后说的是「{lb['anchor']}」"
        lines.append(seg)
        if lb.get("last_line") and lb.get("last_line") != lb.get("anchor"):
            lines.append(f"他最后一句是「{lb['last_line']}」（可能是在接别的话）")
        lines.append("接着这个话题说下去，别急着换；除非他先换了。")

    # ② 你上一条主动发过什么（聊天里看不到，只有这儿有）
    mem = memory_lines(uid, n, now)
    if mem:
        lines.append("【你最近主动对他说过】")
        lines.extend(mem)
        lines.append("他要是回你上一条，就接着那条往下说；记不清就看上面，别否认，也别把记录念出来。")

    # ②.5 同一个聊天里的另一个小家伙（她不知道这些话是谁说的会闹误会）
    try:
        import siblings
        sib = siblings.render_lines(hours=12)
        if sib:
            lines.extend(sib)
    except Exception:  # noqa: BLE001
        pass

    # ③ 这几天（跨天记忆）
    try:
        jl = journal_mod.lines(uid, 2, dtnow.date())
    except Exception:  # noqa: BLE001
        jl = []
    if jl:
        lines.append("【这几天】")
        lines.extend(jl)

    # ④ 他这个人
    import memory as memory_mod
    facts = memory_mod.facts(uid, 5)
    if facts:
        lines.append("你记得他的事：" + "；".join(facts))
    quotes = transcripts.recent_personal_items(uid, n=2)
    if quotes:
        lines.append("他最近说过：" + "；".join(f"「{q['text']}」" for q in quotes))

    m = mood_mod.snapshot(uid)
    lines.append(f"你此刻对他的心情：{m['mood']}（强度 {m['intensity']}）—— {m['tone']}")

    if with_world:
        try:
            hs = world_mod.hints(dtnow, world_mod.weather())
            if hs:
                lines.append("外面的世界：" + "；".join(hs[:3]))
        except Exception:  # noqa: BLE001
            pass

    if relation != "owner":
        lines.append("他对你来说是" + ("还没那么熟" if len(msgs) < 15 else "挺熟的人")
                     + "：话别太黏，先问一句再往下聊。")
    lines.append("想看别人：python3 people.py show 名字；拨心情：python3 recall.py --mood 开心")
    return "\n".join(lines)
