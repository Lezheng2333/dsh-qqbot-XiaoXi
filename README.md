# QQ bot XiaoXi core — 小汐的全部家当

一只住在 QQ 里的鲸鱼娘。这个文件夹是她的**全部**：人设、记忆、心情、图库、语音、定时冒泡的守护进程。
整个文件夹拷到另一台电脑，跑一次 `python3 bootstrap.py` 就能原地复活。

> 约定：她的东西都在这儿；`~/.dsh`、`~/.dsh-qqbot/model-prefs.json` 属于 DSH 宿主，
> 只是她借住的房子（会话记录、插件绑定），搬家时不用带。

## 一分钟上手

```bash
cd "QQ bot XiaoXi core"
python3 bootstrap.py --check   # 体检：依赖、DSH profile、owner、会话目录
python3 bootstrap.py           # 装好：人设→DSH、工作区说明书、兼容桥、开机自启
python3 daemon.py --status     # 她现在什么心情、今天发了多少、下次什么时候
```

## 目录长什么样

```
QQ bot XiaoXi core/
├── paths.py            所有路径的唯一来源（没有一行写死绝对路径）
├── bootstrap.py        装机 / 搬家 / 恢复
├── apply_persona.py    把人设同步进 DSH profile（自动备份 + 回读校验）
├── daemon.py           守护进程：排程、攒话、发表情/语音
├── persona/
│   ├── direct.md       私聊人设（真身）
│   └── group.md        群聊人设
├── users/              ★ 按 QQ 用户分区（一个人一个文件夹）
│   ├── index.json      花名册：openid → 名字/关系/是否允许主动冒泡
│   └── <openid>/
│       ├── memory.json      记得他的事
│       ├── notes.json       她对他主动说过的话
│       ├── mood.json        对他时的心情
│       ├── engagement.json  他回不回她
│       └── state.json       他这条线的额度/下次时间
├── AGENTS.md           工作区说明书（DSH 每次会话自动注入；bootstrap 生成）
├── workspace/          旧工作目录（兼容老会话）与写信箱
├── library/            表情图库（composed/ 是自制卡）
├── media/              QQ 收到的图/歌（缓存，可删）
├── logs/               daemon.log（自动轮转）、语音样本
├── state/              全局运行时：心跳、天气缓存、图库标签、去重记录
├── config.json         运行参数（不含密钥）
├── topic.py            话题追踪（现在在聊什么，跨消息保持）
├── journal.py          日记（每天一页，跨天记忆）
├── memory.py notes.py mood.py engagement.py people.py recall.py
├── messages.py stickers.py compose.py tts.py world.py transcripts.py store.py
└── selftest.py         全链路自测（假发送，不碰真实数据）
```

**密钥不在这个文件夹里**：appId/appSecret 留在 DSH profile 的 `cordis.patch.yml`。
把 core 发给别人不会泄露凭据。

## 用户分区：她怎么知道在跟谁说话

DSH 的 QQ 插件给每个 openid 建一个独立会话，`~/.dsh-qqbot/model-prefs.json` 里记着
`openid → sessionId`。她的 `people.current()` 干三件事：

1. 找最近在写的那条会话（谁刚发消息，就是谁）；
2. 用 sessionId 反查 openid；
3. 打开 `users/<openid>/`，把"这个人"的记忆/心情端出来。

所以：

- **爸爸跟她说话** → 用的是爸爸分区里的记忆，称呼是「爸爸」，可以撒娇。
- **陌生人跟她说话** → 自动新建分区（名字先叫「用户_xxxxxx」），话术收敛：
  不叫爸爸、撒娇权重压到 0.18、先问一句。
- **B 问「A 是个怎样的人」** → `people.py show A` 跨区只读，只给印象和近况，
  不搬运原话、不抖隐私（人设里写死了这条规矩）。
- 私事**不会**进 `workspace/AGENTS.md`：那个文件是所有用户共用的，
  所以它只写说明书，记忆一律走 `recall.py`（它知道现在是谁）。

花名册可以手改，也可以让她自己记：

