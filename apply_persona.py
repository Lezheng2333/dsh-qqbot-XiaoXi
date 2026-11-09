#!/usr/bin/env python3
"""把人设从 persona/*.md 装进 DSH 的 profile 补丁里。

人设的"真身"是本文件夹的 persona/direct.md 和 persona/group.md；
DSH 只认 ~/.dsh/profiles/<profile>/cordis.patch.yml，所以这里做一次同步：
· directPrompt / groupPrompt 整块替换（{CORE} 换成真实路径）
· im-qqbot 的 cwd 指向 <core>/workspace（她的工作区，也是小本子所在地）
· sendFile.extraRoots 指向 <core>/library（发图白名单）

改之前自动备份；改完会回读校验。搬去别的电脑只要跑一次。

  python3 apply_persona.py            # 同步
  python3 apply_persona.py --check    # 只看差异，不写
"""
import datetime as dt
import os
import re
import shutil
import sys

import paths

PROFILE_HINT = "im-qqbot"


def _backup(path):
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M")
    dst = f"{path}.bak-xiaoxi-{ts}"
    shutil.copy2(path, dst)
    return dst


def _find_block(lines, key, indent=4):
    head = f"{' ' * indent}{key}: |"
    for i, line in enumerate(lines):
        if line.rstrip() == head:
            end = i + 1
            while end < len(lines):
                cur = lines[end]
                if cur.strip() == "":
                    end += 1
                    continue
                if len(cur) - len(cur.lstrip()) <= indent:
                    break
                end += 1
            return i, end
    return None


def replace_literal(lines, key, text, indent=4):
    hit = _find_block(lines, key, indent)
    if not hit:
        return None
    start, end = hit
    block = [f"{' ' * indent}{key}: |"]
    for line in text.rstrip("\n").splitlines():
        block.append((" " * (indent + 2) + line) if line.strip() else "")
    return lines[:start] + block + lines[end:]


def _im_block(lines):
    start = None
    for i, line in enumerate(lines):
        if line.rstrip() == f"- id: {PROFILE_HINT}":
            start = i
            break
    if start is None:
        return None, None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^- ", lines[j]):
            end = j
            break
    return start, end


def set_scalar(lines, key, value, indent=4):
    start, end = _im_block(lines)
    if start is None:
        return lines
    pat = re.compile(rf"^{' ' * indent}{re.escape(key)}:.*$")
    for i in range(start, end):
        if pat.match(lines[i]):
            lines[i] = f"{' ' * indent}{key}: {value}"
            return lines
    # 没有就插在 config: 之后
    for i in range(start, end):
        if lines[i].rstrip() == f"{' ' * (indent - 2)}config:":
            lines.insert(i + 1, f"{' ' * indent}{key}: {value}")
            return lines
    return lines


def set_list(lines, key, items, indent=6):
    start, end = _im_block(lines)
    if start is None:
        return lines
    pat = re.compile(rf"^{' ' * indent}{re.escape(key)}:\s*$")
    for i in range(start, end):
        if pat.match(lines[i]):
            j = i + 1
            while j < len(lines) and (len(lines[j]) - len(lines[j].lstrip()) > indent):
                j += 1
            new = [f"{' ' * (indent + 2)}- {it}" for it in items]
            return lines[:i + 1] + new + lines[j:]
    return lines


def desired_prompts():
    core = paths.CORE
    out = {}
    for name, fname in (("directPrompt", "direct.md"), ("groupPrompt", "group.md")):
        p = os.path.join(paths.PERSONA_DIR, fname)
        text = open(p, encoding="utf-8").read().replace("{CORE}", core)
        out[name] = text.rstrip("\n")
    return out


def current_prompts(lines):
    out = {}
    for key in ("directPrompt", "groupPrompt"):
        hit = _find_block(lines, key)
        if not hit:
            out[key] = ""
            continue
        start, end = hit
        body = []
        for line in lines[start + 1:end]:
            body.append(line[6:] if line.startswith("      ") else line.strip())
        out[key] = "\n".join(body).rstrip("\n")
    return out


def apply(check_only=False):
    profile = paths.PROFILE_PATCH
    if not os.path.isfile(profile):
        return {"ok": False, "reason": f"找不到 DSH profile 补丁：{profile}"}
    lines = open(profile, encoding="utf-8").read().splitlines()
    want = desired_prompts()
    before = current_prompts(lines)

    changed = {k: before.get(k) != want[k] for k in want}
    cwd_want = paths.WORKSPACE
    extra_want = [paths.LIB]
    report = {"profile": profile, "changed": changed,
              "cwd": cwd_want, "extraRoots": extra_want}

    cwd_ok = any(l.rstrip() == f"    cwd: {cwd_want}" for l in lines)
    extra_ok = any(l.strip() == f"- {paths.LIB}" for l in lines)
    if check_only:
        return {"ok": True, "check": report}
    if not any(changed.values()) and cwd_ok and extra_ok:
        report.update({"ok": True, "no_change": True})
        return report

    for key, text in want.items():
        lines = replace_literal(lines, key, text)
    lines = set_scalar(lines, "cwd", cwd_want)
    lines = set_list(lines, "extraRoots", extra_want)

    bak = _backup(profile)
    with open(profile, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # 回读校验：人设确实写进去了、结构没坏
    after_lines = open(profile, encoding="utf-8").read().splitlines()
    after = current_prompts(after_lines)
    ok = all(after.get(k) == want[k] for k in want)
    ok = ok and after_lines.count("- id: im-qqbot") == 1
    ok = ok and any(l.rstrip() == f"    cwd: {cwd_want}" for l in after_lines)
    report.update({"ok": ok, "backup": bak,
                   "长度": {k: len(after.get(k, "")) for k in want}})
    return report


if __name__ == "__main__":
    check = "--check" in sys.argv
    import json
    print(json.dumps(apply(check_only=check), ensure_ascii=False, indent=1))
