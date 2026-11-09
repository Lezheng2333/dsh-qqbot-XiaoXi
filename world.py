#!/usr/bin/env python3
"""小汐的"窗外" — 天气、节气、节日、星期几。

天气走 open-meteo（免费、不用 key），结果缓存 20 分钟，断网就用旧数据
并标记 stale；节日/节气是本地算的，不依赖网络。

  python3 world.py          # 看现在外面的世界
  python3 world.py --fresh  # 强制刷新天气
"""
import datetime as dt
import json
import math
import sys
import time
import urllib.parse
import urllib.request

import store

ROOT = store.ROOT
CONFIG = ROOT + "/config.json"
CACHE = store.state_path("world.json")
CACHE_TTL = 20 * 60
STALE_OK = 6 * 3600
TZ_HOURS = 8  # Asia/Shanghai，固定 +8，中国没有夏令时

DEFAULTS = {"city": "成都", "lat": 30.5728, "lon": 104.0668, "weather": True}

WMO = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴",
    45: "有雾", 48: "雾凇",
    51: "毛毛雨", 53: "小雨", 55: "中雨",
    56: "冻雨", 57: "冻雨", 61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "冻雨", 71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "阵雨", 82: "暴雨", 85: "阵雪", 86: "阵雪",
    95: "雷阵雨", 96: "雷暴", 99: "雷暴冰雹",
}

# ────────────────────────── 节日 ──────────────────────────
# 农历节日来自公开万年历逐年对照表（2026-2027），公历节日固定；
# 母亲节/父亲节按"5 月第 2 个周日 / 6 月第 3 个周日"算。
# 节气用天文算法算（见 solar_term），不写死。
LUNAR = [
    # (公历日期, 节日) —— 农历节日逐年对照表，2026-2028 够用了；
    # 除夕已按"春节前一天"核对（2024-2028 连续五年没有年三十）
    ((2026, 2, 16), "除夕"), ((2026, 2, 17), "春节"), ((2026, 3, 3), "元宵"),
    ((2026, 6, 19), "端午"), ((2026, 8, 19), "七夕"), ((2026, 9, 25), "中秋"),
    ((2026, 10, 18), "重阳"),
    ((2027, 2, 5), "除夕"), ((2027, 2, 6), "春节"), ((2027, 2, 20), "元宵"),
    ((2027, 6, 9), "端午"), ((2027, 8, 8), "七夕"), ((2027, 9, 15), "中秋"),
    ((2027, 10, 8), "重阳"),
    ((2028, 1, 25), "除夕"), ((2028, 1, 26), "春节"), ((2028, 2, 9), "元宵"),
    ((2028, 5, 28), "端午"), ((2028, 8, 26), "七夕"), ((2028, 10, 3), "中秋"),
    ((2028, 10, 26), "重阳"),
]
FIXED = [(1, 1, "元旦"), (2, 14, "情人节"), (3, 8, "妇女节"),
         (5, 1, "劳动节"), (6, 1, "儿童节"), (10, 1, "国庆节"),
         (12, 24, "平安夜"), (12, 25, "圣诞")]
SOLAR_TERMS = ["春分", "清明", "谷雨", "立夏", "小满", "芒种", "夏至", "小暑",
               "大暑", "立秋", "处暑", "白露", "秋分", "寒露", "霜降", "立冬",
               "小雪", "大雪", "冬至", "小寒", "大寒", "立春", "雨水", "惊蛰"]
# 立春 315° 起，每 15° 一个节气
TERM_LON = {"立春": 315, "雨水": 330, "惊蛰": 345, "春分": 0, "清明": 15,
            "谷雨": 30, "立夏": 45, "小满": 60, "芒种": 75, "夏至": 90,
            "小暑": 105, "大暑": 120, "立秋": 135, "处暑": 150, "白露": 165,
            "秋分": 180, "寒露": 195, "霜降": 210, "立冬": 225, "小雪": 240,
            "大雪": 255, "冬至": 270, "小寒": 285, "大寒": 300}


def _cfg():
    c = dict(DEFAULTS)
    c.update(store.load_json(CONFIG, {}) or {})
    return c


def _jd_from_dt(local_dt):
    """北京时间的 naive datetime -> UT 儒略日。"""
    utc = local_dt - dt.timedelta(hours=TZ_HOURS)
    epoch = dt.datetime(1970, 1, 1)
    return (utc - epoch).total_seconds() / 86400.0 + 2440587.5


def _dt_from_jd(jd):
    unix = (jd - 2440587.5) * 86400.0
    return dt.datetime(1970, 1, 1) + dt.timedelta(seconds=unix + TZ_HOURS * 3600)


