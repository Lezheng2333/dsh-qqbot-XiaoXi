#!/usr/bin/env python3
"""小汐守护进程 v3 — 多用户、可搬家、按人分区。

v3 相比 v2：
· 所有文件都在本文件夹里，整包搬走就能在别的电脑复活；
· 记忆/心情/额度/回复率按 QQ 用户分区（users/<openid>/），互不串味；
· 主动冒泡只发给"开了主动"的人（默认只有主人）；
· 工作区里的 AGENTS.md 只写说明书，不写任何人的私事。

  python3 daemon.py             # 常驻（launchd 用这个）
  python3 daemon.py --status
  python3 daemon.py --dry-run [--user 爸爸]
  python3 daemon.py --preview
  python3 daemon.py --once      # 真发一轮（测试用，会到对方 QQ）
  python3 daemon.py --doctor
"""
import datetime as dt
import json
import os
import random
import re
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import compose  # noqa: E402
import engagement  # noqa: E402
import memory  # noqa: E402
import messages  # noqa: E402
import mood  # noqa: E402
import notes  # noqa: E402
import paths  # noqa: E402
import people  # noqa: E402
import push  # noqa: E402
import stickers  # noqa: E402
import store  # noqa: E402
import transcripts  # noqa: E402
import tts  # noqa: E402
import world  # noqa: E402

CONFIG = paths.CONFIG
USED_LINES = os.path.join(paths.STATE_DIR, "used_lines.json")
QUEUE = os.path.join(paths.STATE_DIR, "queue.json")
MOOD_REQUEST = os.path.join(paths.WORKSPACE, "mood_request.json")
VERSION = "3.0"

DEFAULTS = {
    "daily_min": 6, "daily_max": 10,
    "gap_min": 40, "gap_max": 150,
    "window_mode": "auto", "fallback_window": [8, 24],
    "sticker_prob": 0.5, "split_prob": 0.3, "typing": True, "voice_prob": 0.08,
    "voice_name": "Flo (中文（中国大陆）)",
    "quiet_after_user_min": 20,
    "composed_prob": 0.05, "composed_daily_max": 1,
    "dedup_days": 7, "same_day_cooldown_min": 6, "sticker_cooldown_min": 300,
    "quota_floor": 3, "quota_cap": 14, "gap_floor": 20, "gap_cap": 240,
    "familiar_after_messages": 15,
}


def log(msg):
    store.log(msg)


def load(path, default):
    return paths.load_json(path, default)


def save(path, data):
    paths.save_json(path, data)


def cfg():
    c = dict(DEFAULTS)
    c.update(paths.config() or {})
    return c


def user_state_path(uid):
    return people.path(uid, "state.json")


# ────────────────────────── 话术去重（全局） ──────────────────────────

def _norm(text):
    return re.sub(r"[\s，。！？、…~～·（）()「」\"'—\-]+", "", text or "")


def used_lines(c=None):
    c = c or cfg()
    d = load(USED_LINES, {}) or {}
    if not isinstance(d, dict):
        d = {}
    cutoff = time.time() - c["dedup_days"] * 86400
    fresh = {k: v for k, v in d.items() if isinstance(v, (int, float)) and v >= cutoff}
    if len(fresh) != len(d):
        save(USED_LINES, fresh)
    return fresh


def remember_lines(lines):
    d = load(USED_LINES, {}) or {}
    now = time.time()
    for line in lines or []:
        if line:
            d[_norm(line)] = now
    if len(d) > 600:
        d = dict(sorted(d.items(), key=lambda kv: kv[1])[-600:])
    save(USED_LINES, d)


# ────────────────────────── 攒一轮 ──────────────────────────

def _familiar(uid):
    prof = people.get(uid) or {}
    if prof.get("relation") == "owner":
        return True
    return len(transcripts.user_messages(uid=uid)) >= cfg().get("familiar_after_messages", 15)


