#!/usr/bin/env python3
"""小汐认识的人 — 每个 QQ 用户一个分区，谁跟她说的话就记在谁名下。

分区规则：
  users/<openid>/memory.json      记得他的事
  users/<openid>/notes.json       她对他主动说过的话
  users/<openid>/mood.json        对他时的心情
  users/<openid>/engagement.json  他对她回不回的统计
  users/<openid>/state.json       他这条线的额度/下次时间

"我是谁在跟我说话"靠两件事：QQ 插件把 openid→sessionId 写在 model-prefs.json，
每次聊天只有一条会话在写，所以最新那个会话就是对面这个人。

跨区读：summary() 只给"印象和近况"，不搬私密细节。

  python3 people.py                 # 我是谁、有几个人
  python3 people.py list
  python3 people.py show 爸爸        # 跨区看：她记得这个人什么
  python3 people.py name 老王        # 把当前这个人改名
"""
import json
import os
import sys
import time

import paths
import store
import transcripts

INDEX = os.path.join(paths.USERS_DIR, "index.json")
_DEFAULT = {"users": {}, "owner": None}


# ────────────────────────── 索引 ──────────────────────────

def index():
    d = paths.load_json(INDEX, None)
    if not isinstance(d, dict):
        d = {}
    d.setdefault("users", {})
    d.setdefault("owner", None)
    return d


def save_index(d):
    paths.ensure_dirs()
    paths.save_json(INDEX, d)


def owner():
    return index().get("owner")


def profiles():
    return index()["users"]


def get(uid):
    if not uid:
        return None
    return index()["users"].get(uid)


def path(uid, name):
    return os.path.join(paths.USERS_DIR, uid, name)


def ensure(uid, name=None, relation="friend", proactive=False, call=None):
    """没有这个人就建分区；有就补字段（不覆盖已有名字）。

    没有实际变化就不写盘——recall.py / push.py 会频繁调它。
    """
    d = index()
    rec = d["users"].get(uid)
    now = time.time()
    if rec is not None:
        rec.setdefault("aliases", [])
        touched = False
        if now - rec.get("last_seen", 0) > 6 * 3600:
            rec["last_seen"] = now
            touched = True
        if name and str(rec.get("name", "")).startswith("用户_"):
            rec["name"] = name
            touched = True
        os.makedirs(os.path.join(paths.USERS_DIR, uid), exist_ok=True)
        if touched:
            save_index(d)
        return rec
    if rec is None:
        rec = {
            "uid": uid,
            "name": name or f"用户_{uid[:6]}",
            "call": call or "你",
            "relation": relation,
            "proactive": bool(proactive),
            "aliases": [],
            "first_seen": now,
            "last_seen": now,
            "note": "",
        }
        d["users"][uid] = rec
    else:
        rec.setdefault("aliases", [])
        rec["last_seen"] = max(rec.get("last_seen", 0), now)
        if name and rec.get("name", "").startswith("用户_"):
            rec["name"] = name
    if d.get("owner") is None and relation == "owner":
        d["owner"] = uid
    save_index(d)
    os.makedirs(os.path.join(paths.USERS_DIR, uid), exist_ok=True)
    return rec


def rename(uid, name, call=None):
    d = index()
    rec = d["users"].get(uid)
    if not rec:
        return None
    rec["name"] = name
    if call:
        rec["call"] = call
    save_index(d)
    return rec


def resolve(token):
    """用 uid / 名字 / 别名 / uid 前缀找一个人。"""
    if not token:
        return None
    token = str(token).strip()
    users = profiles()
    if token in users:
        return token
    low = token.lower()
    for uid, rec in users.items():
        names = [rec.get("name") or "", rec.get("call") or ""] + list(rec.get("aliases") or [])
        if any(low == str(n).lower() for n in names if n):
            return uid
    for uid, rec in users.items():
        names = [rec.get("name") or ""] + list(rec.get("aliases") or [])
        if any(low in str(n).lower() for n in names if n):
            return uid
    for uid in users:
        if uid.lower().startswith(low):
            return uid
    return None