```bash
python3 people.py list              # 有哪些人、聊过多少
python3 people.py show 爸爸          # 跨区看：她印象里的这个人
python3 people.py name 老王 老王      # 改名 + 称呼
```

## 她能直接写自己的文件夹

她的 agent 工作目录（沙箱根）就是**整个 core 文件夹**（`config.json` 里 `agent_cwd: "."`），
所以记忆、图库、状态都在可写范围内，写盘不用审批。

如果沙箱根还没跟上（比如换过目录但会话还是老的），写盘不会弹审批也不会丢：

1. `paths.save_json` / `paths.save_file` 捕获 `PermissionError`；
2. 把内容和目标路径放进"信箱"（`workspace/.outbox/` → 不行就 `/tmp/dsh-*/xiaoxi_outbox/`）；
3. 守护进程每轮 `paths.drain_outbox()` 代写进 core；
4. 这期间 `paths.load_json` 会先读信箱，所以"刚记下的"立刻就能读到。

换过工作目录后，在 QQ 里发一句 `/new`（或 `/reset` / `/clear`）让会话用新目录；
历史记录不会被删，只是开一条新会话。

## 三层记忆

| 层 | 存在哪 | 谁写 | 解决什么 |
|---|---|---|---|
| 会话内 | DSH 会话记录 | DSH | 同一次对话里的上下文 |
| 话题 | `users/<uid>/topic.json` | 守护进程每分钟 | 一段时间只聊一件事，不一句一换 |
| 日记 | `users/<uid>/journal/YYYY-MM-DD.json` | 守护进程每天 | 跨天："昨天你们聊了……" |
| 事实 | `users/<uid>/memory.json` | 她自己（memory.py） | 长期的人设级记忆 |

外加 `users/<uid>/notes.json`：她**主动**发出去的话（含表情包路径）——
这些不进她的会话，只能靠 `recall.py` 看见，所以人设里写了"开口前先跑 recall"。

`recall.py --search 关键词` 能在"她说过的 + 他说过的"里全文搜，
对方提到一件她想不起来的事时用，搜不到就老实说没有（别猜）。

## 她的记忆闭环

```
守护进程攒话 → 发出去 → 写 users/<uid>/notes.json
                              ↓
聊天时：recall.py → "我在跟谁说话 / 我记得他什么 / 我最近对他说过什么 / 心情 / 天气"
                     ↓
              memory.py add "……" → 记到当前这个人名下
```

`workspace/AGENTS.md` 是 DSH 每次会话会自动注入的"工作区说明书"，
里面只写"回话前先跑 recall.py"这类方法，**不写任何人的内容**。

## 搬家 / 移植（换电脑）

0. 也可以直接从仓库克隆（仓库里只有代码和人设，**没有** memory/users/media/日志）：

   ```bash
   git clone https://github.com/Lezheng2333/dsh-qqbot-XiaoXi.git "dsh-qqbot XiaoXi"
   ```

1. 或者把整个文件夹拷过去（可以不带 `media/`、`state/tts/`，是缓存）。
2. 新电脑上装好 DSH 和 QQ 插件（`@tencent-connect/dsh-qqbot`），填好 appId/appSecret。
3. 跑 `python3 bootstrap.py --check` 看缺什么，再跑 `python3 bootstrap.py`。
4. 它会：登记主人（从 `model-prefs.json` 自动发现 openid，或 `--owner <openid>`）、
   写人设进 profile、生成 AGENTS.md、建兼容桥、装开机自启。

`bootstrap.py` 建的两个桥（**都是符号链接，不复制数据**）：

| 旧路径 | 指向 | 为什么 |
|---|---|---|
| `~/.dsh-qqbot/workspace` | `core/workspace` | DSH 的旧会话把工作目录钉在旧路径，链过去它才读得到说明书 |
| `~/.dsh-qqbot/media` | `core/media` | QQ 插件把收到的图/歌写死在这个位置，链过去它们就落在 core 里 |

不想要这两个桥：`python3 bootstrap.py --no-bridge`（新机器上没有旧会话时完全不需要）。

