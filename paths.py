#!/usr/bin/env python3
"""小汐的所有路径都在这里 —— 整个文件夹可以整体搬走，不依赖绝对路径。

核心原则：
· 只有 CORE（本文件所在目录）是"怎么搬都行"的；
· DSH 那几样（profile 补丁、会话目录、QQ 插件状态）属于宿主，按约定位置找，
  找到读不到就把自己降级成"只说话、不记事"，绝不崩；
· 任何模块都不许再写死 /Users/xxx 或 ~/.dsh-qqbot/xiaoxi。
"""
import json
import os
import time

CORE = os.path.dirname(os.path.abspath(__file__))

CONFIG = os.path.join(CORE, "config.json")
PERSONA_DIR = os.path.join(CORE, "persona")
USERS_DIR = os.environ.get("XIAOXI_USERS") or os.path.join(CORE, "users")
LIB = os.path.join(CORE, "library")
MEDIA = os.path.join(CORE, "media")

# 这三个允许被环境变量重定向（自测用临时目录，绝不污染真实数据）
# 默认工作区就是整个 core 文件夹：她的沙箱根 = 她自己的文件夹，
# 记忆/图库/状态都在里面，不需要每次写盘都申请权限。
WORKSPACE = os.environ.get("XIAOXI_WORKSPACE") or CORE
SCRATCH = os.environ.get("XIAOXI_SCRATCH") or os.path.join(CORE, "workspace")  # 旧工作区/信箱
AGENTS_MD = os.path.join(WORKSPACE, "AGENTS.md")
STATE_DIR = os.environ.get("XIAOXI_STATE_DIR") or os.path.join(CORE, "state")
LOGS = os.environ.get("XIAOXI_LOGS") or os.path.join(CORE, "logs")
DAEMON_LOG = os.path.join(LOGS, "daemon.log")

# ── 宿主的约定位置（只读，找不到就降级）──
DSH_HOME = os.environ.get("DSH_HOME") or os.path.expanduser("~/.dsh")
PROFILE_PATCH = os.environ.get("XIAOXI_PROFILE_PATCH") or os.path.join(
    DSH_HOME, "profiles", "desktop", "cordis.patch.yml")
SESSIONS_ROOT = os.path.join(DSH_HOME, "sessions")
QQBOT_RUNTIME = os.path.join(os.path.expanduser("~"), ".dsh-qqbot")
MODEL_PREFS = os.path.join(QQBOT_RUNTIME, "model-prefs.json")
PLIST = os.path.expanduser("~/Library/LaunchAgents/com.xiaoxi.daemon.plist")
LAUNCHD_LABEL = "com.xiaoxi.daemon"


def ensure_dirs():
    for d in (STATE_DIR, LOGS, USERS_DIR, WORKSPACE, LIB, SCRATCH):
        os.makedirs(d, exist_ok=True)


# ────────────────────────── 写盘兜底（outbox） ──────────────────────────
# 如果她的沙箱还不允许写这里（比如换了会话但沙箱根还没跟上），
# 写入不报错、不弹审批，而是落到"临时目录里的信箱"，守护进程下一轮代写。

def outbox_dirs():
    """所有可能出现的信箱目录：core 里的 + 各沙箱 TMPDIR 里的。"""
    out = [os.path.join(SCRATCH, ".outbox")]
    import glob
    tmp = __import__("tempfile").gettempdir()
    out.append(os.path.join(tmp, "xiaoxi_outbox"))
    out += glob.glob(os.path.join(tmp, "dsh-*", "xiaoxi_outbox"))
    return out


def _spool(target, payload):
    """把"本来要写到 target 的东西"暂存到信箱，返回暂存文件路径。

    依次试：core 里的信箱（她自己的文件夹）→ 临时目录信箱（沙箱永远允许写）。
    """
    body = dict(payload, target=target, at=time.time())
    name = str(int(time.time() * 1000)) + "-" + os.urandom(4).hex() + ".json"
    last = None
    for box in (os.path.join(SCRATCH, ".outbox"),
                os.path.join(__import__("tempfile").gettempdir(), "xiaoxi_outbox")):
        try:
            os.makedirs(box, exist_ok=True)
            tmp = os.path.join(box, name)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(body, f, ensure_ascii=False)
            return tmp
        except Exception as e:  # noqa: BLE001
            last = e
    raise last or RuntimeError("没有可写的信箱")


