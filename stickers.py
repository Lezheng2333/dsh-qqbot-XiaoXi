#!/usr/bin/env python3
"""小汐的表情包 — 实时抓图 + 本地情绪标签库 + 质量过滤。

来源：斗图啦（主）、发表情（备）。只用一个受控的中文关键词表，
不用用户输入当搜索词，避免搜出奇怪的东西。

每张图抓到就打上情绪标签（state/sticker_tags.json），下次同情绪优先
用本地已经验过的好图，抓不到才不会瞎配。

  python3 stickers.py fetch 撒娇     # 抓一张，打印路径
  python3 stickers.py batch 5        # 抓 5 张存库
  python3 stickers.py pick 撒娇      # 按情绪挑一张（本地优先）
  python3 stickers.py curate         # 体检 + 去重 + 生成 REVIEW.md
"""
import hashlib
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request

import paths
import store

ROOT = store.ROOT
LIB = os.path.join(ROOT, "library")
COMPOSED = os.path.join(LIB, "composed")
TAGS = store.state_path("sticker_tags.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 情绪 -> 搜索词（鲸鱼娘 / 鲸鱼 / 情绪类）。只做加法，不动别人在用的名字。
EMOTIONS = {
    "鲸鱼": ["鲸鱼", "鲸鱼娘", "小鲸鱼", "鲸"],
    "开心": ["开心", "高兴", "开心鲸鱼", "快乐"],
    "撒娇": ["撒娇", "贴贴", "要抱抱", "么么哒"],
    "委屈": ["委屈", "可怜", "qwq", "欺负"],
    "生气": ["生气", "哼", "气鼓鼓", "凶"],
    "困": ["困", "睡觉", "晚安", "困困"],
    "吃醋": ["吃醋", "嫉妒", "生气吃醋"],
    "哭": ["哭", "大哭", "眼泪"],
    "夸": ["夸我", "棒", "厉害", "点赞"],
    "疑惑": ["问号", "疑惑", "歪头", "什么"],
}
ALL_KEYWORDS = [k for v in EMOTIONS.values() for k in v]
# 每种情绪的"拒收词"：搜出来带这些词义的图，情绪不对就别用
NEGATIVE_WORDS = ("恐怖", "吓人", "恶心", "血", "死", "杀", "色情", "裸")


def _get(url, referer=None, timeout=20):
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def search_doutula(keyword):
    url = "https://www.doutula.com/search?keyword=" + urllib.parse.quote(keyword)
    try:
        html = _get(url).decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return []
    urls = re.findall(r'data-original="(https?://[^"]+\.(?:gif|png|jpe?g|webp))"', html, re.I)
    urls += re.findall(r'data-backup="(https?://[^"]+\.(?:gif|png|jpe?g|webp))"', html, re.I)
    return list(dict.fromkeys(urls))


def search_fabiaoqing(keyword):
    url = f"https://www.fabiaoqing.com/search/bqb/keyword/{urllib.parse.quote(keyword)}/type/bqb.html"
    try:
        html = _get(url).decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return []
    urls = re.findall(r'<img[^>]+data-original="(//[^"]+\.(?:gif|png|jpe?g))"', html, re.I)
    return ["https:" + u if u.startswith("//") else u for u in dict.fromkeys(urls)]


# ────────────────────────── 标签库 ──────────────────────────

def load_tags():
    d = store.load_json(TAGS, None)
    if not isinstance(d, dict):
        d = {}
    d.setdefault("items", {})
    d.setdefault("sent", {})
    return d


def save_tags(d):
    store.save_json(TAGS, d)


def tag(path, emo, kw=None):
    d = load_tags()
    d["items"][path] = {"emo": emo, "kw": kw, "ts": time.time(),
                        "hash": _file_hash(path)}
    save_tags(d)


def mark_sent(path):
    d = load_tags()
    d["sent"][path] = time.time()
    # 只留最近 300 条
    if len(d["sent"]) > 300:
        keep = sorted(d["sent"].items(), key=lambda kv: kv[1])[-300:]
        d["sent"] = dict(keep)
    save_tags(d)


def _file_hash(path):
    try:
        h = hashlib.sha1()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:16]
    except OSError:
        return None


