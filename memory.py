#!/usr/bin/env python3
"""小汐的记性 — 按人分区，记住每个人自己的事。

  python3 memory.py add "最近在忙职称评审"     # 记到"当前正在跟我说话的人"名下
  python3 memory.py list
  python3 memory.py remove 2
  python3 memory.py list --user 爸爸           # 看别人的（跨区只读）
"""
import json
import os
import sys
import time

import paths
import people


def path_of(uid=None):
    uid = uid or people.current()
    return people.path(uid, "memory.json")


def load(uid=None):
    d = paths.load_json(path_of(uid), None)
    if not isinstance(d, dict):
        d = {}
    d.setdefault("facts", [])
    d.setdefault("quotes", [])
    return d


def save(d, uid=None):
    """写之前把上一版留一份 memory.prev.json —— 被整份覆盖也能捞回来。"""
    src = path_of(uid)
    try:
        if os.path.exists(src):
            import shutil
            shutil.copy2(src, people.path(uid or people.current(), "memory.prev.json"))
    except Exception:  # noqa: BLE001
        pass
    paths.save_json(src, d)


def _log(uid, action, fact):
    """记一笔流水，万一将来记忆被误改写也知道原来是什么。"""
    uid = uid or people.current()
    path = people.path(uid, "memory_history.jsonl")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": int(time.time()), "action": action,
                                "fact": fact}, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def add(fact, uid=None, limit=40):
    fact = (fact or "").strip().strip("\"'")
    if fact.startswith("「") and fact.endswith("」"):
        fact = fact[1:-1].strip()
    if not fact:
        return None
    d = load(uid)
    if fact in d["facts"]:
        return None
    d["facts"].append(fact)
    d["facts"] = d["facts"][-limit:]
    save(d, uid)
    _log(uid, "add", fact)
    return fact


def remove(i, uid=None):
    d = load(uid)
    if 0 <= i < len(d["facts"]):
        gone = d["facts"].pop(i)
        save(d, uid)
        _log(uid, "remove", gone)
        return gone
    return None


def facts(uid=None, n=None):
    f = load(uid)["facts"]
    return f[-n:] if n else f


def quotes(uid=None, n=None):
    q = load(uid)["quotes"]
    return q[-n:] if n else q


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    uid = None
    if "--user" in sys.argv:
        i = sys.argv.index("--user")
        if i + 1 < len(sys.argv):
            uid = people.resolve(sys.argv[i + 1])
    uid = uid or people.current()
    who = (people.get(uid) or {}).get("name") or uid
    cmd = args[0] if args else "list"

    if cmd == "add" and len(args) > 1:
        got = add(args[1], uid)
        print(f"记到 {who} 名下: {got}" if got else "已有或为空")
    elif cmd == "remove" and len(args) > 1:
        gone = remove(int(args[1]) - 1, uid)
        print("忘掉:", gone) if gone else print("没有这条")
    else:
        print(f"# {who} 的事")
        for i, f in enumerate(facts(uid), 1):
            print(f"{i}. {f}")
