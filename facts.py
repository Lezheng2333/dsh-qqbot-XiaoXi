#!/usr/bin/env python3
"""小汐的档案员 — 从聊天里把"关于这个人的硬信息"抽出来，补进记忆。

她自己会记，但经常只顾着聊天忘了记（"我是2002年3月24日出生的"->
她回了 ENFP，生日就没了）。所以这里用规则兜底：生日、MBTI、学校、
工作、喜好、家人、城市……抽到就写进 memory.json，去重、限量。

只扫"他说的"，不扫她说的；宁缺毋滥，抽不出来就算了。

  python3 facts.py            # 看扫描结果（不写）
  python3 facts.py --write    # 真的写进记忆
  python3 facts.py --backfill # 把整段历史扫一遍
"""
import re
import sys
import time

import memory
import paths
import people
import transcripts

MBTI = ("INTJ", "INTP", "ENTJ", "ENTP", "INFJ", "INFP", "ENFJ", "ENFP",
        "ISTJ", "ISFJ", "ESTJ", "ESFJ", "ISTP", "ISFP", "ESTP", "ESFP")

# (标签, 正则, 生成函数)
RULES = [
    ("生日", re.compile(r"((?:19|20)\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]"),
     lambda m: f"生日是 {m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"),
    ("生日", re.compile(r"我.{0,4}(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]"),
     lambda m: f"生日是 {int(m.group(1))} 月 {int(m.group(2))} 日"),
    ("MBTI", re.compile(r"(?i)(?<![A-Za-z])(" + "|".join(MBTI) + r")(?![A-Za-z])"),
     lambda m: f"MBTI 是 {m.group(1).upper()}"),
    # 学校：必须是他自己说的（我小学/我是…/保送/专业是…）
    ("学校", re.compile(r"(我(?:小学|初中|中学|高中|大学|研究生)|我是.{0,8}(?:小学|初中|中学|大学|学院)|保送|专业是|学的是)"),
     None),
    # 工作：我 + 工作/在…当/单位
    ("工作", re.compile(r"(我(?:的)?工作|我现在在|我就在|我在.{0,10}(?:工作|上班|当)|我是.{0,6}员)"),
     None),
    # 喜好：仅第一人称
    ("喜好", re.compile(r"我(?:平时|很|挺|也|最近|特别)?(?:喜欢|爱|迷上|在追|在玩)"),
     None),
    ("家人", re.compile(r"(我妹|我弟|我妈|我爸|我儿子|我女儿|我老婆|我对象|我爷爷|我奶奶)"), None),
    ("城市", re.compile(r"(?:我|现)?住在(成都|重庆|北京|上海|深圳|广州|杭州|西安|武汉|南京)"), None),
]

# 提问 / 指令 / 否定——这些不是"关于他的事实"
BAD = ("忘掉", "清掉", "删掉", "不要", "别记", "？", "?", "什么", "哪一", "怎么", "多少",
       "是不是", "吗", "呢")

NOISE = ("【表情", "- Image", "- File", "[图片]", "[文件]", "http")
MAX_AUTO = 40


def _clean(text):
    t = re.sub(r"【[^】]*】", "", text or "")
    t = re.sub(r"- (Image|File): \S+", "", t)
    t = re.sub(r"\[(图片|文件)\]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _sentence(text, around, width=46):
    """截到包含关键词的一句话，别把整段搬进去。"""
    t = _clean(text)
    if len(t) <= width:
        return t
    i = t.find(around)
    if i < 0:
        return t[:width]
    start = max(0, i - width // 2)
    return t[start:start + width]


def extract(text):
    """从一句话里抽事实。返回 [(标签, 事实)]。"""
    t = _clean(text)
    if not t or len(t) < 4:
        return []
    if any(n in t for n in NOISE):
        return []
    if any(b in t for b in BAD):
        return []
    if re.search(r"(喜欢|爱)(你|小汐)", t):
        return []
    out = []
    for label, pat, make in RULES:
        m = pat.search(t)
        if not m:
            continue
        if make is not None:
            out.append((label, make(m)))
        else:
            out.append((label, _sentence(t, m.group(0))))
    # 同一句里抽到太多标签，只留最有信息量的两个
    seen, uniq = set(), []
    for label, fact in out:
        key = re.sub(r"\W", "", fact)
        if key in seen:
            continue
        seen.add(key)
        uniq.append((label, fact))
    return uniq[:2]


def _existing_blob(uid):
    return " ".join(memory.facts(uid))


def _grams(t):
    t = re.sub(r"\W", "", t or "")
    return {t[i:i + 2] for i in range(len(t) - 1)}


def similar(fact, existing):
    g = _grams(fact)
    cs = set(re.sub(r"\W", "", fact))
    for f in existing:
        fg = _grams(f)
        if fg and g and len(g & fg) / len(g) > 0.5:
            return True
        cf = set(re.sub(r"\W", "", f))
        if cs and cf and len(cs & cf) / len(cs | cf) > 0.6:
            return True
    return False


def bday_of(fact):
    """从任意写法里抠出日期：2002-03-24 / 2002年3月24日 / 3月24日。"""
    m = re.search(r"((?:19|20)\d{2})\s*[-年]\s*(\d{1,2})\s*[-月]\s*(\d{1,2})", fact)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", fact)
    if m:
        return f"--{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return None


def _key(fact):
    """粗粒度去重键：生日/MBTI 只看值，其它看前 12 个字。"""
    b = bday_of(fact)
    if b:
        return "bday:" + b
    m = re.search("|".join(MBTI), fact, re.I)
    if m:
        return "mbti:" + m.group(0).upper()
    return re.sub(r"\W", "", fact)[:12]


def scan(uid, since_ts=0, write=False, limit=12):
    """扫这个人的消息，抽新事实。since_ts=0 表示整段历史。"""
    got, added = [], []
    existing = memory.facts(uid)
    blob = _existing_blob(uid)
    known = {_key(f) for f in existing}
    for m in transcripts.user_messages(uid=uid):
        if m["ts"] <= since_ts:
            continue
        for label, fact in extract(m["text"]):
            k = _key(fact)
            if k in known:
                continue
            if fact[:20] in blob or similar(fact, existing):
                continue
            known.add(k)
            got.append({"label": label, "fact": fact, "ts": m["ts"]})
            if write:
                memory.add(fact, uid)
                added.append(fact)
            if len(got) >= limit:
                break
        if len(got) >= limit:
            break
    return {"found": got, "added": added}


def scan_new(uid, write=True):
    """只扫"上次之后"的新消息；守护进程每轮调这个。"""
    import os
    st_path = os.path.join(paths.USERS_DIR, uid, "facts_state.json")
    st = paths.load_json(st_path, {}) or {}
    last = st.get("last_ts", 0)
    latest = transcripts.last_user_ts(uid=uid)
    if latest <= last:
        return {"found": [], "added": []}
    r = scan(uid, since_ts=last, write=write)
    st["last_ts"] = latest
    st["updated"] = time.time()
    paths.save_json(st_path, st)
    return r


if __name__ == "__main__":
    import json
    uid = people.current()
    write = "--write" in sys.argv
    backfill = "--backfill" in sys.argv
    since = 0 if backfill else 0
    r = scan(uid, since_ts=since, write=write)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    if not write:
        print("\n（加 --write 才会写进记忆）")
