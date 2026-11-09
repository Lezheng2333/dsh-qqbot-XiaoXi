#!/usr/bin/env python3
"""小汐自测 — 不碰 QQ、不碰真实数据，把多用户整条链路跑一遍。

  python3 selftest.py        # 3 个用户 × 完整链路（假发送，状态全在临时目录）
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 自测绝不碰真实数据：状态/日志/工作区/用户分区全走临时目录
_TMP = tempfile.mkdtemp(prefix="xiaoxi-selftest-")
os.environ.setdefault("XIAOXI_STATE_DIR", os.path.join(_TMP, "state"))
os.environ.setdefault("XIAOXI_LOGS", os.path.join(_TMP, "logs"))
os.environ.setdefault("XIAOXI_WORKSPACE", os.path.join(_TMP, "workspace"))
os.environ.setdefault("XIAOXI_USERS", os.path.join(_TMP, "users"))
for k in ("XIAOXI_STATE_DIR", "XIAOXI_LOGS", "XIAOXI_WORKSPACE", "XIAOXI_USERS"):
    os.makedirs(os.environ[k], exist_ok=True)

import daemon  # noqa: E402
import engagement  # noqa: E402
import memory  # noqa: E402
import messages  # noqa: E402
import mood  # noqa: E402
import notes  # noqa: E402
import paths  # noqa: E402
import people  # noqa: E402
import push  # noqa: E402
import store  # noqa: E402
import tts  # noqa: E402
import world  # noqa: E402

store.DAEMON_LOG = os.path.join(_TMP, "selftest.log")
store.rotate_log = lambda *a, **k: False

SENT = []
PROBLEMS = []


def fake_push():
    push.token = lambda force=False: "fake-token"
    push.typing = lambda seconds=4, tok=None, uid=None: None
    push.send_text = lambda content, tok=None, uid=None: SENT.append((uid, "text", content)) or {"ok": 1}
    push.send_image = lambda path, tok=None, uid=None: SENT.append((uid, "image", os.path.basename(path))) or {"ok": 1}
    push.send_voice = lambda path, tok=None, uid=None: SENT.append((uid, "voice", os.path.basename(path))) or {"ok": 1}


A = "AAAA0000000000000000000000000001"
B = "BBBB0000000000000000000000000002"


def setup_users():
    people.ensure(A, name="爸爸", relation="owner", proactive=True, call="爸爸")
    d = people.index()
    d["owner"] = A
    d["users"][A]["aliases"] = ["A"]
    people.save_index(d)
    people.ensure(B, name="老王", relation="friend", proactive=False)
    d = people.index()
    d["users"][B]["aliases"] = ["B"]
    people.save_index(d)
    memory.add("在忙一个大项目，代号「月光」", A)
    memory.add("喜欢听老歌", A)


def run_round(uid, force_sticker=False):
    plan = daemon.build_plan(uid, force_sticker=force_sticker)
    if plan.get("sticker"):
        daemon._attach_sticker(plan, daemon.cfg())
    daemon.deliver(plan, daemon.cfg())
    daemon._finish_round(plan, daemon.cfg())
    return plan


def main():
    fake_push()
    print("=== 1. 环境 ===")
    print("  core     :", paths.CORE)
    print("  临时数据 :", _TMP)
    print("  用户分区 :", paths.USERS_DIR)
    if not paths.CORE.startswith(os.sep):
        PROBLEMS.append("CORE 路径异常")

    print("\n=== 2. 用户分区 ===")
    setup_users()
    for uid, rec in people.profiles().items():
        print(f"  {rec['name']:4s} {rec['relation']:6s} proactive={rec['proactive']} "
              f"分区文件={sorted(os.listdir(os.path.join(paths.USERS_DIR, uid))) or '空'}")
    if len(people.profiles()) != 2:
        PROBLEMS.append("用户分区数量不对")

    print("\n=== 3. 按人分区的心情/话术 ===")
    for uid in (A, B):
        snap = mood.snapshot(uid)
        fam = daemon._familiar(uid)
        print(f"  {people.get(uid)['name']}: 心情={snap['mood']} 熟悉={fam} "
              f"撒娇权重={mood.bias_for(uid, snap, fam).get('coquette', 0):.2f}")
    a_cq = mood.bias_for(A, mood.snapshot(A), True).get("coquette", 0)
    b_cq = mood.bias_for(B, mood.snapshot(B), False).get("coquette", 0)
    if not a_cq > b_cq:
        PROBLEMS.append("陌生人的撒娇权重没有压低")

    print("\n=== 4. 完整发送链路（假发送）===")
    for uid in (A, B):
        plan = run_round(uid, force_sticker=True)
        st = plan.get("sticker") or {}
        print(f"  → {people.get(uid)['name']}: [{' / '.join(plan['texts'])}]"
              f" 表情={os.path.basename(st['path']) if st.get('path') else '-'}({st.get('source')})")
        if not os.path.exists(os.path.join(paths.USERS_DIR, uid, "notes.json")):
            PROBLEMS.append(f"{uid[:4]} 没写 notes")
    if len(SENT) < 4:
        PROBLEMS.append("假发送记录太少")

    print("\n=== 5. 隐私：B 的对话里不该出现 A 的事 ===")
    leaked = []
    for _ in range(8):
        plan = daemon.build_plan(B)
        text = " ".join(plan["texts"])
        if any(k in text for k in ("月光", "老歌")):
            leaked.append(text)
    print("  泄漏:", leaked or "无")
    if leaked:
        PROBLEMS.append("B 的话术里出现了 A 的记忆")

    print("\n=== 6. 跨区读（B 问 A 是什么人）===")
    print(people.summary_text(A).replace("\n", "\n  "))
    if "月光" not in people.summary_text(A):
        PROBLEMS.append("跨区读不到 A 的记忆")

    print("\n=== 7. 小本子不含私事 ===")
    notes.sync_agents_md(force=True)
    body = open(notes.AGENTS_MD, encoding="utf-8").read()
    print("  AGENTS.md 大小:", len(body), "字节")
    for secret in ("月光", "老歌"):
        if secret in body:
            PROBLEMS.append(f"工作区说明书里漏了私事：{secret}")
    print("  含私事:", "有（不对）" if any(s in body for s in ("月光", "老歌")) else "没有 ✓")

    print("\n=== 8. 回忆（按人）===")
    print(notes.render(A).replace("\n", "\n  ")[:600])

    print("\n=== 9. 去重 ===")
    seen = {}
    for _ in range(8):
        p = messages.compose(mood=mood.snapshot(A), world=world.snapshot(),
                             avoid=daemon.used_lines())
        for s in p["sources"]:
            n = daemon._norm(s)
            seen[n] = seen.get(n, 0) + 1
            daemon.remember_lines([s])
    dup = {k: v for k, v in seen.items() if v > 1}
    print("  8 轮内重复:", dup or "无")
    if dup:
        PROBLEMS.append(f"出现重复：{list(dup)[:3]}")

    print("\n=== 10. 语音 ===")
    for name, text in (("开心", "今天心情特别好"), ("困", "唔，好困呀")):
        path = tts.speak(text, mood=name)
        print(f"  {name}: {os.path.basename(path) if path else '失败'}")
        if not path:
            PROBLEMS.append(f"{name} 语音合成失败")

    print("\n=== 结果 ===")
    if PROBLEMS:
        print("发现问题：")
        for p in PROBLEMS:
            print("  -", p)
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