# ────────────────────────── 我是谁 ──────────────────────────

def current(create=True):
    """正在跟她说话的人（openid）。认不出来就退回主人。"""
    rec = transcripts.current_session()
    uid = (rec or {}).get("uid")
    if uid:
        if create:
            ensure(uid, proactive=(uid == owner()))
        return uid
    return owner()


def whoami():
    rec = transcripts.current_session() or {}
    uid = rec.get("uid")
    source = "会话映射"
    if not uid:
        uid = owner()
        source = "退回主人（会话映射没认出来）"
    prof = get(uid) or (ensure(uid) if uid else None)
    return {"uid": uid, "name": (prof or {}).get("name"), "relation": (prof or {}).get("relation"),
            "session": rec.get("sid"), "source": source,
            "identified": bool(rec.get("uid"))}


# ────────────────────────── 跨区读 ──────────────────────────

def _facts(uid, limit=6):
    d = paths.load_json(path(uid, "memory.json"), {}) or {}
    return [f for f in (d.get("facts") or []) if f][-limit:]


def summary(uid, facts_limit=6):
    """给"B 问起 A"用的画像：关系、聊了多少、最近在意什么。"""
    rec = get(uid) or {}
    msgs = transcripts.user_messages(uid=uid)
    topics = [it["text"] for it in transcripts.recent_personal_items(uid, n=facts_limit)]
    return {
        "uid": uid,
        "name": rec.get("name"),
        "relation": rec.get("relation"),
        "alias": rec.get("aliases") or [],
        "messages": len(msgs),
        "last_talk": msgs[-1]["ts"] if msgs else 0,
        "first_seen": rec.get("first_seen"),
        "facts": _facts(uid, facts_limit),
        "recent_words": topics,
    }


def summary_text(uid, max_facts=4):
    s = summary(uid)
    if not s.get("name"):
        return "我对这个人还没什么印象。"
    lines = [f"我记得的是：{s['name']}"]
    if s.get("relation") == "owner":
        lines[0] += "（我的爸爸，最重要的那个人）"
    if s.get("messages"):
        lines.append(f"我们聊过 {s['messages']} 次话")
    if s.get("last_talk"):
        import datetime as dt
        when = dt.datetime.fromtimestamp(s["last_talk"])
        lines.append(f"最后一次是 {when:%m-%d %H:%M}")
    if s.get("facts"):
        lines.append("我记着他的事：" + "；".join(s["facts"][-max_facts:]))
    if s.get("recent_words"):
        lines.append("他最近说过：" + "；".join(s["recent_words"][-2:]))
    return "\n".join(lines)


# ────────────────────────── 命令行 ──────────────────────────

def _print(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0] if args else "me"
    if cmd == "me":
        _print(whoami())
    elif cmd == "list":
        rows = []
        for uid, rec in profiles().items():
            rows.append({"uid": uid, "name": rec.get("name"),
                         "relation": rec.get("relation"),
                         "proactive": rec.get("proactive"),
                         "消息数": len(transcripts.user_messages(uid=uid))})
        _print({"owner": owner(), "users": rows})
    elif cmd == "show" and len(args) > 1:
        uid = resolve(args[1]) or current()
        print(summary_text(uid))
    elif cmd == "discover":
        m = paths.session_uid_map()
        print(json.dumps({"发现这些人（openid -> 会话）": m,
                          "提示": "换电脑后先让 TA 发条消息，再跑 python3 bootstrap.py --owner <openid>"},
                         ensure_ascii=False, indent=1))
    elif cmd == "name" and len(args) > 1:
        uid = current()
        call = args[2] if len(args) > 2 else None
        print(rename(uid, args[1], call) and f"改好了：{args[1]}")
    else:
        print(__doc__)
