#!/usr/bin/env python3
"""小汐的小工具层 — 原子 JSON 读写、带轮转的日志、心跳。

所有路径都从 paths.py 来，整个文件夹搬走不会断。
"""
import datetime as dt
import json
import os
import sys
import time

import paths

ROOT = paths.CORE
STATE_DIR = paths.STATE_DIR
LOGS = paths.LOGS
DAEMON_LOG = paths.DAEMON_LOG
LOG_MAX_BYTES = 3 * 1024 * 1024
LOG_KEEP = 3
# 只有在终端里跑才回显到 stdout；launchd 下只写 daemon.log，
# 免得 launchd.out.log 无限增长（那个文件我们没法自己轮转）。
ECHO = sys.stdout.isatty() or os.environ.get("XIAOXI_ECHO") == "1"


def now():
    return dt.datetime.now()


def ensure_dirs():
    paths.ensure_dirs()


def state_path(name):
    return os.path.join(STATE_DIR, name)


def load_json(path, default=None):
    return paths.load_json(path, default)


def save_json(path, data):
    paths.save_json(path, data)


def rotate_log(path, max_bytes=LOG_MAX_BYTES, keep=LOG_KEEP):
    """超过上限就滚一份，最多留 keep 个 .N。"""
    try:
        if os.path.getsize(path) <= max_bytes:
            return False
    except OSError:
        return False
    try:
        for i in range(keep, 0, -1):
            src = f"{path}.{i}"
            dst = f"{path}.{i + 1}"
            if i == keep:
                if os.path.exists(src):
                    os.remove(src)
                continue
            if os.path.exists(src):
                os.replace(src, dst)
        os.replace(path, f"{path}.1")
        return True
    except OSError:
        return False


_LAST_ROTATE = [0.0]


def log(msg, path=None, echo=None):
    ensure_dirs()
    path = path or DAEMON_LOG
    line = f"[{now():%Y-%m-%d %H:%M:%S}] {msg}"
    try:
        if time.time() - _LAST_ROTATE[0] > 3600:
            _LAST_ROTATE[0] = time.time()
            rotate_log(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass
    if (ECHO if echo is None else echo):
        print(line, flush=True)
    return line


# ────────────────────────── 心跳 ──────────────────────────

HEARTBEAT = os.path.join(STATE_DIR, "heartbeat.json")
_STARTED = time.time()


def heartbeat(**fields):
    """每轮循环写一次；--status / doctor 靠它判断守护进程是否活着。"""
    hb = load_json(HEARTBEAT, {}) or {}
    prev_pid = hb.get("pid")
    hb.update({"pid": os.getpid(), "started_at": _STARTED,
               "uptime_min": round((time.time() - _STARTED) / 60, 1),
               "beat_at": time.time(), "beat_local": f"{now():%m-%d %H:%M:%S}"})
    hb.update(fields)
    if prev_pid not in (None, os.getpid()):
        hb["beats"] = 0          # 换了个进程，心跳从头数
    hb["beats"] = int(hb.get("beats", 0)) + 1
    save_json(HEARTBEAT, hb)
    return hb


def read_heartbeat():
    return load_json(HEARTBEAT, {}) or {}
