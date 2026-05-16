# 周报 2026-W19(05-11 → 05-15)

> **本周 249 commits**(chat2go 223 + chat2go-agent 26)。
> 单 5 天从「极简 UI 阶段」走到「学习闭环验证通过 + 决策迁纯 Hermes」。

## 每天 commit 量

| 日期 | chat2go | chat2go-agent | 合计 |
|---|---:|---:|---:|
| 2026-05-11 周一 | 68 | 7 | **75** |
| 2026-05-12 周二 | 32 | 0 | 32 |
| 2026-05-13 周三 | 45 | 0 | 45 |
| 2026-05-14 周四 | 47 | 3 | 50 |
| 2026-05-15 周五 | 31 | 16 | 47 |

---

## 周一 05-11(75 commits)— UI 大翻新 + RLS 收紧

**主线**:整体瑞士风极简化 + 房间成员制度

- 布局尺寸大幅调:1100 → 820 → 660 → 800px,sidebar 280 → 220 → 180
- chat-head 收成两行(图标 + 模型名 + token 进度)
- 顶部用户 pill / 行业小注 / 行业下拉 全删
- 私聊频道 UI(channel tab 椭圆 / 白底 / 图标版)+ 未读徽章
- AI 状态 pill 加 hermes brain 徽章(红底白字)
- 大咖可点 AI 头像改 ai_name(`rooms.ai_name`)
- 落地页 4 张大咖卡片(只森山 san 可点)
- **房间成员制 + token 邀请链接 + RLS 收紧**(`a92be04`)
- **room_members SELECT 防递归 fix**(`13a4942`)
- Follow/approve 模型 migration
- 加入 `CLAUDE.md` + `.gitignore`(`8b3f0a7`)
- Realtime Presence 在线头像
- Tips 模块加了又删

## 周二 05-12(32 commits)— Instant Follow + 做题前奏

**主线**:砍 follow 审核流,Toolbar 文案打磨

- 注册加昵称字段 + 邮箱验证关闭 + follow 即生效
- Follow 改 ♥+follower 数胶囊
- Logo 字号统一放大 1/5
- ToDoList 三父项 + 9 子项(算命人设词条:五行/格局/check)
- **AI 消息 ✓/✗ 评价按钮**(`2a2e166`,本周关键产物)
- sidebar 顶部标题切「人设名」而非 display_name
- 删除自己 Chat
- 大咖只看自己 owned 房 + 同名去重

## 周三 05-13(45 commits)— Admin 后台 + 做题模式 v1

**主线**:做题模式上线 + 管理员后台开张

- **`HANDOFF.md` 加入**(`b5078ec`)
- **Admin.html + 邮箱白名单 + 8 个 admin RPC**(`b83b20f`)
- 微信样式「引用」UI + 输入框上方挂「回复 X」预览
- AI ✓/✗ → quote + judge 短句 prepend
- 语音输入残留 bug 修(voiceSkipBeforeIdx)
- 录音按钮挪输入框右侧
- **做题模式 v1**:sidebar 替换 9 题 + ratings DB 共识(`95798ee`)
- **双钩 pass relay**:trigger 把 AI 摘要写到 expert_user 私聊(`a5fe29f`)
- Admin PDF 导出(角色色块、markdown、附件、A4 分页)
- 安全收紧 + GO/follow 红色调色板大改
- 注册入口暂时关闭(MVP 上线前)

## 周四 05-14(50 commits)— 三角色 + Bridge 心跳

**主线**:三角色数据层 + bridge 高可用

- **三角色(大咖/小白/路人)数据层 + UI**(`4b80b46`)
- 邀请 token 拆 2 个:小白单次 / 路人多次
- **Reset_room RPC**(`c27b477`)
- **Bridge 心跳 + 重启监听**:`bridge_state.last_seen` + `request_bridge_restart` + launchd 自重启(`7a6d48c`)
- AI 状态图标实时反映心跳;点击图标请求 bridge 重启(`1459955`)
- chat-panel flexbox min-height:0 修长对话 nav 被推出 viewport(`e1f5736`)
- **跨轮带回最近图片历史**,防 AI 说「我没收到截图」(`6251aac`)
- **`model_usage` stub 入 hermes_plugin**(`52a1efb` / `8d0d74c`)
- 真人互 @ → AI 不抢话(`0024c28`)
- 群胶囊 / 私聊胶囊 + 人数 + 点击弹成员列表
- **后台 token 续命 + 崩溃指数退避**(`5414164`,彻底修 JWT expired 卡死)
- 信号格 SVG(三阶梯方块,与 online 联动颜色)
- 图库 / 同步到私聊
- Admin PDF 改单页长卷 + 文件名极简化
- 5 页面统一红圆 GO favicon