def sun_longitude(jd):
    """Meeus 低精度太阳视黄经（度）。误差约 0.01°，够定节气日期。"""
    t = (jd - 2451545.0) / 36525.0
    l0 = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    m = math.radians(357.52911 + 35999.05029 * t - 0.0001537 * t * t)
    c = ((1.914602 - 0.004817 * t - 0.000014 * t * t) * math.sin(m)
         + (0.019993 - 0.000101 * t) * math.sin(2 * m)
         + 0.000289 * math.sin(3 * m))
    omega = math.radians(125.04 - 1934.136 * t)
    app = l0 + c - 0.00569 - 0.00478 * math.sin(omega)
    return app % 360.0


def solar_term_time(year, name):
    """返回该年第 name 个节气（北京时间）的 datetime。"""
    target = TERM_LON[name]
    jd = _jd_from_dt(dt.datetime(year, 1, 1))
    end = _jd_from_dt(dt.datetime(year + 1, 1, 2))
    prev = None
    while jd < end:
        diff = (sun_longitude(jd) - target + 180.0) % 360.0 - 180.0
        if prev is not None and prev[1] < 0 <= diff:
            lo, hi = prev[0], jd
            for _ in range(40):
                mid = (lo + hi) / 2
                d = (sun_longitude(mid) - target + 180.0) % 360.0 - 180.0
                if d < 0:
                    lo = mid
                else:
                    hi = mid
            return _dt_from_jd((lo + hi) / 2)
        prev = (jd, diff)
        jd += 1.0
    return None


def solar_terms(year):
    return {name: solar_term_time(year, name) for name in SOLAR_TERMS}


_TERM_CACHE = {}


def terms_of(year):
    if year not in _TERM_CACHE:
        _TERM_CACHE[year] = {k: v for k, v in solar_terms(year).items() if v}
    return _TERM_CACHE[year]


def _nth_weekday(year, month, weekday, n):
    d = dt.date(year, month, 1)
    while d.weekday() != weekday:
        d += dt.timedelta(days=1)
    return d + dt.timedelta(days=7 * (n - 1))


def festivals(year):
    """返回 [(date, 名字)]，含农历、固定公历、母亲节父亲节、节气。"""
    out = []
    for m, d, name in FIXED:
        out.append((dt.date(year, m, d), name))
    for (y, m, d), name in LUNAR:
        if y == year:
            out.append((dt.date(y, m, d), name))
    out.append((_nth_weekday(year, 5, 6, 2), "母亲节"))
    out.append((_nth_weekday(year, 6, 6, 3), "父亲节"))
    for name, when in terms_of(year).items():
        out.append((when.date(), name))
    return sorted(set(out))


def next_festival(today=None, within=10, skip_terms=False):
    """最近的节日：今天/还有几天。返回 dict 或 None。"""
    today = today or dt.date.today()
    cands = []
    for y in (today.year, today.year + 1):
        cands += festivals(y)
    best = None
    for d, name in sorted(cands):
        days = (d - today).days
        if days < 0:
            continue
        if skip_terms and name in TERM_LON:
            continue
        if days <= within:
            best = {"name": name, "days": days, "date": d.isoformat(),
                    "is_term": name in TERM_LON}
            break
    return best


def today_term(today=None):
    today = today or dt.date.today()
    for name, when in terms_of(today.year).items():
        if when.date() == today:
            return name
    return None


# ────────────────────────── 天气 ──────────────────────────

def _fetch_weather(c):
    q = urllib.parse.urlencode({
        "latitude": c["lat"], "longitude": c["lon"],
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,is_day",
        "daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max",
        "hourly": "temperature_2m,weather_code,precipitation_probability",
        "timezone": "Asia/Shanghai", "forecast_days": 2, "past_days": 1,
    })
    url = "https://api.open-meteo.com/v1/forecast?" + q
    req = urllib.request.Request(url, headers={"User-Agent": "xiaoxi/1.0"})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode())


def _rain_soon(data, now=None):
    now = now or dt.datetime.now()
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    probs = hourly.get("precipitation_probability") or []
    best = 0
    for t, p in zip(times, probs):
        try:
            h = dt.datetime.fromisoformat(t)
        except Exception:  # noqa: BLE001
            continue
        if 0 <= (h - now).total_seconds() <= 6 * 3600:
            best = max(best, p or 0)
    return best


