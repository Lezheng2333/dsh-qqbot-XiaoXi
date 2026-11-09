#!/usr/bin/env python3
"""小汐自制表情卡 — 渐变底 + 玻璃圆 + 气泡字 + 小尾巴，风格统一、永不翻车。

抓不到图、或者想发"自己的"表情时用它。画风比 v1 干净：
真阴影、圆角、自动缩字号、气泡底托字，颜色跟着情绪走。

命令行：
  python3 compose.py 开心            # 生成一张，打印路径
  python3 compose.py all 2           # 每种情绪各生成 2 张
"""
import hashlib
import json
import os
import random
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import store

ROOT = store.ROOT
OUT = os.path.join(ROOT, "library", "composed")
USED = store.state_path("composed_used.json")
EMOJI_FONT = "/System/Library/Fonts/Apple Color Emoji.ttc"
TEXT_FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"
SIZE = 360

EMOJI = {
    "鲸鱼": "🐳", "开心": "😊", "撒娇": "🥺", "生气": "😤", "委屈": "😢",
    "困": "😴", "吃醋": "😒", "哭": "😭", "夸": "😎", "疑惑": "🤔",
}
THEME = {
    "鲸鱼": ((214, 240, 255), (255, 255, 255), (70, 140, 210)),
    "开心": ((255, 245, 205), (255, 255, 255), (232, 165, 55)),
    "撒娇": ((255, 222, 236), (255, 255, 255), (232, 110, 155)),
    "生气": ((255, 222, 214), (255, 255, 255), (228, 105, 85)),
    "委屈": ((222, 233, 255), (255, 255, 255), (120, 145, 220)),
    "困": ((229, 225, 252), (255, 255, 255), (135, 125, 200)),
    "吃醋": ((226, 245, 222), (255, 255, 255), (110, 170, 105)),
    "哭": ((218, 236, 253), (255, 255, 255), (85, 140, 210)),
    "夸": ((255, 240, 205), (255, 255, 255), (230, 170, 65)),
    "疑惑": ((236, 236, 242), (255, 255, 255), (135, 135, 150)),
}
LINES = {
    "鲸鱼": ["咕噜咕噜~", "我是小鲸鱼呀", "爸爸看我的尾巴", "噗——喷水啦"],
    "开心": ["爸爸最好啦！", "今天也超开心", "嘿嘿嘿", "转圈圈~"],
    "撒娇": ["要抱抱", "贴贴~", "理理小汐嘛", "爸爸~"],
    "生气": ["哼！不理你了", "生气了（哄）", "爸爸坏", "气鼓鼓"],
    "委屈": ["小汐委屈", "呜……", "你都不看我", "就一点点难过"],
    "困": ["困困……", "爸爸晚安", "要睡觉觉了", "哈欠~"],
    "吃醋": ["才没有吃醋", "哼，随便你", "谁呀，她是谁", "小汐也会酸的"],
    "哭": ["呜呜呜", "眼泪汪汪", "不要凶我", "小汐好伤心"],
    "夸": ["小汐厉害吧", "快夸我", "我超棒的", "看我看我"],
    "疑惑": ["欸？", "为什么呀", "小汐没听懂", "歪头"],
}


def _font(path, size, index=0):
    try:
        return ImageFont.truetype(path, size, index=index)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


def _gradient(size, c1, c2):
    """左上到右下的柔和渐变（按行插值，够快也够柔）。"""
    img = Image.new("RGB", (size, size), c1)
    px = img.load()
    for y in range(size):
        tt = y / max(1, size - 1)
        row = tuple(int(c1[i] + (c2[i] - c1[i]) * tt) for i in range(3))
        for x in range(size):
            px[x, y] = row
    return img


