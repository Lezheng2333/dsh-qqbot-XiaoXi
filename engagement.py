#!/usr/bin/env python3
"""小汐的分寸感 — 按人统计"她冒泡之后对方回没回"。

  python3 engagement.py            # 看对当前这个人的回复率
  python3 engagement.py reset
  python3 engagement.py list
"""
import json
import os
import sys
import time

import paths
import transcripts

KEEP = 60
WINDOW_MIN = 60
LOOKBACK = 12


def eng_path(uid):
    return os.path.join(paths.USERS_DIR, uid, "engagement.json")


def load(uid):
    d = paths.load_json(eng_path(uid), None)
    if not isinstance(d, dict):
        d = {}
    d.setdefault("sends", [])
    d.setdefault("updated", 0)
    return d


def save(d, uid):
    d["sends"] = d.get("sends", [])[-KEEP:]
    d["updated"] = time.time()
    paths.save_json(eng_path(uid), d)


def record_send(uid, ts=None, emotion=None, mood=None, texts=None):
    d = load(uid)
    d["sends"].append({"ts": ts or time.time(), "emotion": emotion, "mood": mood,
                       "texts": list(texts or [])[:3], "replied": None})
    save(d, uid)


def refresh(uid, now=None, window_min=WINDOW_MIN):
    now = now or time.time()
    d = load(uid)
    changed = False
    for s in d["sends"]:
        if s.get("replied") is not None:
            continue
        age = now - s["ts"]
        if age < 0:
            continue
        if age > window_min * 60:
            s["replied"] = bool(transcripts.replied_within(s["ts"], window_min, uid=uid))
            s["resolved_at"] = now
            changed = True
        elif transcripts.replied_within(s["ts"], window_min, uid=uid):
            s["replied"] = True
            s["resolved_at"] = now
            changed = True
    if changed:
        save(d, uid)

    resolved = [s for s in d["sends"] if s.get("replied") is not None]
    tail = resolved[-LOOKBACK:]
    rate = (sum(1 for s in tail if s["replied"]) / len(tail)) if tail else 0.5

    ignored = 0
    for s in reversed(resolved):
        if s["replied"]:
            break
        ignored += 1

    engaged = 0
    for s in reversed(resolved):
        if not s["replied"]:
            break
        engaged += 1

    if ignored >= 3:
        qf, gf, why = 0.45, 1.7, f"连着 {ignored} 次没回，收着点"
    elif ignored == 2:
        qf, gf, why = 0.6, 1.5, "连着两次没回，缓一缓"
    elif ignored == 1:
        qf, gf, why = 0.8, 1.2, "上一次没回，稍微等一下"
    elif len(tail) >= 4 and rate >= 0.6:
        qf, gf, why = 1.2, 0.85, f"最近回得挺勤（{rate:.0%}），可以多冒几个泡"
    else:
        qf, gf, why = 1.0, 1.0, "节奏正常"

    return {"samples": len(tail), "reply_rate": round(rate, 2),
            "ignored_streak": ignored, "engaged_streak": engaged,
            "quota_factor": qf, "gap_factor": gf, "reason": why}


def recent(uid, n=5):
    return load(uid)["sends"][-n:]


def reset(uid):
    save({"sends": [], "updated": time.time()}, uid)


if __name__ == "__main__":
    import people
    args = sys.argv[1:]
    if args and args[0] == "reset":
        reset(people.current())
        print("已清空")
    elif args and args[0] == "list":
        out = {}
        for uid, rec in people.profiles().items():
            out[rec.get("name") or uid] = refresh(uid)
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print(json.dumps(refresh(people.current()), ensure_ascii=False, indent=1))
