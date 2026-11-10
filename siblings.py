#!/usr/bin/env python3
"""同一个 QQ 里还有别的"小家伙"在说话时，小汐得知道。

比如 `~/.dsh/fish` 的大肥鱼（自称"鱼鱼"、叫对方"主人"）会自己冒泡。
用户看到的是同一个聊天窗口，很容易把它的消息当成小汐说的——
小汐就会一脸茫然："我没说过呀"。

这里读它的日志，把小汐不在场时"别人说的话"列出来，同时给守护进程一个
"别跟它撞车"的信号。

  python3 siblings.py            # 看看兄弟机器人最近说了什么
"""
import datetime as dt
import os
import re
import sys
import time

import paths
import store

DEFAULTS = [{
    "name": "大肥鱼",
    "self": "鱼鱼",
    "log": "~/.dsh/fish/poke.log",
    "pattern": r"已发送 \((.*)\) id=",
}]


def list_siblings():
    conf = (paths.config() or {}).get("siblings")
    return conf if isinstance(conf, list) and conf else DEFAULTS


def recent(hours=12, n=3):
    """兄弟机器人最近发出去的几句话：[{name, self, text, ts}]。"""
    cutoff = time.time() - hours * 3600
    out = []
    for sib in list_siblings():
        path = os.path.expanduser(sib.get("log", ""))
        if not path or not os.path.exists(path):
            continue
        pat = re.compile(sib.get("pattern") or DEFAULTS[0]["pattern"])
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-400:]
        except OSError:
            continue
        for line in lines:
            m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?)\]\s*(.*)",
                         line.strip())
            if not m:
                continue
            fmt = "%Y-%m-%d %H:%M:%S" if m.group(1).count(":") == 2 else "%Y-%m-%d %H:%M"
            try:
                ts = dt.datetime.strptime(m.group(1), fmt).timestamp()
            except ValueError:
                continue
            if ts < cutoff:
                continue
            mm = pat.search(m.group(2))
            if not mm:
                continue
            out.append({"name": sib.get("name"), "self": sib.get("self"),
                        "text": mm.group(1).strip(), "ts": ts})
    out.sort(key=lambda x: x["ts"])
    return out[-n:]


def last_ts():
    r = recent(hours=6, n=1)
    return r[-1]["ts"] if r else 0.0


def quiet(minutes=15):
    """兄弟刚说过话就别跟着说，免得用户一次收到两段。"""
    t = last_ts()
    return bool(t) and (time.time() - t) < minutes * 60


def render_lines(hours=12):
    r = recent(hours=hours, n=2)
    if not r:
        return []
    out = ["【同一个聊天里还有另一个小家伙】"]
    for it in r:
        when = dt.datetime.fromtimestamp(it["ts"]).strftime("%H:%M")
        out.append(f"- {when} 它说：「{it['text']}」（自称{it['self']}，叫你主人）")
    who = r[-1].get("self") or r[-1].get("name")
    out.append(f"上面这些不是你说的。对方接的话你要是没印象，很可能是{who}说的——"
               f"可以说「那句是{who}说的吧」，别否认、也别冒领。")
    return out


if __name__ == "__main__":
    for it in recent(hours=24, n=6):
        print(dt.datetime.fromtimestamp(it["ts"]).strftime("%m-%d %H:%M"),
              "|", it["name"], "|", it["text"])
    print("刚说过话？", quiet())
