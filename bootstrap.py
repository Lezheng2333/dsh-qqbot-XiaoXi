#!/usr/bin/env python3
"""把小汐装起来 / 搬到新电脑后恢复。

同一个脚本，三种用法：
  python3 bootstrap.py --check      # 只体检，不动任何东西
  python3 bootstrap.py             # 装好（人设→DSH、工作区说明书、定时冒泡）
  python3 bootstrap.py --no-launchd # 只准备文件，不装开机自启

它做的事：
1. 建目录、检查依赖（PIL / edge-tts / zstd）
2. 登记主人（openid 从 QQ 插件的 model-prefs.json 里发现，也可以 --owner 指定）
3. 把人设 persona/*.md 同步进 DSH profile（自动备份）
4. 生成工作区说明书 workspace/AGENTS.md
5. 建两个兼容桥（都是符号链接，不复制数据）：
     ~/.dsh-qqbot/workspace -> <core>/workspace  （旧会话的工作目录还指着这里）
     ~/.dsh-qqbot/media     -> <core>/media      （插件收到的图/歌也落在 core 里）
6. 写 launchd plist 并加载（macOS）
"""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import apply_persona  # noqa: E402
import notes  # noqa: E402
import paths  # noqa: E402
import people  # noqa: E402
import transcripts  # noqa: E402

PLIST_TMPL = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string>
    <string>{daemon}</string>
  </array>
  <key>WorkingDirectory</key><string>{core}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>XIAOXI_CORE</key>
    <string>{core}</string>
  </dict>
  <key>StandardOutPath</key><string>{out}</string>
  <key>StandardErrorPath</key><string>{err}</string>
</dict>
</plist>
"""


def check_env():
    out = {"core": paths.CORE, "python": sys.executable, "问题": []}
    for mod, name in (("PIL", "Pillow"), ("edge_tts", "edge-tts")):
        try:
            __import__(mod)
            out[name] = "有"
        except Exception:  # noqa: BLE001
            out[name] = "缺"
            out["问题"].append(name)
    out["zstd"] = transcripts.zstd_bin() or "缺"
    if not out["zstd"]:
        out["问题"].append("zstd")
    out["profile"] = paths.PROFILE_PATCH if os.path.isfile(paths.PROFILE_PATCH) else "找不到"
    out["QQ插件状态"] = paths.MODEL_PREFS if os.path.isfile(paths.MODEL_PREFS) else "找不到"
    out["会话目录"] = [os.path.basename(d) for d in transcripts.session_dirs()] or "还没有"
    out["用户"] = [f"{r.get('name')}({r.get('relation')})" for r in people.profiles().values()]
    out["工作区"] = paths.WORKSPACE
    return out


def ensure_owner(owner=None):
    """确定主人是谁；没有就登记一个。"""
    d = people.index()
    uid = owner or d.get("owner")
    if not uid:
        uid = paths.session_uid_map().get(transcripts.current_session().get("sid")
                                          if transcripts.current_session() else None)
    if not uid:
        found = list(paths.session_uid_map().values())
        uid = found[0] if found else None
    if not uid:
        return None
    rec = people.ensure(uid, name="爸爸", relation="owner", proactive=True, call="爸爸")
    d = people.index()
    d["owner"] = uid
    people.save_index(d)
    return rec


def bridge(src, dst):
    """建符号链接（不复制数据）；目标已存在且是链接就跳过。"""
    if os.path.islink(src):
        if os.path.realpath(src) == os.path.realpath(dst):
            return "已就绪"
        os.unlink(src)
    elif os.path.exists(src):
        return f"跳过（{src} 已经是真实目录，没有覆盖）"
    os.makedirs(os.path.dirname(src), exist_ok=True)
    os.symlink(dst, src)
    return "已创建"


def write_plist():
    os.makedirs(os.path.dirname(paths.PLIST), exist_ok=True)
    body = PLIST_TMPL.format(
        label=paths.LAUNCHD_LABEL, python=sys.executable,
        daemon=os.path.join(paths.CORE, "daemon.py"), core=paths.CORE,
        out=os.path.join(paths.LOGS, "launchd.out.log"),
        err=os.path.join(paths.LOGS, "launchd.err.log"))
    if os.path.isfile(paths.PLIST):
        ts = dt.datetime.now().strftime("%Y%m%d-%H%M")
        shutil.copy2(paths.PLIST, f"{paths.PLIST}.bak-{ts}")
    with open(paths.PLIST, "w", encoding="utf-8") as f:
        f.write(body)
    return paths.PLIST


def launchd(load=True):
    uid = os.getuid()
    plist = paths.PLIST
    res = {}
    if not load:
        return {"skipped": True}
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{paths.LAUNCHD_LABEL}"],
                   capture_output=True)
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", plist], capture_output=True)
    res["bootstrap"] = r.returncode
    if r.returncode != 0:
        res["bootstrap_err"] = r.stderr.decode(errors="ignore")[:300]
        r2 = subprocess.run(["launchctl", "load", "-w", plist], capture_output=True)
        res["load"] = r2.returncode
    return res


def sync_config():
    """把"当前所在位置"写回 config.json —— 文件夹搬了，这里也跟着对。"""
    c = paths.config()
    before = dict(c)
    c["agent_cwd"] = "workspace"     # 相对路径，避免把用户名/绝对路径写进仓库
    c.pop("owner_openid", None)      # openid 属于个人标识，只留在 users/（已 gitignore）
    if c != before:
        paths.save_json(paths.CONFIG, c)
        return "已更新"
    return "没变"


def install(owner=None, load_launchd=True, do_bridge=True):
    report = {"core": paths.CORE}
    paths.ensure_dirs()
    report["owner"] = (ensure_owner(owner) or {}).get("name") or "没登记（找不到 openid）"
    report["config"] = sync_config()
    report["persona"] = apply_persona.apply()
    report["说明书"] = "已写" if notes.sync_agents_md(force=True) else "没变"
    if do_bridge:
        legacy_ws = os.path.expanduser("~/.dsh-qqbot/workspace")
        # 只有"旧会话真的把工作目录钉在旧路径"时才建这个桥；
        # 新电脑上没有旧会话，就不会留任何东西。
        if transcripts.sessions_with_cwd(legacy_ws):
            report["桥·workspace"] = bridge(legacy_ws, paths.WORKSPACE)
        else:
            report["桥·workspace"] = "不需要（没有旧会话）"
        report["桥·media"] = bridge(os.path.expanduser("~/.dsh-qqbot/media"), paths.MEDIA)
    report["plist"] = write_plist()
    report["launchd"] = launchd(load=load_launchd)
    return report


def main():
    args = sys.argv[1:]
    if "--check" in args:
        print(json.dumps(check_env(), ensure_ascii=False, indent=1))
        return 0

    owner = None
    if "--owner" in args:
        i = args.index("--owner")
        owner = args[i + 1] if i + 1 < len(args) else None

    rep = install(owner=owner, load_launchd=("--no-launchd" not in args),
                  do_bridge=("--no-bridge" not in args))
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    print("\n下一步：")
    print(f"  python3 \"{paths.CORE}/daemon.py\" --status")
    print(f"  python3 \"{paths.CORE}/daemon.py\" --doctor")
    print("  QQ 里随便说句话，然后 tail 一下 logs/daemon.log 看她认不认得人")
    return 0


if __name__ == "__main__":
    sys.exit(main())