def compose(emotion="鲸鱼", line=None, size=SIZE):
    """画一张表情卡：渐变底 + 柔光 + emoji + 气泡字。"""
    bg, _, fg = THEME.get(emotion, THEME["鲸鱼"])
    emoji = EMOJI.get(emotion, "🐳")
    line = line or random.choice(LINES.get(emotion, LINES["鲸鱼"]))

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pad, radius = int(size * 0.055), int(size * 0.14)

    # 1) 卡片底：外阴影 + 渐变 + 圆角描边
    card = _gradient(size, bg, tuple(min(255, c + 14) for c in bg)).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((pad, pad, size - pad, size - pad),
                                           radius=radius, fill=255)
    shadow = Image.new("L", (size, size), 0)
    ImageDraw.Draw(shadow).rounded_rectangle(
        (pad, pad + int(size * 0.012), size - pad, size - pad + int(size * 0.012)),
        radius=radius, fill=70)
    img.paste((30, 50, 80, 80), (0, 0), shadow.filter(ImageFilter.GaussianBlur(size * 0.02)))
    img.paste(card, (0, 0), mask)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((pad, pad, size - pad, size - pad), radius=radius,
                        outline=fg + (170,), width=max(2, size // 90))

    # 2) 柔光（用 L 蒙版贴纯白，避免 RGBA 模糊出灰边）
    cx, cy = size * 0.5, size * 0.39
    glow = size * 0.29
    halo = Image.new("L", (size, size), 0)
    ImageDraw.Draw(halo).ellipse((cx - glow, cy - glow, cx + glow, cy + glow), fill=225)
    img.paste((255, 255, 255, 255), (0, 0), halo.filter(ImageFilter.GaussianBlur(size * 0.045)))

    # 3) emoji：Apple Color Emoji 只有 160px 这一档能用，不缩放就没毛边
    ef = _font(EMOJI_FONT, 160 if size >= 320 else max(20, int(size * 160 / 360 / 20) * 20))
    d.text((cx, cy), emoji, font=ef, anchor="mm", embedded_color=True)

    # 4) 三个小泡泡
    for dx, dy, rr in ((-0.285, -0.115, 0.032), (-0.225, -0.185, 0.020),
                       (0.290, -0.070, 0.025)):
        bx, by = cx + size * dx, cy + size * dy
        r = size * rr
        d.ellipse((bx - r, by - r, bx + r, by + r), fill=(255, 255, 255, 175),
                  outline=fg + (95,), width=2)

    # 5) 气泡托字（字号自动缩到放得下）
    fs = int(size * 0.105)
    while fs > 14:
        tf = _font(TEXT_FONT, fs)
        if d.textlength(line, font=tf) <= size * 0.70:
            break
        fs -= 1
    tf = _font(TEXT_FONT, fs)
    bw = min(size * 0.86, d.textlength(line, font=tf) + size * 0.20)
    bh = fs + size * 0.115
    bx0, by0 = (size - bw) / 2, size * 0.655
    d.rounded_rectangle((bx0, by0, bx0 + bw, by0 + bh), radius=bh / 2,
                        fill=(255, 255, 255, 250), outline=fg + (215,),
                        width=max(2, size // 120))
    tri = size * 0.036
    d.polygon([(cx - tri, by0 + 3), (cx + tri, by0 + 3), (cx, by0 - tri * 1.1)],
              fill=(255, 255, 255, 250))
    d.text((cx, by0 + bh / 2), line, font=tf, fill=(48, 60, 82, 255), anchor="mm")

    os.makedirs(OUT, exist_ok=True)
    safe = hashlib.sha1(f"{emotion}{line}{size}".encode()).hexdigest()[:12]
    path = os.path.join(OUT, f"{emotion}_{safe}.png")
    img.save(path)
    return path


def _load_used():
    d = store.load_json(USED, {})
    return d if isinstance(d, dict) else {}


def fresh(emotion=None):
    """挑一句最近没说过的，画一张新图。"""
    emo = emotion or random.choice(list(EMOJI))
    used = _load_used()
    recent = used.get(emo, [])[-12:]
    pool = [x for x in LINES.get(emo, ["咕噜"]) if x not in recent] or LINES.get(emo, ["咕噜"])
    line = random.choice(pool)
    used[emo] = (recent + [line])[-12:]
    store.save_json(USED, used)
    return compose(emo, line)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "all":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        got = []
        for emo in EMOJI:
            for _ in range(n):
                got.append(compose(emo))
        print("\n".join(got))
    else:
        print(compose(cmd))