## 常用命令

```bash
python3 daemon.py --status          # 每个人：额度/下次时间/心情/回复率 + 心跳
python3 daemon.py --dry-run         # 预演一轮（不联网挑图、不发送）
python3 daemon.py --dry-run --user 老王
python3 daemon.py --preview         # 完整跑：攒话+挑图+合语音，都不发送
python3 daemon.py --simulate 10     # 连演 10 轮，看会不会重复
python3 daemon.py --doctor          # 自检：依赖/天气/图库/token/心跳/会话
python3 selftest.py                 # 多用户全链路自测（临时目录，不动真实数据）
python3 recall.py                   # 她的小本子摘要（含"我在跟谁说话"）
python3 recall.py --who 爸爸         # 跨区只读
python3 recall.py --mood 开心        # 给自己拨心情（后台下一轮生效）
python3 people.py list              # 花名册
python3 mood.py list                # 所有人各什么心情
python3 engagement.py list          # 所有人各什么回复率
python3 world.py                    # 天气/节气/节日
python3 stickers.py curate          # 图库体检（去重/补标签/生成 REVIEW.md）
python3 tts.py samples              # 五种心情的语音试听
touch PAUSE                         # 暂停主动消息（全局）；rm PAUSE 恢复
```

## 她有什么本事（v2 到 v3 累积）

- **记忆闭环**：主动说过的话会被记住，聊天时接得上；记忆按人分区。
- **心情状态机**：开心 / 黏人 / 小别扭 / 困 / 担心，对每个人各算各的，影响语气、表情、语音。
- **话术不重复**：关心 32 / 撒娇 32 / 分享 32 / 故事 33 / 情绪专属每种 15 条，7 天内不重样。
- **语音有情绪**：Xiaoyi（活泼）/ Xiaoxiao（温柔）+ 各心情的 rate/pitch，失败回退 macOS say。
- **表情看得懂场合**：入库打情绪标签；关心/天气/分享一律中性鲸鱼脸，只有"哼/吃醋/呜呜"才配生气哭脸。
- **知道外面的世界**：成都天气（温差/降雨）、24 节气（天文算法）、农历节日、周末。
- **主动性会自适应**：连着不回就降频，聊得热络就升温；陌生人默认不主动。
- **可靠性**：心跳、日志轮转、断网排队、token 缓存、发送重试、异常打堆栈。

## 仓库里有什么、没什么

公开仓库 `Lezheng2333/dsh-qqbot-XiaoXi` 只装"骨架和人设"：

| 进仓库 | 说明 |
|---|---|
| 全部 .py | 代码本身就是她的能力 |
| `persona/` | 人设真身（`{CORE}` 占位符，不含本机路径） |
| `library/composed/` | 她自己画的情绪卡（自制，安全） |
| `README.md` `config.json` | 说明与参数（无 openid、无密钥、无绝对路径） |

| 不进仓库（`.gitignore`） | 为什么 |
|---|---|
| `users/` | 每个人的 openid、她记得的事、心情、聊天偏好 —— **这是隐私** |
| `media/` | QQ 收到的图/歌，可能是私人照片文件 |
| `logs/` `state/` `workspace/` `backup/` | 运行时/缓存/生成物，且带本机绝对路径 |
| `library/` 里抓来的图 | 网上抓的表情，版权和内容都不可控 |

密钥（appId/appSecret）从来只在 DSH profile 里，连本地 core 都没有。

## 已知边界

- 她的"身份识别"依赖"最近写入的那个会话"——同一个人连续发消息没问题；
  两个人恰好同一秒说话时可能认错（概率极低，认错了也是按陌生人处理，不会泄露）。
- `~/.dsh/sessions/` 里的聊天记录属于 DSH，不在 core 里；换电脑后历史会话不会跟着走，
  但"她记得的事"在 `users/*/memory.json`，会跟着走。
- 人设是"软"约束：模型偶尔还会跑偏，改 `persona/direct.md` 再跑 `apply_persona.py` 即可。