def build_plan(uid, c=None, w=None, now=None, force_sticker=False, rng=None):
    """给某个人拼出这一轮要发什么（不发送）。"""
    c = c or cfg()
    rng = rng or random
    now = now or dt.datetime.now()
    w = w or world.snapshot(now=now)

    metrics = engagement.refresh(uid)
    last_user = transcripts.last_user_ts(uid)
    recent = [m["text"] for m in transcripts.recent_texts(uid=uid, n=3)]
    familiar = _familiar(uid)
    m = mood.tick(uid, now=now, reply_rate=metrics["reply_rate"],
                  ignored_streak=metrics["ignored_streak"],
                  last_user_ts=last_user, recent_texts=recent,
                  familiar=familiar, rand=rng)
    m = dict(m, slot_bias=mood.bias_for(uid, m, familiar))

    msg = messages.compose(now=now, facts=memory.facts(uid, 6), quotes=memory.quotes(uid, 6)
                           + transcripts.recent_personal_items(uid, n=6),
                           mood=m, world=w, avoid=used_lines(c), rng=rng)

    plan = {"uid": uid, "texts": msg["texts"], "kinds": msg["kinds"],
            "sources": msg["sources"], "emotion": msg["emotion"],
            "mood": m["mood"], "mood_intensity": m["intensity"], "metrics": metrics,
            "world_hints": w["hints"], "at": now.timestamp(), "sticker": None, "voice": None}

    want_sticker = force_sticker or rng.random() < (
        c["sticker_prob"] + (0.06 if m["mood"] in ("黏人", "小别扭", "开心") else 0))
    if want_sticker:
        plan["sticker"] = {"emotion": plan["emotion"], "path": None, "source": "skip"}

    vp = c["voice_prob"] * (1.6 if m["mood"] in ("黏人", "困") else 1.0)
    if rng.random() < vp:
        line = next((t for t in plan["texts"]
                     if len(t) <= 26 and not any(ch in t for ch in "（「")), None)
        plan["voice"] = {"text": line or rng.choice(["爸爸抱抱", "想你了", "要早点睡哦"]),
                         "hint": m["voice"]}
    return plan


def _attach_sticker(plan, c, rng=None):
    rng = rng or random
    emo = plan["emotion"]
    path, source = stickers.pick(emo, prefer_local_min_age=c["sticker_cooldown_min"])
    if not path:
        path, source = compose.fresh(emo), "composed"
    if source != "composed" and rng.random() < c.get("composed_prob", 0.05):
        day = load(os.path.join(paths.STATE_DIR, "composed_day.json"), {}) or {}
        used_today = day.get("n", 0) if day.get("day") == dt.date.today().isoformat() else 0
        if used_today < c.get("composed_daily_max", 1):
            path, source = compose.fresh(emo), "composed"
    plan["sticker"] = {"emotion": emo, "path": path, "source": source}
    return plan


# ────────────────────────── 发送 ──────────────────────────

