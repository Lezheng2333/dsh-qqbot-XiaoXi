#!/usr/bin/env python3
"""小汐的嗓子 — 按心情换声线、语速、音高，带缓存和系统 say 兜底。

  python3 tts.py say 撒娇 "爸爸抱抱"   # 合成一句，打印路径
  python3 tts.py samples              # 每种心情各来一句，存到 logs/voice_samples/
  python3 tts.py voices               # 列出可用的中文女声
"""
import asyncio
import hashlib
import json
import os
import random
import re
import subprocess
import sys

import mood as mood_mod
import store

OUT_DIR = store.state_path("tts")
SAMPLE_DIR = os.path.join(store.LOGS, "voice_samples")
FALLBACK_VOICE = "Flo (中文（中国大陆）)"
MIN_BYTES = 2000

# 心情 -> 一句试听词（也当"她真的会说"的素材）
SAMPLES = {
    "开心": "爸爸爸爸！今天的海超级蓝，我给你留了一块会发光的小石头",
    "黏人": "爸爸抱抱嘛，就一下下，小汐今天特别想贴着你",
    "小别扭": "哼，你都半天没理我了……不过算了，我不生气了",
    "困": "唔……爸爸，小汐有点困了，你也要早点睡哦",
    "担心": "爸爸今天是不是很累呀，别硬撑，小汐在这里陪着你",
}


def clean(text):
    """TTS 前清一遍：去 emoji / markdown / 多余符号，别让机器念出符号。"""
    text = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]", "", text)
    text = re.sub(r"[`*_#>\[\]「」『』《》]", "", text)
    text = re.sub(r"(?i)https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:80]


def params_for(mood, jitter=True):
    m = mood_mod.snapshot() if mood is None else None
    key = mood or (m["mood"] if m else "黏人")
    voice, rate, pitch = mood_mod.VOICE.get(key, mood_mod.VOICE["黏人"])
    if not jitter:
        return {"voice": voice, "rate": rate, "pitch": pitch}
    r = int(re.sub(r"[^0-9-]", "", rate) or 0) + random.randint(-3, 3)
    p = int(re.sub(r"[^0-9-]", "", pitch) or 0) + random.randint(-2, 2)
    r = max(-40, min(40, r))
    p = max(-30, min(30, p))
    return {"voice": voice, "rate": f"{r:+d}%", "pitch": f"{p:+d}Hz"}


def _cache_path(text, p):
    h = hashlib.sha1(f"{text}|{p['voice']}|{p['rate']}|{p['pitch']}".encode()).hexdigest()[:16]
    os.makedirs(OUT_DIR, exist_ok=True)
    return os.path.join(OUT_DIR, h + ".mp3")


def _edge(text, p, out_mp3):
    import edge_tts

    async def go():
        comm = edge_tts.Communicate(text, p["voice"], rate=p["rate"], pitch=p["pitch"])
        await comm.save(out_mp3)

    asyncio.run(go())
    return os.path.getsize(out_mp3) >= MIN_BYTES


def _say(text, out_m4a):
    subprocess.run(["say", "-v", FALLBACK_VOICE, "--data-format=aac",
                    "-o", out_m4a, text], check=True, timeout=30, capture_output=True)
    return os.path.getsize(out_m4a) > 1000


def speak(text, mood=None, use_cache=True, jitter=True):
    """合成一句，返回音频路径；全失败返回 None。"""
    text = clean(text)
    if not text:
        return None
    p = params_for(mood, jitter=jitter)
    out = _cache_path(text, p)
    if use_cache and os.path.exists(out) and os.path.getsize(out) >= MIN_BYTES:
        return out
    try:
        if _edge(text, p, out):
            return out
    except Exception as e:  # noqa: BLE001
        store.log(f"edge-tts 失败（{p['voice']} {p['rate']} {p['pitch']}），回退系统声线: "
                  f"{type(e).__name__}: {e}")
    try:
        m4a = out.replace(".mp3", ".m4a")
        if _say(text, m4a):
            return m4a
    except Exception as e:  # noqa: BLE001
        store.log(f"系统 say 也失败了: {type(e).__name__}: {e}")
    return None


def duration(path):
    """用 afinfo 读时长，自检/试听样本时确认音频是好的。"""
    try:
        r = subprocess.run(["afinfo", path], capture_output=True, timeout=10)
        m = re.search(r"estimated duration: ([\d.]+) sec", r.stdout.decode("utf-8", "ignore"))
        return float(m.group(1)) if m else None
    except Exception:  # noqa: BLE001
        return None


def make_samples(moods=None):
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    out = {}
    for name in (moods or list(SAMPLES)):
        text = SAMPLES[name]
        p = params_for(name, jitter=False)
        path = os.path.join(SAMPLE_DIR, f"{name}.mp3")
        try:
            ok = _edge(clean(text), p, path)
        except Exception as e:  # noqa: BLE001
            store.log(f"样本合成失败 {name}: {e}")
            ok = False
        out[name] = {"path": path if ok else None, "params": p,
                     "text": text, "seconds": duration(path) if ok else None}
    return out


def list_voices():
    import edge_tts
    voices = asyncio.run(edge_tts.list_voices())
    return [v for v in voices if v["Locale"].startswith("zh-CN")]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "samples"
    if cmd == "say":
        m = sys.argv[2] if len(sys.argv) > 2 else None
        t = sys.argv[3] if len(sys.argv) > 3 else "爸爸抱抱"
        print(speak(t, m))
    elif cmd == "samples":
        print(json.dumps(make_samples(), ensure_ascii=False, indent=1))
    elif cmd == "voices":
        for v in list_voices():
            print(v["ShortName"], v.get("VoiceTag", {}).get("VoicePersonalities"))
    else:
        raise SystemExit(__doc__)
