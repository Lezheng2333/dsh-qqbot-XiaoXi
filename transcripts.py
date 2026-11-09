#!/usr/bin/env python3
"""小汐的"耳朵" — 读 QQ 会话转录，按人分开看。

每个 QQ 用户有自己的会话（DSH 一个 openid 一个 session），
转录文件名里就带着 sessionId；`model-prefs.json` 把 sessionId 映射回 openid。
所以这里的每条消息都带 `_uid`，可以：

  transcripts.user_messages("E952...")   # 只看爸爸说的话
  transcripts.user_messages()            # 所有人（统计/兜底用）

读不到就返回空，绝不因为宿主环境变化而崩。
"""
import datetime as dt
import json
import os
import shutil
import subprocess
import time

import paths
import store

_CACHE_TTL = 45.0
_CACHE = {"at": 0.0, "sig": None, "events": []}
_FILE_CACHE = {}          # path -> {"key": (size, mtime), "events": [...], "uid": str}
_ZSTD = {"bin": None, "logged": False}
_SESS_CACHE = {"at": 0.0, "dirs": [], "cwd": None}
_SESS_CACHE_FILE = os.path.join(paths.STATE_DIR, "sessions_dir.json")


# ────────────────────────── zstd ──────────────────────────

def zstd_bin():
    """launchd 的 PATH 只有 /usr/bin:/bin:...，zstd 常在 /opt/homebrew/bin —— 显式找。"""
    if _ZSTD["bin"] is not None:
        return _ZSTD["bin"]
    for cand in [shutil.which("zstd"), "/opt/homebrew/bin/zstd",
                 "/usr/local/bin/zstd", "/usr/bin/zstd"]:
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            _ZSTD["bin"] = cand
            return cand
    try:
        import zstandard  # noqa: F401
        _ZSTD["bin"] = "py:zstandard"
        return _ZSTD["bin"]
    except Exception:  # noqa: BLE001
        _ZSTD["bin"] = ""
    if not _ZSTD["logged"]:
        _ZSTD["logged"] = True
        store.log("找不到 zstd，聊天记录读不了（回复率/作息会退回默认值）")
    return _ZSTD["bin"]


