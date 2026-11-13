#!/usr/bin/env python3
"""小汐的表情包 — 只发"鲸鱼娘"系可爱图，别的材料一张都不发。

规则（爸爸定的）：
· 只许发鲸鱼 / 鲸鱼娘 / 小鲸鱼这类可爱图；
· 网上现抓的"暴走漫画/沙雕表情"一律不要——那些看着像猥琐大汉；
· 新图先落到 candidate/，人工（或 AI）看过、确认可爱，才 promote 进 whale/。

所以这个模块分两侧：
  发送侧 pick()  只从 library/whale/ 里挑（index.json 带情绪标签）
  采集侧 fetch()  用"鲸鱼娘"关键词搜图，只落 candidate/，绝不自动发

  python3 stickers.py pick 撒娇          # 挑一张（发给 QQ 用）
  python3 stickers.py stats             # 图库统计
  python3 stickers.py sheet             # 生成审图拼图 library/whale_sheet.png
  python3 stickers.py add <图> <情绪>    # 把审过的图正式加进池子
  python3 stickers.py fetch 5           # 抓 5 张候选（只进 candidate/）
  python3 stickers.py search 鲸鱼娘      # 只打印搜到的图片链接
"""
import hashlib
import io
import json
import os
import random
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request

from PIL import Image

import paths
import store