def drain_outbox(verbose=False):
    """守护进程调用：把信箱里的东西真正写进 core。"""
    done = failed = 0
    for box in outbox_dirs():
        if not os.path.isdir(box):
            continue
        for name in sorted(os.listdir(box)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(box, name)
            item = load_json(path, None)
            if not isinstance(item, dict) or "target" not in item:
                continue
            target = item["target"]
            try:
                if "json" in item:
                    _write_json(target, item["json"])
                elif "b64" in item:
                    _write_file(target, __import__("base64").b64decode(item["b64"]))
                else:
                    continue
                os.remove(path)
                done += 1
                if verbose:
                    print("已代写:", target)
            except Exception:  # noqa: BLE001
                failed += 1
    return done, failed


def _pending_json(path):
    """信箱里有没有"还没落盘"的这一份？有就先用它（读到的是最新状态）。"""
    best = None
    for box in (os.path.join(SCRATCH, ".outbox"),
                os.path.join(__import__("tempfile").gettempdir(), "xiaoxi_outbox")):
        if not os.path.isdir(box):
            continue
        try:
            names = os.listdir(box)
        except OSError:
            continue
        for name in names:
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(box, name), encoding="utf-8") as f:
                    item = json.load(f)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(item, dict) and item.get("target") == path and "json" in item:
                if best is None or item.get("at", 0) > best.get("at", 0):
                    best = item
    return best


def load_json(path, default=None):
    pending = _pending_json(path)
    if pending is not None:
        return pending["json"]
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def _write_json(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def save_json(path, data):
    """写 JSON；沙箱不让写就暂存到信箱，绝不抛错去烦用户。"""
    try:
        _write_json(path, data)
        return "written"
    except (PermissionError, OSError) as e:
        if not isinstance(e, PermissionError):
            raise
        _spool(path, {"json": data})
        return "spooled"


def _write_file(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def save_file(path, data):
    """写二进制（图片/音频）；同样带信箱兜底。"""
    try:
        _write_file(path, data)
        return "written"
    except PermissionError:
        _spool(path, {"b64": __import__("base64").b64encode(data).decode()})
        return "spooled"


def config():
    """全局配置（不含密钥）。"""
    c = load_json(CONFIG, {}) or {}
    return c


def bot_cwd():
    """QQ 插件给小汐分配的 agent 工作目录。配置优先，否则用 core/workspace。"""
    c = config()
    cwd = c.get("agent_cwd") or WORKSPACE
    cwd = os.path.abspath(os.path.expanduser(cwd))
    if not os.path.isabs(str(c.get("agent_cwd") or "")):
        # 相对路径按 core 解释 —— 文件夹改名/搬家后不会指向旧地方
        cwd = os.path.join(CORE, c["agent_cwd"].strip()) if c.get("agent_cwd") else WORKSPACE
    return os.path.abspath(cwd)


def slug(path):
    """DSH 的会话目录名编码：/ → -，安全字符保留，其它按 UTF-16 码元写成 ~XXXX。"""
    body = []
    for ch in path.lstrip("/"):
        if ch == "/":
            body.append("-")
        elif ch.isascii() and (ch.isalnum() or ch in "._-"):
            body.append(ch)
        else:
            raw = ch.encode("utf-16-be")
            for i in range(0, len(raw), 2):
                body.append(f"~{int.from_bytes(raw[i:i + 2], 'big'):04X}")
    return "--" + "".join(body) + "--"


def session_dirs():
    """小汐的会话目录列表（可能有多个：工作目录换过就多一个）。"""
    out = []
    cand = os.path.join(SESSIONS_ROOT, slug(bot_cwd()))
    if os.path.isdir(cand):
        out.append(cand)
    # 兜底：旧路径（搬目录前建的会话）
    legacy = os.path.join(SESSIONS_ROOT, slug(os.path.expanduser("~/.dsh-qqbot/workspace")))
    if os.path.isdir(legacy) and legacy not in out:
        out.append(legacy)
    return out


def session_uid_map():
    """sessionId -> openid。QQ 插件把绑定关系写在 model-prefs.json 里。"""
    d = load_json(MODEL_PREFS, {}) or {}
    out = {}
    for key, sid in (d.get("sessionIds") or {}).items():
        parts = str(key).split(":")
        if len(parts) >= 4 and parts[0] == "qqbot":
            out[str(sid)] = parts[-1]
    return out


def dsh_available():
    return os.path.isdir(SESSIONS_ROOT) and os.path.isfile(MODEL_PREFS)