def tagged(emo=None, max_age_days=60):
    d = load_tags()
    now = time.time()
    out = []
    for path, meta in d["items"].items():
        if not os.path.exists(path):
            continue
        if emo and meta.get("emo") != emo:
            continue
        if max_age_days and now - meta.get("ts", 0) > max_age_days * 86400:
            continue
        out.append((path, meta))
    return out


def pick_local(emo, minutes_avoid=0):
    """按情绪挑一张本地图：优先没用过的、没发过的。"""
    d = load_tags()
    sent = d.get("sent", {})
    cands = []
    for path, meta in tagged(emo):
        last = sent.get(path, 0)
        if minutes_avoid and (time.time() - last) < minutes_avoid * 60:
            continue
        cands.append((last, path))
    if not cands:
        return None
    cands.sort()
    # 最久没发过的那批里随机挑一张，别总是同一张
    oldest = cands[:max(1, len(cands) // 2)]
    return random.choice(oldest)[1]


# ────────────────────────── 质量过滤 ──────────────────────────

def _valid(path):
    """尺寸/比例/体积/内容过滤，坏图直接丢。"""
    try:
        from PIL import Image, ImageStat
        size = os.path.getsize(path)
        if size < 8_000 or size > 6_000_000:
            return False
        im = Image.open(path)
        im.load()
        w, h = im.size
        if w < 120 or h < 120:
            return False
        ratio = max(w, h) / max(1, min(w, h))
        if ratio > 2.6:
            return False
        # 几乎纯色的图（白底截图/空白）没意思
        gray = im.convert("L").resize((64, 64))
        stat = ImageStat.Stat(gray)
        if stat.stddev[0] < 6:
            return False
        return True
    except Exception:  # noqa: BLE001
        return False


def _save(data, url, emo=None):
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower() or ".png"
    if ext == ".jpeg":
        ext = ".jpg"
    h = hashlib.sha1(data).hexdigest()[:16]
    sub = os.path.join(LIB, h[:2])
    os.makedirs(sub, exist_ok=True)
    path = os.path.join(sub, h + ext)
    paths.save_file(path, data)             # 沙箱不让写就进信箱，后台代写
    # QQ 对 webp 不友好，转成 png 再入库
    if ext == ".webp":
        try:
            import io
            from PIL import Image
            png = os.path.join(sub, h + ".png")
            buf = io.BytesIO()
            Image.open(path).convert("RGBA").save(buf, format="PNG")
            paths.save_file(png, buf.getvalue())
            os.remove(path)
            path = png
        except Exception:  # noqa: BLE001
            pass
    if emo:
        tag(path, emo, url)
    return path


def _recent_urls():
    """用文件名 hash 近似"抓过哪些"，避免同图重复下载。"""
    return {os.path.splitext(f)[0] for f in os.listdir(LIB)} if os.path.isdir(LIB) else set()


def fetch_one(emotion=None, tries=3):
    """抓一张可用的表情，返回 (路径, 关键词)。失败返回 (None, None)。"""
    keywords = EMOTIONS.get(emotion, ALL_KEYWORDS) if emotion else ALL_KEYWORDS
    keywords = random.sample(keywords, len(keywords))
    seen = set()
    for dp, _, fns in os.walk(LIB):
        for f in fns:
            seen.add(os.path.splitext(f)[0])
    for kw in keywords[:tries]:
        if any(bad in kw for bad in NEGATIVE_WORDS):
            continue
        urls = search_doutula(kw)
        if len(urls) < 3:
            urls += search_fabiaoqing(kw)
        random.shuffle(urls)
        for url in urls[:10]:
            key = hashlib.sha1(url.encode()).hexdigest()[:16]
            if key in seen:
                continue
            try:
                data = _get(url, referer="https://www.doutula.com/")
            except Exception:  # noqa: BLE001
                continue
            if len(data) < 8_000:
                continue
            content_hash = hashlib.sha1(data).hexdigest()[:16]
            if content_hash in seen:
                continue
            path = _save(data, url, emotion)
            if not _valid(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
                d = load_tags()
                d["items"].pop(path, None)
                save_tags(d)
                continue
            seen.add(key)
            seen.add(content_hash)
            return path, kw
    return None, None


def library_files():
    out = []
    for dp, _, fn in os.walk(LIB):
        for f in fn:
            if os.path.splitext(f)[1].lower() in (".png", ".gif", ".jpg", ".webp"):
                out.append(os.path.join(dp, f))
    return out


def fetch_local_any():
    files = library_files()
    return random.choice(files) if files else None


# ────────────────────────── 策展 ──────────────────────────

def curate(delete_bad=True):
    """体检图库：坏图删掉、重复的只留一张、给老图补标签。"""
    files = library_files()
    d = load_tags()
    report = {"total": len(files), "removed_bad": [], "removed_dup": [],
              "tagged": 0, "kept": 0}
    hashes = {}
    for path in files:
        if not _valid(path):
            if delete_bad:
                try:
                    os.remove(path)
                except OSError:
                    pass
                d["items"].pop(path, None)
                report["removed_bad"].append(os.path.basename(path))
                continue
        h = _file_hash(path)
        if h in hashes:
            if delete_bad:
                try:
                    os.remove(path)
                except OSError:
                    pass
                d["items"].pop(path, None)
                report["removed_dup"].append(os.path.basename(path))
                continue
        hashes[h] = path
        if path not in d["items"]:
            emo = None
            base = os.path.basename(path)
            for name in EMOTIONS:
                if base.startswith(name):
                    emo = name
                    break
            if emo:
                d["items"][path] = {"emo": emo, "kw": "composed", "ts": time.time(), "hash": h}
                report["tagged"] += 1
        report["kept"] += 1
    save_tags(d)
    _write_review()
    return report


def _write_review():
    d = load_tags()
    lines = ["# 表情包图库体检单", "", f"生成时间：{time.strftime('%Y-%m-%d %H:%M')}",
             "", "想删掉哪张，直接把文件删了就行（路径在下面）。", ""]
    by_emo = {}
    for path, meta in d["items"].items():
        by_emo.setdefault(meta.get("emo") or "未分类", []).append(path)
    for emo in sorted(by_emo):
        lines.append(f"## {emo}（{len(by_emo[emo])} 张）")
        for p in sorted(by_emo[emo]):
            lines.append(f"- `{p}`")
        lines.append("")
    untagged = [p for p in library_files() if p not in d["items"]]
    if untagged:
        lines.append(f"## 未打标签（{len(untagged)} 张）")
        lines += [f"- `{p}`" for p in untagged]
    try:
        with open(os.path.join(LIB, "REVIEW.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass


def pick(emotion, prefer_local_min_age=180):
    """发图主入口：本地标签库优先，其次实时抓，最后兜底。"""
    path = pick_local(emotion, minutes_avoid=prefer_local_min_age)
    if path and random.random() < 0.45:
        return path, "local"
    path, kw = fetch_one(emotion)
    if path:
        return path, "live"
    path = pick_local(emotion) or pick_local(None) or fetch_local_any()
    return path, "fallback"


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    if cmd == "fetch":
        emo = sys.argv[2] if len(sys.argv) > 2 else None
        p, kw = fetch_one(emo)
        print(json.dumps({"path": p, "keyword": kw}, ensure_ascii=False))
    elif cmd == "batch":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        got = []
        for _ in range(n):
            p, kw = fetch_one()
            if p:
                got.append({"path": p, "keyword": kw})
        print(json.dumps(got, ensure_ascii=False, indent=1))
    elif cmd == "pick":
        emo = sys.argv[2] if len(sys.argv) > 2 else "撒娇"
        print(json.dumps(pick(emo), ensure_ascii=False))
    elif cmd == "curate":
        print(json.dumps(curate(), ensure_ascii=False, indent=1))
    else:
        raise SystemExit(__doc__)