def _normalize(data, city):
    cur = data.get("current") or {}
    daily = data.get("daily") or {}
    tmax = (daily.get("temperature_2m_max") or [None, None])
    tmin = (daily.get("temperature_2m_min") or [None, None])
    code = cur.get("weather_code", 0)
    today_max = tmax[1] if len(tmax) > 1 else None
    yday_max = tmax[0] if tmax else None
    drop = round(yday_max - today_max, 1) if (today_max is not None and yday_max is not None) else 0.0
    return {
        "city": city,
        "temp": cur.get("temperature_2m"),
        "feels": cur.get("apparent_temperature"),
        "humidity": cur.get("relative_humidity_2m"),
        "code": code,
        "desc": WMO.get(code, "说不清的天"),
        "is_day": bool(cur.get("is_day", 1)),
        "tmax": today_max,
        "tmin": tmin[1] if len(tmin) > 1 else None,
        "tmax_tomorrow": tmax[2] if len(tmax) > 2 else None,
        "drop": drop,
        "rain_soon": _rain_soon(data),
        "rain_today": (daily.get("precipitation_probability_max") or [None, None])[1],
        "at": time.time(),
    }


def weather(force=False):
    """天气快照。优先缓存；网络挂了就用旧数据（最多认 6 小时）。"""
    c = _cfg()
    if not c.get("weather", True):
        return None
    cache = store.load_json(CACHE, {}) or {}
    w = cache.get("weather")
    if w and not force and time.time() - w.get("at", 0) < CACHE_TTL:
        return w
    try:
        data = _fetch_weather(c)
        w = _normalize(data, c.get("city", "成都"))
        cache["weather"] = w
        store.save_json(CACHE, cache)
        return w
    except Exception as e:  # noqa: BLE001
        if w and time.time() - w.get("at", 0) < STALE_OK:
            store.log(f"天气刷新失败，用 {int((time.time() - w['at']) / 60)} 分钟前的数据: {type(e).__name__}")
            w = dict(w, stale=True)
            return w
        store.log(f"天气拿不到（可能断网）: {type(e).__name__}: {e}")
        return None


# ────────────────────────── 外面长什么样 ──────────────────────────

def hints(now=None, w=None):
    """把世界变成几句人话，够她随口说一句真关心。"""
    now = now or dt.datetime.now()
    today = now.date()
    out = []
    term = today_term(today)
    if term:
        out.append(f"今天是{term}")

    if w:
        desc, temp, drop = w.get("desc"), w.get("temp"), w.get("drop") or 0
        tmax, tmin = w.get("tmax"), w.get("tmin")
        if drop >= 4:
            out.append(f"今天比昨天冷了 {drop:.0f} 度（最高 {tmax:.0f} 度）")
        elif drop <= -4:
            out.append(f"今天比昨天回暖了 {abs(drop):.0f} 度（最高 {tmax:.0f} 度）")
        if temp is not None:
            out.append(f"现在 {temp:.0f} 度，{desc}")
        if tmin is not None and tmin <= 8:
            out.append(f"最低只有 {tmin:.0f} 度，冷")
        if (w.get("rain_soon") or 0) >= 55:
            out.append(f"六小时内下雨概率 {w['rain_soon']:.0f}%，出门带伞")
        elif (w.get("rain_today") or 0) >= 60:
            out.append(f"今天下雨概率 {w['rain_today']:.0f}%")

    wd = now.weekday()
    names = "一二三四五六日"
    if wd == 4:
        out.append("今天周五，快下班了")
    elif wd >= 5:
        out.append(f"今天是周{'六日'[wd - 5]}，周末")
    elif wd == 0:
        out.append("今天周一")
    f = next_festival(today, within=7)
    if f:
        if f["days"] == 0:
            out.append(f"今天是{f['name']}")
        elif f["days"] == 1:
            out.append(f"明天是{f['name']}")
        elif not f.get("is_term") or f["name"] in ("清明", "冬至", "立冬", "立春"):
            out.append(f"还有 {f['days']} 天是{f['name']}")
    return out


def snapshot(force=False, now=None):
    now = now or dt.datetime.now()
    w = weather(force=force)
    today = now.date()
    return {
        "weather": w,
        "hints": hints(now, w),
        "term": today_term(today),
        "festival": next_festival(today, within=10),
        "weekday": "一二三四五六日"[now.weekday()],
        "is_weekend": now.weekday() >= 5,
        "at": time.time(),
    }


if __name__ == "__main__":
    force = "--fresh" in sys.argv
    print(json.dumps(snapshot(force=force), ensure_ascii=False, indent=1))
    for y in (2026, 2027):
        t = terms_of(y)
        print(y, {k: v.strftime("%m-%d %H:%M") for k, v in sorted(t.items(), key=lambda kv: kv[1])})
