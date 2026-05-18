# Handoff — 2026-05-17 晚

> 给明早(2026-05-18)接手 session 的 Claude 看的。读完直接接得上。

## TL;DR

今晚把 **tradego 站从子目录拆出独立 repo + 独立部署**(`chat2go.xyz`),mini Hermes 切 **DeepSeek V3**,主站 + tradego 都把"单钩待二钩"状态可视化方案**迭代了 7 轮**最终落地成 **sidebar 题目胶囊半勾**(取消顶部 banner)。两边 chat.html 现在功能对齐。

## 当前生产状态

```
chat2go.cn  → tototo1999/chat2go    → Hermes(dev 机)  → main: claude-sonnet-4-6
chat2go.xyz → tototo1999/tradego    → Hermes(mini)    → main: deepseek-chat (V3), vision: claude-haiku-4-5

mini Hermes: PID 61550, launchd 守护, watchdog 60s 自救兜底 → 24h 在线已 ready
```

## 今晚版本 list

### 主站 `tototo1999/chat2go`(47 commits)

按主题分组(不按时间排,看主题更清晰):

**typing 指示器优化**
```
4dcacd8  ui: typing 头部 * → GO 圆圈 + token 计数改本房累计
e30f0fb  ui: typing GO 圆圈缩小 19→14px
4a9cb1a  ui: typing 头部改纯红描边圈(去掉 GO 文字)
aacd723  ui: typing 红圈改雷达 ping 动画
bd2350c  ui: typing 动词字号 14→12px
```

**todo 系统**
```
479d46f  ui: 大题链式解锁(上一组全 pass 才开下一组)
104512c  ui: 大题锁图标改 SVG 挂锁/开锁
cb63a92  ui: 已完成 todo 组自动折叠
1077d7c  revert: 去掉大题链式解锁
5f84c4f  Revert revert(链式解锁加回来)
14e2083  ui(tradego): 小锁头功能加回去对齐主站
```

**tradego 子目录 → 独立 repo 迁移**
```
0985741  feat: tradego MVP 子目录骨架 /tradego/
0c1ef40  ui(tradego): 第一张卡解锁可点击 /tradego/chat.html
9185211  feat: rooms.product 隔离主站 vs /tradego/
212d0d9  feat: expert_todo_templates 加 product filter
2010e2e  ui(tradego): nav logo 改 TradeGO
8cbc3d0  ui(tradego): 打开注册 tab
494c2fd  ui(tradego): 100 个外贸跟单 typing 用语
a0694e0  feat(tradego): 10 个 checkpoint todo
426c29d  ui(tradego): todo 简化为 3 组 10 题
fb12a40  ui(tradego): todo 去掉链式解锁
a4bfae6  ui(tradego): CSS 强制隐藏锁图标
de4f857  ui(tradego): 邀请链接按钮直接复制
b0e9410  fix(tradego): 邀请入场等 session 就绪
c121fda  ui(tradego): 关闭注册 tab
40378b1  ui(tradego): 订单子项改 5 个单证关键词
e453fdf  chore: 删除 chat2go.cn/tradego/(已迁独立 repo)  ★关键节点
```

**单钩待二钩状态可视化(7 轮迭代)**
```
e687180  ui: sidebar 房间置顶 📌(保留)
6516484  ui: 房间内 sticky 横条公告条
eb1a998  ui: 置顶 + 公告条配色改中性灰 + 同步 tradego
bed82be  ui: 改居中胶囊横排
1a426ea  ui: 公告条容器去白底/border/blur
0e77ea9  ui: 胶囊单行并列居中 + 去胶囊白底
7468f30  fix: 胶囊点击改 JS 绑定 + flash 用 box-shadow
aef035e  debug: 加 console.log + toast + 去 pointer-events
cc3e92f  ui: 胶囊容器 fit-content + margin auto
effe809  ui: :empty 兜底
0cb6e87  feat: 取消顶部胶囊,改 sidebar 题目胶囊半勾  ★最终落地
```

**架构 + 配置 + docs**
```
a2aa0e5  ui: 房间 token 预算 10K → 10M
39370e3  docs(hermes-patches): chat2go.py 加 _watchdog_loop 自救
998471a  docs(tradego-mini): 同步晚状态 + vision pre-process
df46b30  docs: 新建 TODO.md
711f601  docs(TODO): 加多大咖部署模板
8f5a9a9  docs(TODO): 加 GitHub PAT 轮换
```

