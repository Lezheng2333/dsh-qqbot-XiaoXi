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

CORE = os.path.dirname(os.path.abspath(__file__))

CONFIG = os.path.join(CORE, "config.json")
PERSONA_DIR = os.path.join(CORE, "persona")
USERS_DIR = os.environ.get("XIAOXI_USERS") or os.path.join(CORE, "users")
LIB = os.path.join(CORE, "library")
MEDIA = os.path.join(CORE, "media")

# 这三个允许被环境变量重定向（自测用临时目录，绝不污染真实数据）
WORKSPACE = os.environ.get("XIAOXI_WORKSPACE") or os.path.join(CORE, "workspace")
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
    for d in (STATE_DIR, LOGS, USERS_DIR, WORKSPACE, LIB):
        os.makedirs(d, exist_ok=True)


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def save_json(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


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
