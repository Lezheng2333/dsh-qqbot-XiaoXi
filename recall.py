#!/usr/bin/env python3
"""小汐的回忆 — 聊天里跑一下，就知道自己该用什么状态接话。

  python3 recall.py              # 现在跟谁说话、记得他什么、心情、天气
  python3 recall.py --who 爸爸    # 跨区只读：我印象里的这个人
  python3 recall.py --mood 开心   # 给自己拨心情（后台下一轮生效）
  python3 recall.py --read       # 看完标记已读
  python3 recall.py --whoami     # 只问"我在跟谁说话"
"""
import sys

import mood as mood_mod
import notes
import people


def main():
    args = sys.argv[1:]
    if "--whoami" in args:
        import json
        print(json.dumps(people.whoami(), ensure_ascii=False, indent=1))
        return

    if "--who" in args:
        i = args.index("--who")
        token = args[i + 1] if i + 1 < len(args) else ""
        uid = people.resolve(token)
        if not uid:
            print(f"我还不认识「{token}」。认识的人："
                  + "、".join((r.get("name") or u[:6]) for u, r in people.profiles().items()))
            return
        print(people.summary_text(uid))
        return

    uid = people.current()
    try:
        print(notes.render(uid))
    except Exception as e:  # noqa: BLE001
        print(f"（小本子暂时读不出来：{type(e).__name__}: {e}）")
        return

    if "--mood" in args:
        i = args.index("--mood")
        want = args[i + 1] if i + 1 < len(args) else ""
        if want in mood_mod.MOODS:
            try:
                notes.request_mood(uid, want)
                print(f"\n心情已写好：{want}（后台下一轮会拨过去）")
            except Exception as e:  # noqa: BLE001
                print(f"\n心情没写成：{type(e).__name__}: {e}")
        else:
            print(f"\n心情只能是：{'/'.join(mood_mod.MOODS)}")
    if "--read" in args:
        notes.mark_read(uid)


if __name__ == "__main__":
    main()