### tradego mini `tototo1999/tradego`(11 commits,跟主站同步)

```
8e049a8  feat: TradeGO 独立站初始部署(chat2go.xyz)
886bb9c  ui: sticky 公告条 + sidebar 房间置顶
932704d  ui: 公告条改居中胶囊 + 清洗 markdown
0fcdb68  ui: 公告条容器去白底
1f5da1d  ui: 胶囊单行并列 + 去白底
74a5463  fix: 胶囊点击改 JS 绑定 + flash box-shadow
f4e5789  debug: console.log + toast + 去 pointer-events
c241108  ui: 胶囊容器 fit-content
2f43da2  ui: :empty 兜底
a24bc83  feat: 取消顶部胶囊,改 sidebar 题目胶囊半勾  ★最终
419b2b7  fix: copyInviteLink fallback 改 textarea+execCommand(HTTP 环境也能直接复制)
```

> ⚠️ chat2go.xyz **Enforce HTTPS 还没在 GH Settings 里勾**,用户从 http://访问时,navigator.clipboard 不可用 → fallback 路径触发。代码层已经做 textarea+execCommand fallback,但 GH Settings 勾上 Enforce HTTPS 一了百了。

## chat2go.py adapter 三项重大改造(同步两机)

- `_read_hermes_default_model()` — stub_model 自动跟随 `~/.hermes/config.yaml`
- `_watchdog_loop()` — _poll_loop 心跳 >60s 没更新就 `os._exit(1)` 让 launchd 拉起
- vision pre-process — 图片先调 `vision_analyze_tool` 转文字,不再让 main 直接拿 image_url

存档:`docs/hermes-patches/02-chat2go-platform-adapter.patch`(1110 行,全量 snapshot)。

## 明天主线(详见 `docs/TODO.md` 2026-05-18 段)

1. **tradego 拦截器扩 Excel**(报价单 / 装箱单 / PL)— 让大咖出 Excel 不打开 terminal
2. **撤换 3 条泄露的 key/token**:OpenRouter / DeepSeek / GitHub PAT(都在本会话历史里贴过明文)
3. **`model_usage` 表 anon SELECT 权限**(stats 拉不到)
4. **10 个外贸 + 10 个命理实战个案数据复盘**
5. **多大咖部署模板** `deploy-expert.sh <industry> <ssh_user> <ssh_host> <token> <provider> <model>`
6. **handoff SOP**:加"单文件同步 chat2go.py 到 mini"的安全 SOP(避免 deploy.sh 全套覆盖风险)

## 明天接手 SOP

```bash
cd ~/chat2go
claude
# Claude 会自动读 MEMORY.md 索引,看到:
#   - chat2go-state-2026-05-17-pm(本晚快照)  ← 今晚的事
#   - project-tradego-architecture            ← 双 repo 双部署
#   - project-tradego-mini-deployment         ← mini 配置
#   - project-mini-24h-uptime                 ← 24h 在线方案
#   - feedback-auto-poll-after-push           ← grep chat2go.cn 验证部署
#   - feedback-supabase-sql-split             ← Supabase SQL 拆单条发
```

然后让 Claude `cat docs/TODO.md`,从 2026-05-18 段第一条任务开始干。

## 重要踩坑记忆(明天别再踩)

- **改 tradego/chat.html 不能整文件 rsync 主站**(会丢主题色 + tradego 文案差异),必须 surgical patch.py + scp + ssh apply
- **每个文件改动后两端 commit 用同一 commit message**,方便对照同步状态
- **chat2go.cn/tradego/ 永久关闭**,以后任何前端只推主站根 chat.html
- **shell ssh + python heredoc + 嵌套 quote 容易爆炸** → 用本地 Write 写 patch.py 文件 + scp 过去,更稳
- **patch 02 (chat2go.py 全量)在 dev 机生成,mini 上是 git checkout**,patch 02 也要每次重新 dump
- **AI 自报模型名不可信**(系统 prompt 里写啥都行),配置真实信息看 `config.yaml`

---

晚安。