LIB = paths.LIB
WHALE = os.path.join(LIB, "whale")
CAND = os.path.join(LIB, "candidate")
TRASH = os.path.join(LIB, "trash")
INDEX = os.path.join(WHALE, "index.json")
USED = os.path.join(paths.STATE_DIR, "whale_used.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 只用这些词搜（都是"鲸鱼娘/小鲸鱼"范畴），不许再带回暴走漫画
QUERIES = [
    "鲸鱼娘", "鲸鱼娘 表情包", "鲸鱼娘 可爱", "鲸鱼娘 插画",
    "小鲸鱼 表情包 可爱", "鲸鱼 表情包 可爱", "鲸鱼 拟人 少女",
    "くじら娘 イラスト", "whale girl cute sticker",
]

EMOTIONS = ["鲸鱼", "开心", "撒娇", "委屈", "小别扭", "困", "夸", "疑惑", "哭", "吃醋"]

# 情绪 -> 池子里优先挑的标签（挑不到就随便从池子里挑一张，反正都是鲸鱼）
PREF = {
    "鲸鱼": ["鲸鱼", "开心"], "开心": ["开心", "夸", "鲸鱼"], "撒娇": ["撒娇", "鲸鱼"],
    "委屈": ["委屈", "撒娇"], "小别扭": ["小别扭", "委屈"], "困": ["困", "鲸鱼"],
    "夸": ["夸", "开心"], "疑惑": ["疑惑", "鲸鱼"], "哭": ["委屈", "撒娇"],
    "吃醋": ["小别扭", "委屈"], "生气": ["小别扭", "委屈"],
}


# ────────────────────────── 图库 ──────────────────────────

def _index():
    d = paths.load_json(INDEX, None)
    if not isinstance(d, dict):
        d = {}
    return d


def _save_index(d):
    paths.ensure_dirs()
    paths.save_json(INDEX, d)


def pool(emo=None):
    """池子里能发的图：[{path, emo}]。"""
    idx = _index()
    out = []
    for name, meta in idx.items():
        path = os.path.join(WHALE, name)
        if not os.path.exists(path):
            continue
        if emo and meta.get("emo") != emo:
            continue
        out.append({"path": path, "emo": meta.get("emo"), "name": name})
    return out


def _used():
    d = paths.load_json(USED, {}) or {}
    return d if isinstance(d, dict) else {}


def _mark_used(path):
    d = _used()
    d[os.path.basename(path)] = time.time()
    if len(d) > 200:
        d = dict(sorted(d.items(), key=lambda kv: kv[1])[-200:])
    paths.save_json(USED, d)


def mark_sent(path):
    if path:
        _mark_used(path)


def pick(emotion=None, min_gap_min=240):
    """按情绪挑一张鲸鱼娘图；挑不到合适的就退而求其次，池子空就返回 None。"""
    emos = PREF.get(emotion) or ([emotion] if emotion else [])
    used = _used()
    now = time.time()
    for emo in emos + [None]:
        cands = pool(emo) if emo else pool()
        if not cands:
            continue
        fresh = [c for c in cands
                 if (now - used.get(c["name"], 0)) > min_gap_min * 60]
        chosen = random.choice(fresh or cands)
        _mark_used(chosen["path"])
        return chosen
    return None


def add(src, emo, convert=True):
    """把一张审过的图正式加进池子（webp 自动转 png）。"""
    if not os.path.exists(src):
        raise SystemExit(f"找不到图：{src}")
    raw = open(src, "rb").read()
    ext = os.path.splitext(src)[1].lower()
    if convert and (ext in (".webp", ".jpeg") or ext not in (".png", ".jpg", ".gif")):
        im = Image.open(io.BytesIO(raw)); im.load()
        buf = io.BytesIO(); im.convert("RGBA").save(buf, "PNG")
        raw, ext = buf.getvalue(), ".png"
    h = hashlib.sha1(raw).hexdigest()[:12]
    name = f"{emo}_{h}{ext}"
    os.makedirs(WHALE, exist_ok=True)
    paths.save_file(os.path.join(WHALE, name), raw)
    idx = _index()
    idx[name] = {"emo": emo, "added": time.time(), "src": os.path.basename(src)}
    _save_index(idx)
    return os.path.join(WHALE, name)


# ────────────────────────── 采集（只进候选） ──────────────────────────

def _get(url, referer=None, timeout=10):
    h = {"User-Agent": UA}
    if referer:
        h["Referer"] = referer
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        return r.read()


def search_urls(query, count=40):
    """Bing 图片搜索，返回图片直链。"""
    u = ("https://www.bing.com/images/async?q=" + urllib.parse.quote(query)
         + f"&first=0&count={count}&mmasync=1")
    html = _get(u, referer="https://www.bing.com/images/search?q=" + urllib.parse.quote(query)
                ).decode("utf-8", "ignore")
    urls = re.findall(r'murl&quot;:&quot;(.*?)&quot;', html) or re.findall(r'"murl":"(.*?)"', html)
    return [x.replace("&amp;", "&") for x in urls]


def _looks_bad(path):
    """粗筛：太小/太扁/纯色/带大段文字的截图。"""
    try:
        size = os.path.getsize(path)
        if size < 8_000 or size > 6_000_000:
            return True
        im = Image.open(path)
        im.load()
        w, h = im.size
        if w < 140 or h < 140:
            return True
        if max(w, h) / max(1, min(w, h)) > 2.2:
            return True
        from PIL import ImageStat
        stat = ImageStat.Stat(im.convert("L").resize((48, 48)))
        if stat.stddev[0] < 8:          # 纯色/近乎纯色
            return True
        return False
    except Exception:  # noqa: BLE001
        return True


def fetch(n=10, queries=None):
    """抓候选图（不会自动发送，等审）。"""
    os.makedirs(CAND, exist_ok=True)
    seen = {f.split(".")[0] for f in os.listdir(CAND)}
    got = []
    qs = list(queries or QUERIES)
    random.shuffle(qs)
    for q in qs:
        if len(got) >= n:
            break
        try:
            urls = search_urls(q)
        except Exception:  # noqa: BLE001
            continue
        random.shuffle(urls)
        for u in urls:
            if len(got) >= n:
                break
            try:
                data = _get(u, referer="https://www.bing.com/")
            except Exception:  # noqa: BLE001
                continue
            h = hashlib.sha1(data).hexdigest()[:16]
            if h in seen:
                continue
            ext = os.path.splitext(urllib.parse.urlparse(u).path)[1].lower() or ".png"
            if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                ext = ".png"
            tmp = os.path.join(CAND, h + ext)
            paths.save_file(tmp, data)
            if _looks_bad(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                continue
            seen.add(h)
            got.append({"path": tmp, "query": q})
    return got


def sheet(cols=6, cell=200):
    """把池子 + 候选图拼成一张审图，方便一眼看。"""
    from PIL import ImageDraw
    items = [(f"池·{c['emo']}", c["path"]) for c in pool()]
    if os.path.isdir(CAND):
        items += [("候选", os.path.join(CAND, f)) for f in sorted(os.listdir(CAND))[:60]
                  if os.path.splitext(f)[1].lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp")]
    if not items:
        return None
    rows = (len(items) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * cell, rows * cell), (248, 248, 248))
    d = ImageDraw.Draw(canvas)
    for i, (tag, f) in enumerate(items):
        try:
            im = Image.open(f).convert("RGBA")
            im.thumbnail((cell - 12, cell - 30))
            bg = Image.new("RGB", (cell - 12, cell - 30), (255, 255, 255))
            bg.paste(im, ((cell - 12 - im.width) // 2, (cell - 30 - im.height) // 2), im)
            x, y = (i % cols) * cell, (i // cols) * cell
            canvas.paste(bg, (x + 6, y + 24))
            d.text((x + 6, y + 6), f"{i:03d} {tag}", fill=(190, 0, 0))
        except Exception:  # noqa: BLE001
            continue
    out = os.path.join(paths.STATE_DIR, "whale_sheet.png")
    canvas.save(out)
    return out


def curate():
    """体检池子：坏图删掉、索引对齐、旧的沙雕图挪走。"""
    os.makedirs(WHALE, exist_ok=True)
    os.makedirs(TRASH, exist_ok=True)
    report = {"dropped": [], "archived": 0, "kept": 0}
    idx = _index()
    for name in list(idx):
        path = os.path.join(WHALE, name)
        if not os.path.exists(path) or _looks_bad(path):
            idx.pop(name, None)
            report["dropped"].append(name)
    _save_index(idx)
    # 池子以外、还在 library 根下的旧图（暴走漫画那种）全部归档
    for dp, _, fns in os.walk(LIB):
        if dp.startswith(WHALE) or dp.startswith(CAND) or dp.startswith(TRASH):
            continue
        for f in fns:
            if os.path.splitext(f)[1].lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                src = os.path.join(dp, f)
                try:
                    shutil.move(src, os.path.join(TRASH, f))
                    report["archived"] += 1
                except Exception:  # noqa: BLE001
                    pass
    report["kept"] = len(pool())
    return report


def stats():
    idx = _index()
    by_emo = {}
    for meta in idx.values():
        by_emo[meta.get("emo")] = by_emo.get(meta.get("emo"), 0) + 1
    return {"池子": len(idx), "分布": by_emo,
            "候选": len(os.listdir(CAND)) if os.path.isdir(CAND) else 0,
            "水位": os.path.join(WHALE, "index.json")}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "pick":
        emo = sys.argv[2] if len(sys.argv) > 2 else None
        p = pick(emo)
        print(json.dumps(p, ensure_ascii=False) if p else "None")
    elif cmd == "stats":
        print(json.dumps(stats(), ensure_ascii=False, indent=1))
    elif cmd == "sheet":
        print(sheet() or "没有图")
    elif cmd == "add" and len(sys.argv) > 3:
        print(add(sys.argv[2], sys.argv[3]))
    elif cmd == "fetch":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        print(json.dumps(fetch(n), ensure_ascii=False, indent=1))
    elif cmd == "search":
        q = sys.argv[2] if len(sys.argv) > 2 else "鲸鱼娘"
        for u in search_urls(q)[:20]:
            print(u)
    elif cmd == "curate":
        print(json.dumps(curate(), ensure_ascii=False, indent=1))
    else:
        raise SystemExit(__doc__)