def _typing_seconds(texts):
    return max(3, min(9, 2 + sum(len(t) for t in texts) // 8))


def deliver(plan, c=None, tok=None):
    c = c or cfg()
    uid = plan.get("uid")
    tok = tok or push.token()
    if c["typing"]:
        push.typing(_typing_seconds(plan["texts"]), tok, uid)
        time.sleep(random.uniform(1.2, 2.6))
    for i, part in enumerate(plan["texts"]):
        if i:
            time.sleep(random.uniform(1.8, 4.5))
        push.send_text(part, tok, uid)

    sticker = plan.get("sticker")
    if sticker and sticker.get("path"):
        time.sleep(random.uniform(1.0, 2.2))
        try:
            push.send_image(sticker["path"], tok, uid)
            stickers.mark_sent(sticker["path"])
            if sticker.get("source") == "composed":
                f = os.path.join(paths.STATE_DIR, "composed_day.json")
                d = load(f, {}) or {}
                if d.get("day") != dt.date.today().isoformat():
                    d = {"day": dt.date.today().isoformat(), "n": 0}
                d["n"] = int(d.get("n", 0)) + 1
                save(f, d)
        except Exception as e:  # noqa: BLE001
            log(f"表情发送失败（文字已发）: {type(e).__name__}: {e}")

    voice = plan.get("voice")
    if voice:
        path = tts.speak(voice["text"], mood=plan["mood"])
        if path:
            time.sleep(0.8)
            try:
                push.send_voice(path, tok, uid)
            except Exception as e:  # noqa: BLE001
                log(f"语音发送失败: {type(e).__name__}: {e}")
        else:
            log("语音合成失败，跳过这一条语音")
    return True


def _finish_round(plan, c):
    uid = plan["uid"]
    remember_lines(plan.get("sources"))
    engagement.record_send(uid, plan["at"],
                           plan["sticker"]["emotion"] if plan.get("sticker") else None,
                           plan["mood"], plan["texts"])
    notes.append(uid, plan["texts"], emotion=(plan.get("sticker") or {}).get("emotion"),
                 mood=plan["mood"], kinds=plan.get("kinds"), ts=plan["at"])
    who = (people.get(uid) or {}).get("name") or uid[:6]
    sticker = plan.get("sticker") or {}
    rate = plan["metrics"]
    rate_s = "样本不足" if not rate.get("samples") else format(rate["reply_rate"], ".0%")
    log(f"已发送[{who}][{plan['mood']}] {' | '.join(plan['texts'])}"
        f" | 表情={os.path.basename(sticker['path']) if sticker.get('path') else '无'}"
        f"({sticker.get('source', '-')}) | 语音={'有' if plan.get('voice') else '无'}"
        f" | 回复率={rate_s}")


# ────────────────────────── 断网排队 ──────────────────────────

def queue_push(plan):
    q = load(QUEUE, []) or []
    q.append({"plan": plan, "attempts": 0})
    save(QUEUE, q[-5:])


def queue_flush(c=None):
    c = c or cfg()
    q = load(QUEUE, []) or []
    if not q:
        return 0
    keep, sent = [], 0
    for item in q:
        plan = item.get("plan") or {}
        age = time.time() - (plan.get("at") or 0)
        if age > 90 * 60 or item.get("attempts", 0) >= 3:
            log(f"排队消息过期丢弃（{age / 60:.0f} 分钟前）: {plan.get('texts')}")
            continue
        if sent:
            keep.append(item)
            continue
        try:
            plan["at"] = time.time()
            deliver(plan, c)
            _finish_round(plan, c)
            sent += 1
        except Exception as e:  # noqa: BLE001
            item["attempts"] = item.get("attempts", 0) + 1
            keep.append(item)
            log(f"补发失败（第 {item['attempts']} 次）: {type(e).__name__}: {e}")
            break
    save(QUEUE, keep)
    return sent


# ────────────────────────── 排程 ──────────────────────────

def _today():
    return dt.date.today().isoformat()


def _in_window(now, win):
    if win[0] <= win[1]:
        return win[0] <= now.hour < win[1]
    return now.hour >= win[0] or now.hour < win[1]


def _next_start(now, win):
    start = now.replace(hour=win[0] % 24, minute=random.randint(0, 20), second=0, microsecond=0)
    if win[0] < now.hour or (now.hour == win[0] and now.minute > 20):
        start += dt.timedelta(days=1)
    return start


def active_window(uid, c=None):
    c = c or cfg()
    if c["window_mode"] != "auto":
        return c["fallback_window"]
    return transcripts.active_window(uid=uid, fallback=tuple(c["fallback_window"]))


def next_gap_minutes(c, win, eff_quota, gap_factor):
    span_min = max(60, (win[1] - win[0]) * 60)
    avg = span_min / max(1, eff_quota)
    base = random.uniform(c["gap_min"], c["gap_max"]) * gap_factor
    return int(max(c["gap_floor"], min(c["gap_cap"], min(base, avg * 1.8))))


def effective_quota(st, c, qf):
    base = st.get("quota") or c["daily_min"]
    return int(max(c["quota_floor"], min(c["quota_cap"], round(base * qf))))


def proactive_users():
    return [uid for uid, rec in people.profiles().items() if rec.get("proactive")]


def send_round(uid, dry=False, force_sticker=False, now=None, c=None, w=None):
    c = c or cfg()
    plan = build_plan(uid, c, w=w, now=now, force_sticker=force_sticker)
    if dry:
        view = dict(plan)
        if view.get("sticker"):
            view["sticker"] = {"emotion": view["sticker"]["emotion"], "source": "待定（dry-run 不联网）"}
        print(json.dumps(view, ensure_ascii=False, indent=1))
        return plan
    if not plan["texts"]:
        log("这一轮没攒出话，跳过")
        return None
    if plan.get("sticker"):
        _attach_sticker(plan, c)
    try:
        deliver(plan, c)
    except Exception as e:  # noqa: BLE001
        log(f"发送失败，进排队: {type(e).__name__}: {e}")
        queue_push(plan)
        raise
    _finish_round(plan, c)
    return plan


# ────────────────────────── 对某个人跑一轮判断 ──────────────────────────

def tick_user(uid, c, w, now=None):
    """返回 "sent" / "wait" / "skip" 之一，内部负责落盘与日志。"""
    now = now or dt.datetime.now()
    st = load(user_state_path(uid), {})
    met = engagement.refresh(uid)
    qf, gf = met["quota_factor"], met["gap_factor"]

    if st.get("day") != _today():
        win0 = active_window(uid, c)
        base = random.randint(c["daily_min"], c["daily_max"])
        quota = int(max(c["quota_floor"], min(c["quota_cap"], round(base * met["quota_factor"]))))
        nxt = (now.timestamp() + random.randint(15, 45) * 60 if _in_window(now, win0)
               else _next_start(now, win0).timestamp())
        st = {"day": _today(), "sent": 0, "quota": quota, "base_quota": base, "next_at": nxt}
        save(user_state_path(uid), st)
        who = (people.get(uid) or {}).get("name") or uid[:6]
        log(f"[{who}] 新的一天：额度 {quota}（基础 {base} × {met['quota_factor']}），"
            f"时段 {win0[0]}:00-{win0[1]}:00，{met['reason']}")

    eff = effective_quota(st, c, qf)
    win = active_window(uid, c)
    brief = {"sent": st.get("sent", 0), "quota": st.get("quota"), "eff": eff,
             "window": win, "next_at": st.get("next_at")}

    if st.get("sent", 0) >= eff:
        return {"state": "skip", **brief}
    if not _in_window(now, win):
        st["next_at"] = _next_start(now, win).timestamp()
        save(user_state_path(uid), st)
        return {"state": "skip", **brief}

    nxt = st.get("next_at", 0)
    if now.timestamp() < nxt:
        return {"state": "wait", **brief}
    if now.timestamp() - nxt > 3 * 3600:
        st["next_at"] = time.time() + random.randint(15, 45) * 60
        save(user_state_path(uid), st)
        log("检测到长时间休眠，本次排程顺延")
        return {"state": "wait", **brief}

    last_user = transcripts.last_user_ts(uid)
    if last_user and (time.time() - last_user) < c["quiet_after_user_min"] * 60:
        st["next_at"] = time.time() + 1800
        save(user_state_path(uid), st)
        return {"state": "wait", **brief}

    try:
        plan = send_round(uid, c=c, w=w, now=now)
    except Exception as e:  # noqa: BLE001
        log(f"这一轮没发出去: {type(e).__name__}: {e}")
        st["next_at"] = time.time() + 600
        save(user_state_path(uid), st)
        return {"state": "wait", **brief}

    if not plan:
        st["next_at"] = time.time() + 900
        save(user_state_path(uid), st)
        return {"state": "wait", **brief}

    st["sent"] = int(st.get("sent", 0)) + 1
    st["last_sent"] = now.strftime("%m-%d %H:%M")
    st["last_plan"] = {"texts": plan["texts"], "mood": plan["mood"],
                       "emotion": plan["emotion"]}
    gap = next_gap_minutes(c, win, eff, gf)
    st["next_at"] = time.time() + gap * 60
    save(user_state_path(uid), st)
    log(f"下一轮 {gap} 分钟后（额度 {st['sent']}/{eff}，{met['reason']}）")
    return {"state": "sent", "sent": st["sent"], "eff": eff, "gap_min": gap}


# ────────────────────────── 聊天里写的心情纸条 ──────────────────────────

def _consume_mood_request():
    req = load(MOOD_REQUEST, None)
    if not isinstance(req, dict):
        return None
    want = req.get("mood")
    target = req.get("uid")
    try:
        os.remove(MOOD_REQUEST)
    except OSError:
        pass
    if want not in mood.MOODS:
        return None
    if not target:
        target = people.current()
    if not target:
        return None
    if (time.time() - (req.get("at") or 0)) > 3600:
        return None
    m = mood.force(target, want)
    log(f"按聊天里的纸条把对 {(people.get(target) or {}).get('name', target[:6])} 的心情拨到 {want}")
    return m


# ────────────────────────── 状态/自检 ──────────────────────────

def status():
    c = cfg()
    met_hb = store.read_heartbeat()
    alive = (time.time() - met_hb.get("beat_at", 0)) < 420
    rows = []
    for uid, rec in people.profiles().items():
        st = load(user_state_path(uid), {})
        eff = effective_quota(st, c, engagement.refresh(uid)["quota_factor"])
        win = active_window(uid, c)
        nxt = st.get("next_at")
        m = mood.snapshot(uid)
        met = engagement.refresh(uid)
        rows.append({
            "是谁": f"{rec.get('name')}（{rec.get('relation')}）",
            "uid": uid[:8] + "…",
            "主动": bool(rec.get("proactive")),
            "今天已发": st.get("sent", 0),
            "额度": st.get("quota"),
            "自适应额度": eff,
            "下次时间": dt.datetime.fromtimestamp(nxt).strftime("%m-%d %H:%M") if nxt else "—",
            "活跃时段": f"{win[0]}:00-{win[1]}:00",
            "上次发送": st.get("last_sent"),
            "心情": f"{m['mood']}（{m['intensity']}）",
            "回复率": f"{met['reply_rate']:.0%}（样本 {met['samples']}，连续未回 {met['ignored_streak']}）",
            "节奏": met["reason"],
        })
    print(json.dumps({
        "版本": VERSION,
        "core": paths.CORE,
        "守护进程": (f"活着（{met_hb.get('uptime_min', 0)} 分钟，pid {met_hb.get('pid')}，"
                     f"{met_hb.get('beats', 0)} 次心跳）") if alive else "没心跳（可能没在跑）",
        "用户": rows,
    }, ensure_ascii=False, indent=1))


def doctor():
    out = {"版本": VERSION, "core": paths.CORE, "问题": []}

    def check(name, fn):
        try:
            out[name] = fn()
        except Exception as e:  # noqa: BLE001
            out[name] = f"失败: {type(e).__name__}: {e}"
            out["问题"].append(name)

    check("zstd", lambda: transcripts.zstd_bin() or "缺")
    check("PIL", lambda: __import__("PIL").__version__)
    check("edge-tts", lambda: "可用" if __import__("edge_tts") else "缺")
    check("天气", lambda: (world.weather() or {}).get("desc") or "拿不到")
    check("节气算法", lambda: world.solar_term_time(2026, "冬至").strftime("%m-%d %H:%M"))
    check("图库", lambda: f"{len(stickers.library_files())} 张")
    check("会话目录", lambda: f"{len(transcripts.session_dirs())} 个")
    check("当前会话", lambda: (transcripts.current_session() or {}).get("uid") or "认不出")
    check("用户分区", lambda: f"{len(people.profiles())} 个")
    check("工作区", lambda: paths.WORKSPACE)
    check("说明书", lambda: "有" if os.path.exists(notes.AGENTS_MD) else "没有")
    check("QQ token", lambda: "能取到" if push.token() else "取不到")

    def _hb():
        hb = store.read_heartbeat()
        if not hb.get("beat_at"):
            return "还没有心跳（守护进程没跑过）"
        age = int(time.time() - hb["beat_at"])
        return (f"{age} 秒前（pid {hb.get('pid')}，已跑 {hb.get('uptime_min', 0)} 分钟）"
                if age < 420 else f"心跳停了 {age // 60} 分钟")
    check("心跳", _hb)
    print(json.dumps(out, ensure_ascii=False, indent=1))


# ────────────────────────── 主循环 ──────────────────────────

def loop():
    log(f"小汐守护进程启动 v{VERSION}（core={paths.CORE}，zstd={transcripts.zstd_bin() or '缺'}）")
    try:
        msgs = transcripts.user_messages()
        log(f"读到聊天记录：{len(msgs)} 条，{len(people.profiles())} 个用户分区")
    except Exception as e:  # noqa: BLE001
        log(f"读聊天记录失败: {type(e).__name__}: {e}")
    try:
        notes.sync_agents_md()
    except Exception:  # noqa: BLE001
        pass
    store.heartbeat(last_send=None, version=VERSION)

    while True:
        try:
            c = cfg()
            now = dt.datetime.now()

            _consume_mood_request()
            if os.path.exists(os.path.join(ROOT, "PAUSE")):
                time.sleep(120)
                continue

            w = world.snapshot(now=now)
            todos = proactive_users()

            if queue_flush(c):
                store.heartbeat(queue_flushed=time.time())

            brief = {}
            for uid in todos:
                try:
                    brief[uid] = tick_user(uid, c, w, now=now)
                except Exception as e:  # noqa: BLE001
                    log(f"[{uid[:6]}…] 这一轮异常: {type(e).__name__}: {e}")
                    brief[uid] = {"state": "error"}
            store.heartbeat(version=VERSION, users=brief)
        except Exception as e:  # noqa: BLE001
            log(f"循环异常: {type(e).__name__}: {e}")
            log(traceback.format_exc(limit=3))
        time.sleep(60)


# ────────────────────────── 命令行 ──────────────────────────

def _simulate(n, hour, uid):
    c = cfg()
    now = dt.datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0)
    seen = used_lines(c)
    for i in range(n):
        plan = messages.compose(now=now, facts=memory.facts(uid, 6),
                                quotes=memory.quotes(uid, 6),
                                mood=mood.snapshot(uid), world=world.snapshot(now=now),
                                avoid=seen)
        print(f"{i + 1:02d}. [{plan['emotion']}] " + " | ".join(plan["texts"]))
        for s in plan["sources"]:
            seen[_norm(s)] = time.time()
        now += dt.timedelta(minutes=random.randint(30, 120))


def preview(uid, now=None):
    c = cfg()
    now = now or dt.datetime.now()
    plan = build_plan(uid, c, now=now, force_sticker=True)
    _attach_sticker(plan, c)
    out = {"是谁": (people.get(uid) or {}).get("name"), "文字": plan["texts"],
           "心情": plan["mood"], "表情情绪": plan["emotion"],
           "表情图": plan["sticker"]["path"], "表情来源": plan["sticker"]["source"],
           "世界": plan["world_hints"], "回复率": plan["metrics"]["reply_rate"]}
    voice = plan.get("voice") or {"text": plan["texts"][0] if plan["texts"] else "爸爸抱抱",
                                  "hint": mood.snapshot(uid)["voice"]}
    path = tts.speak(voice["text"], mood=plan["mood"])
    out["语音"] = {"text": voice["text"], "path": path,
                   "seconds": tts.duration(path) if path else None, "参数": voice["hint"]}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    arg = args[0] if args else ""

    def opt(name, default=None):
        if name in args:
            i = args.index(name)
            if i + 1 < len(args):
                return args[i + 1]
        return default

    who = opt("--user")
    uid = people.resolve(who) if who else people.current()
    at_hour = opt("--at")
    when = dt.datetime.now().replace(hour=int(at_hour)) if at_hour else None

    if arg == "--once":
        send_round(uid, force_sticker=True)
    elif arg == "--dry-run":
        send_round(uid, dry=True, force_sticker="--sticker" in args, now=when)
    elif arg == "--preview":
        preview(uid, now=when)
    elif arg == "--simulate":
        _simulate(int(opt("--simulate", "6")), int(at_hour or dt.datetime.now().hour), uid)
    elif arg == "--status":
        status()
    elif arg == "--doctor":
        doctor()
    elif arg == "--queued":
        print(json.dumps(load(QUEUE, []), ensure_ascii=False, indent=1))
    else:
        loop()
