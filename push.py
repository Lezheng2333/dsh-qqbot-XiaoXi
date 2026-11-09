#!/usr/bin/env python3
"""小汐推送底层 — QQ 机器人 v2 接口（文字 / 图片 / 语音 / 输入中状态）。

支持多用户：每个函数都接受 uid（openid），不传就是"主人"。
凭据只从 DSH profile 里读，绝不写进日志、不落盘到 core。

  python3 push.py token
  python3 push.py text "内容"
  python3 push.py text "内容" <openid>
  python3 push.py image /abs/x.png
  python3 push.py voice /abs/x.m4a
"""
import base64
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.request

import paths

API_BASES = ["https://api.bot.qq.com", "https://api.sgroup.qq.com"]
TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
RETRIES = 2

# token 缓存：之前每发一条消息都重新取一次 token，既慢又容易撞限流
_TOKEN = {"value": None, "expires_at": 0.0}


def _creds():
    """从 DSH profile 读 appId/appSecret（读不到就让调用方报错，不打印内容）。"""
    text = open(paths.PROFILE_PATCH, encoding="utf-8").read()
    app_id = re.search(r'appId:\s*"?([^"\s]+)"?', text)
    secret = re.search(r'appSecret:\s*"?([^"\s]+)"?', text)
    if not app_id or not secret:
        raise RuntimeError("找不到 appId/appSecret（检查 DSH profile 的 cordis.patch.yml）")
    return app_id.group(1), secret.group(1)


def openid(uid=None):
    if uid:
        return uid
    import people
    return people.owner() or ""


def _post(url, payload, token=None, retries=RETRIES):
    """发请求；网络抖动/5xx 重试两次（4xx 直接失败，别重试刷接口）。"""
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"QQBot {token}"
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="ignore")[:200]
            last = RuntimeError(f"HTTP {e.code}: {body}")
            if 400 <= e.code < 500 and e.code != 429:
                raise last from None
        except Exception as e:  # noqa: BLE001
            last = e
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"接口失败: {last}")


def token(force=False):
    """带缓存的 access_token（提前 5 分钟过期，避免边界失败）。"""
    if not force and _TOKEN["value"] and time.time() < _TOKEN["expires_at"]:
        return _TOKEN["value"]
    app_id, secret = _creds()
    out = _post(TOKEN_URL, {"appId": app_id, "clientSecret": secret})
    if not out.get("access_token"):
        raise RuntimeError("取 token 失败（返回值里没有 access_token）")
    ttl = int(out.get("expires_in", 7200) or 7200)
    _TOKEN["value"] = out["access_token"]
    _TOKEN["expires_at"] = time.time() + max(300, ttl - 300)
    return _TOKEN["value"]


def api(path, payload, tok=None, uid=None):
    tok = tok or token()
    target = openid(uid)
    if not target:
        raise RuntimeError("不知道发给谁：没有 openid（先在 bootstrap 里登记主人）")
    last = None
    for base in API_BASES:
        try:
            return _post(f"{base}/v2/users/{target}{path}", payload, tok)
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"接口失败: {last}")


def send_text(content, tok=None, uid=None):
    return api("/messages", {"content": content, "msg_type": 0}, tok, uid)


def typing(seconds=4, tok=None, uid=None):
    """'正在输入' 状态（平台侧可能忽略，尽力而为）。"""
    try:
        return api("/messages", {"msg_type": 6, "input_notify": {
            "input_type": 1, "input_second": max(1, min(60, seconds))}}, tok, uid)
    except Exception:  # noqa: BLE001
        return None


def _upload(path, file_type, tok, uid=None):
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    target = openid(uid)
    out = api("/files", {"file_type": file_type, "file_data": b64, "srv_send_msg": False}, tok, uid)
    if not out.get("file_info"):
        raise RuntimeError("上传失败（没有 file_info）")
    return out["file_info"]


def send_media(path, file_type, tok=None, uid=None):
    tok = tok or token()
    info = _upload(path, file_type, tok, uid)
    return api("/messages", {"msg_type": 7, "media": {"file_info": info}}, tok, uid)


def send_image(path, tok=None, uid=None):
    return send_media(path, 1, tok, uid)


def send_voice(path, tok=None, uid=None):
    return send_media(path, 3, tok, uid)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "token"
    if cmd == "token":
        t = token()
        print("token ok:", t[:10] + "…")
    elif cmd == "text":
        who = sys.argv[3] if len(sys.argv) > 3 else None
        print(json.dumps(send_text(sys.argv[2], uid=who), ensure_ascii=False))
    elif cmd == "image":
        print(json.dumps(send_image(sys.argv[2]), ensure_ascii=False))
    elif cmd == "voice":
        print(json.dumps(send_voice(sys.argv[2]), ensure_ascii=False))
    else:
        raise SystemExit(__doc__)