def _read_lines(path, limit=None, timeout=25):
    bin_ = zstd_bin()
    if not bin_:
        return []
    try:
        if bin_ == "py:zstandard":
            import zstandard
            with open(path, "rb") as f:
                data = zstandard.ZstdDecompressor().stream_reader(f).read().decode("utf-8", "ignore")
            lines = data.splitlines()
            return lines[-limit:] if limit else lines
        proc = subprocess.Popen([bin_, "-dc", path], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
        out, _ = proc.communicate(timeout=timeout)
        lines = out.decode("utf-8", "ignore").splitlines()
        return lines[-limit:] if limit else lines
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        return []


def _read_head(path, nbytes=4096):
    """只读会话文件开头（第一行是 session 头，里面有 cwd）。"""
    bin_ = zstd_bin()
    if not bin_ or bin_ == "py:zstandard":
        lines = _read_lines(path, limit=1)
        return lines[0] if lines else ""
    try:
        proc = subprocess.Popen([bin_, "-dc", path], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
        head = proc.stdout.read(nbytes)
        proc.kill()
        return head.decode("utf-8", "ignore").splitlines()[0] if head else ""
    except Exception:  # noqa: BLE001
        return ""


# ────────────────────────── 找会话目录 ──────────────────────────

def _probe_cwd_dirs(target):
    """扫一遍 ~/.dsh/sessions，找出会话 cwd == target 的目录（不靠目录名规则）。"""
    root = paths.SESSIONS_ROOT
    if not os.path.isdir(root):
        return []
    out = []
    for name in os.listdir(root):
        d = os.path.join(root, name)
        if not os.path.isdir(d):
            continue
        zs = []
        for dp, _, fns in os.walk(d):
            for f in fns:
                if f.endswith(".zstd"):
                    zs.append(os.path.join(dp, f))
        if not zs:
            continue
        newest = max(zs, key=os.path.getmtime)
        head = _read_head(newest)
        try:
            cwd = (json.loads(head) or {}).get("cwd")
        except Exception:  # noqa: BLE001
            cwd = None
        if cwd and os.path.abspath(cwd) == target:
            out.append(d)
    return out


def sessions_with_cwd(cwd):
    """哪些会话目录的工作目录是 cwd（换过工作目录时用来认旧会话）。"""
    return _probe_cwd_dirs(os.path.abspath(os.path.expanduser(cwd)))


def session_dirs(force=False):
    """小汐的会话目录：目录名规则猜 + 实际探测，两者合并，缓存 10 分钟。"""
    now = time.time()
    cwd = paths.WORKSPACE if not paths.config().get("agent_cwd") else paths.bot_cwd()
    if not force and _SESS_CACHE["cwd"] == cwd and now - _SESS_CACHE["at"] < 600:
        return list(_SESS_CACHE["dirs"])
    cached = paths.load_json(_SESS_CACHE_FILE, {}) or {}
    if (not force and cached.get("cwd") == cwd
            and now - cached.get("at", 0) < 600 and cached.get("dirs")):
        dirs = [d for d in cached["dirs"] if os.path.isdir(d)]
        if dirs:
            _SESS_CACHE.update({"at": now, "cwd": cwd, "dirs": dirs})
            return list(dirs)

    dirs = []
    for d in paths.session_dirs():
        if os.path.isdir(d) and d not in dirs:
            dirs.append(d)
    for d in _probe_cwd_dirs(paths.bot_cwd()):
        if d not in dirs:
            dirs.append(d)
    # 旧工作目录（搬目录之前建的会话）也别丢
    legacy_ws = os.path.abspath(os.path.expanduser("~/.dsh-qqbot/workspace"))
    for d in _probe_cwd_dirs(legacy_ws):
        if d not in dirs:
            dirs.append(d)
    _SESS_CACHE.update({"at": now, "cwd": cwd, "dirs": dirs})
    try:
        paths.save_json(_SESS_CACHE_FILE, {"cwd": cwd, "dirs": dirs, "at": now})
    except Exception:  # noqa: BLE001
        pass
    return list(dirs)


# ────────────────────────── 读事件 ──────────────────────────

def _session_files(limit=8):
    out = []
    uid_map = paths.session_uid_map()
    for root in session_dirs():
        for dp, _, fns in os.walk(root):
            for name in fns:
                if not (name.startswith("session") and name.endswith(".zstd")):
                    continue
                path = os.path.join(dp, name)
                # 会话目录名就是 session-<id>，model-prefs 里也是这个形式
                sid = os.path.basename(dp)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                out.append({"path": path, "sid": sid, "mtime": st.st_mtime,
                            "size": st.st_size, "uid": uid_map.get(sid)})
    out.sort(key=lambda x: x["mtime"])
    return out[-limit:]


def _file_events(rec):
    key = (rec["size"], int(rec["mtime"]))
    c = _FILE_CACHE.get(rec["path"])
    if c and c["key"] == key:
        return c["events"]
    evs = []
    for line in _read_lines(rec["path"], limit=3000):
        try:
            ev = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(ev, dict):
            ev["_uid"] = rec["uid"]
            ev["_sid"] = rec["sid"]
            evs.append(ev)
    _FILE_CACHE[rec["path"]] = {"key": key, "events": evs}
    return evs


def events(uid=None, ttl=_CACHE_TTL):
    """所有会话的最近事件；uid 给了就只留那个人的。"""
    files = _session_files()
    sig = tuple((f["path"], f["size"], int(f["mtime"])) for f in files)
    if _CACHE["sig"] != sig or (time.time() - _CACHE["at"]) > ttl:
        merged = []
        for rec in files:
            merged.extend(_file_events(rec))
        merged.sort(key=lambda e: e.get("time") or 0)
        _CACHE.update({"sig": sig, "at": time.time(), "events": merged})
    evs = _CACHE["events"]
    return [e for e in evs if e.get("_uid") == uid] if uid else evs


def _text_of(data):
    return "".join(c.get("text", "") for c in (data.get("content") or [])
                   if c.get("type") == "text").strip()


def user_messages(uid=None, ttl=_CACHE_TTL):
    """真人说的话：[{ts, text, hour, date, uid}]。"""
    out = []
    for ev in events(uid=uid, ttl=ttl):
        if ev.get("type") != "user/message":
            continue
        data = ev.get("data") or {}
        if (data.get("source") or {}).get("kind") != "user":
            continue
        text = _text_of(data)
        if not text or text.startswith("Time sampled"):
            continue
        ts = (ev.get("time") or 0) / 1000.0
        if ts <= 0:
            continue
        local = dt.datetime.fromtimestamp(ts)
        out.append({"ts": ts, "text": text, "hour": local.hour,
                    "date": local.date().isoformat(), "uid": ev.get("_uid")})
    return out


def last_user_ts(uid=None, ttl=_CACHE_TTL):
    msgs = user_messages(uid=uid, ttl=ttl)
    return msgs[-1]["ts"] if msgs else 0.0


def replied_within(ts, minutes=60, uid=None, ttl=_CACHE_TTL):
    for m in user_messages(uid=uid, ttl=ttl):
        if ts < m["ts"] <= ts + minutes * 60:
            return True
    return False


def current_session():
    """刚刚在说话的那个会话（谁的会话文件最新，就是谁）。"""
    files = _session_files()
    if not files:
        return None
    return files[-1]


# ────────────────────────── 挑"生活碎碎念" ──────────────────────────

CMD_HINTS = ("介绍", "帮我", "查一下", "查查", "写个", "改一下", "打开", "运行",
             "安装", "总结", "翻译", "你是", "你好", "在吗", "测试", "生成")
PERSONAL_HINTS = ("我", "今天", "最近", "累", "忙", "想", "喜欢", "准备", "睡",
                  "吃", "做", "弄", "加班", "烦", "开心", "难过")
QUESTION_HINTS = ("吗", "呢", "怎么", "什么", "多久", "几号", "哪天", "是不是",
                  "会不会", "能不能", "可不可以", "有没有", "如何", "为什么", "多少")
TECH_HINTS = ("token", "Token", "TOKEN", "接口", "代码", "命令", "插件", "模型",
              "程序", "报错", "部署", "服务器", "文件", "路径", "配置", "harness",
              "Harness", "deepseek", "DeepSeek", "API", "api", "prompt", "bug")


def looks_personal(text):
    text = text.strip()
    if not (4 <= len(text) <= 40):
        return False
    if text.startswith(CMD_HINTS):
        return False
    if any(ch in text for ch in "?？:"):
        return False
    if any(h in text for h in QUESTION_HINTS):
        return False
    if any(h in text for h in TECH_HINTS):
        return False
    if text.startswith("- Image") or text.startswith("- File") or "[图片]" in text:
        return False
    if "/Users/" in text:
        return False
    return any(k in text for k in PERSONAL_HINTS)


def recent_personal_items(uid=None, n=6, days=7, ttl=_CACHE_TTL):
    cutoff = time.time() - days * 86400
    items = [{"text": m["text"], "ts": m["ts"]} for m in user_messages(uid=uid, ttl=ttl)
             if m["ts"] >= cutoff and looks_personal(m["text"])]
    return items[-n:]


def recent_personal(uid=None, n=6, days=7, ttl=_CACHE_TTL):
    return [it["text"] for it in recent_personal_items(uid, n, days, ttl)]


def recent_texts(uid=None, n=12, days=3, ttl=_CACHE_TTL):
    cutoff = time.time() - days * 86400
    return [m for m in user_messages(uid=uid, ttl=ttl) if m["ts"] >= cutoff][-n:]


# ────────────────────────── 作息 ──────────────────────────

def hour_weights(uid=None, days=21, ttl=_CACHE_TTL):
    cutoff = time.time() - days * 86400
    hist = {}
    for m in user_messages(uid=uid, ttl=ttl):
        if m["ts"] < cutoff:
            continue
        age_days = (time.time() - m["ts"]) / 86400
        w = 0.5 ** (age_days / 7.0)
        hist[m["hour"]] = hist.get(m["hour"], 0.0) + w
    return hist


def active_window(uid=None, fallback=(8, 24), min_weight=6.0, min_hours=8, ttl=_CACHE_TTL):
    hist = hour_weights(uid=uid, ttl=ttl)
    total = sum(hist.values())
    if total < min_weight or len([w for w in hist.values() if w >= 0.3]) < 4:
        return list(fallback)
    cum, lo, hi = 0.0, None, None
    for h in range(24):
        cum += hist.get(h, 0.0)
        if lo is None and cum >= total * 0.05:
            lo = h
        if cum <= total * 0.97:
            hi = h
    if lo is None or hi is None or hi < lo:
        return list(fallback)
    lo = max(6, lo - 1)
    hi = min(24, hi + 2)
    if hi - lo < min_hours:
        mid = (lo + hi) // 2
        lo = max(6, mid - min_hours // 2)
        hi = min(24, lo + min_hours)
    return [lo, hi]


if __name__ == "__main__":
    print(json.dumps({
        "会话目录": session_dirs(),
        "会话数": len(_session_files()),
        "当前会话": current_session(),
        "所有消息": len(user_messages()),
        "窗口": active_window(),
    }, ensure_ascii=False, indent=1))