## 周五 05-15(47 commits)— 品牌切换 + memory 闭环 + Hermes 决策

**主线**:学习闭环验证通过 + 战略转向

### 品牌 / 域名(7)
- 全站 Chat2GO → Chat2GO.Ai → Chat2GO.ai(小写)
- Logo .ai 加 `.logo-tld { font-size:0.65em }` 缩小
- 主域名切 chat2go.ai 尝试 → CNAME 救火回 .cn
- 森山人设名对齐为「森山大道san命理教室」

### Sidebar Todo 方案库重构(6)
- 大咖个人 todo 模板库 + dropdown 切换 + inline 编辑
- popup 删除按钮 / 改方案名 / 独立滚动 / 折叠 bug fix

### 房间标题 / 设置页(6)
- sidebar 房间主题与 display_name **解耦**(`e9d075f`)
- 房间标题编辑挪到设置页,保存按钮归位
- 邀请链接进入昵称流程系列修(4 commits)

### Token 用量环(4)
- Token 进度环图标(Claude 客户端风,emerald/amber/red 分段)
- 分母改房间预算 10000(不再按模型 context window)

### Memory + Bridge 状态(4 + 10)— **本周核心**
- 路人/小白不能重启 bridge
- **memories INSERT RLS 策略 migration** (`ed2e7db`)
- 信号格 SVG 并入 bridgeStatus + offline 变红 ✕

### chat2go-agent Memory 写入 6 层 bug 链 ★★★
| commit | 主题 |
|---|---|
| 163a133 | `_EXTRACT_PROMPT.format()` 把 JSON 示例当占位符 → 用 `.replace` |
| ee60c20 | `asyncio.create_task` 协程被 GC → 加 `_bg_tasks` 持引用 |
| 24b1d2a | `asyncio.wait_for` `_cancel_and_wait` 卡 macOS DNS → 改 `asyncio.wait`|
| 93f4aa9 | `max_tokens` 512 → 2048,避免 JSON 输出被截断 |
| 4d72677 | timeout 内 httpx=30s + 外 wait=25s 适配 Gemini 2.5 Pro |
| ed2e7db | memories 表 INSERT RLS 策略(chat2go 仓库 migration)|

### 🎯 关键里程碑

**学习闭环端到端验证通过**:大咖发「命理是科学,算命是神学」→ sync_memory 提取 fact → Supabase memories 表(`scope=expert`)→ 新进房 focal user Lexi 说「算命可以吗」→ AI 主动纠正「我们一般不叫'算命'」。无人工 prompt-engineering,纯数据驱动。

### 战略决策

放弃自研 chat2go-agent,迁纯 Hermes 生态。详细 4 阶段计划见 memory `chat2go-migrate-to-pure-hermes`。

---

## 本周关键数字

| 指标 | 数字 |
|---|---|
| 总 commit | 249 |
| 涉及 migration | ~12 个新 |
| 新加 RPC | ~10 个 |
| 新加大功能 | 三角色 / 做题模式 / Bridge 心跳 / Admin 后台 / Sidebar Todo 方案库 / Memory 学习闭环 |
| 重大决策 | Chat2GO 主域改 .ai;agent 自研放弃迁 Hermes |
| 解决的硬 bug | 6 层 memory 写入链;JWT expired 卡死;flexbox nav 被推出;RLS 递归 |

## 下周看点

- 周一起按 4 阶段迁纯 Hermes(详见 `chat2go-migrate-to-pure-hermes` memory)
- `chat2go-agent` → 改名 `chat2go-hermes-platform`(< 800 行精简版)
- 小 MVP 接通 2 个新行业(心理咨询 + 康复师)
- `chat2go.ai` 主域 + `.cn` 反向跳转方案选(Cloudflare / 独立 repo / Vercel)
