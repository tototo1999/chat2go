# Chat2GO.ai — REBUILD HANDOFF(给外部 vibe-coding LLM 看)

> **目标读者**:从未接触过本项目的 LLM agent / coder。读完这份就能从零搭起后端,部署到 `chat2go.ai` 上,前端 100% 复用已有 `chat2go` 仓库。
> **不要**改前端代码 —— `chat2go` 仓库的 5 个 HTML / 36 个 supabase migrations 都是契约,你只需要让后端按这些契约工作。
>
> **2026-05-16 下午 v0.2**:Track A 本机 Phase 1-3.5 跑通后回写,主要补充 §5.4-5.6 memory loop 实战实现 + §11 引用 docs/hermes-patches/ 作为权威参考代码。
>
> **生产实证(2026-05-16 16:00 UTC)**:
> - Hermes gateway PID 74319 持续在线
> - chat2go platform 状态 `connected`
> - bridge_state.last_seen age <30s
> - Hermes 接管后 87 分钟自动写入 23 条 memory(scope/tags/source_message_id 全程正确)
> - 5/5 关键功能端到端跑通(AI 回复 / model_usage / memory loop / 心跳 / Realtime)

---

## 0. 30 秒看懂

```
[chat2go.cn 前端]                  [Supabase 数据库 + Edge Functions]            [你要写的后端]
  index.html        ─┐                                                            
  login.html         │  HTTPS / Realtime WebSocket                                
  chat.html          ├─────────────────────────────►  postgres + auth + storage  ◄──── 订阅 messages 表
  onboarding.html    │                                                                  推 AI 回复
  admin.html        ─┘                                                            
                                                                                        ↓
                                                                                  调 LLM (Anthropic/OpenAI/Gemini)
                                                                                        ↓
                                                                                  INSERT messages role='ai'
```

**你的工作**:实现「订阅 Supabase Realtime → 路由到 LLM → 写回 AI 消息」这个 backend,部署到云端,绑定 `chat2go.ai` 流量。

---

## 1. 产品定位 + 三角色

Chat2GO.ai 是 **AI marketplace**:行业大咖 + AI + 小白三方协作平台。

**核心角色**:
- **大咖**(`profiles.role='expert'`):行业从业者(命理师 / 心理咨询师 / 康复师等),房主 + AI 调教者
- **小白 / focal user**(`rooms.focal_user_id`):第一个非大咖加入房间的人,是该房的「主角」
- **路人 / audience**(其余加入者):可观摩,不参与 AI 调用,不计费
- **AI**:由你的后端写入(role='ai',user_id 用大咖 user_id 占位)

**核心交互场景**:
小白进大咖房间问问题 → 大咖看 AI 回答 → 大咖纠正/补充 → AI 记住该纠正(memories 表) → **下次小白(或新小白)问类似问题,AI 自动应用大咖知识**。

**MVP 阶段(2026 年 5 月)**:1 大咖(森山命理)→ 扩到 3 行业(命理 + 心理咨询 + 康复师)。

---

## 2. 数据模型契约(★ 这是和前端的硬接口)

完整 schema 见 `chat2go/supabase/migrations/*.sql`,共 36 个 migration 文件,2026-05-16 时点已全部应用到生产 Supabase。

### 2.1 你必须知道的表

| 表 | 你怎么用 |
|---|---|
| `rooms` | SELECT 拿房间元信息(industry / expert_id / focal_user_id / model / system_prompt / ai_name / brain / commission_pct / exchange_rate_to_cny / sidebar_title / active_todo_template_id) |
| `messages` | **SUBSCRIBE INSERT 事件**(role != 'ai')+ **写入 role='ai' 的回复**;字段:room_id / user_id / role / content / type / attachments / channel / ratings |
| `profiles` | SELECT 拿大咖 / 小白的 display_name |
| `room_members` | 不直接用,DB trigger 自动维护(focal_user_id 锁定就在这) |
| `expert_agent_keys` | 不直接用,通过 `agent-auth` Edge Function 兑换 session |
| `bridge_state` | **★ 心跳必写**(通过 `bridge_pong()` RPC),否则前端信号格永远显示离线 |
| `model_usage` | **★ 每次 AI 回复后写一行**(只填 token 数,不填计费金额) |
| `memories` | **★ 大咖纠正自动沉淀**(scope=room/expert/user,prefetch + sync,详见 §5)|

### 2.2 channel 字段(messages 表)

- `channel='main'`:三方共聊,**AI 必须响应**
- `channel='expert_user'`:大咖 ↔ 小白私聊,**AI 必须跳过不响应**

收到 INSERT 时**第一件事**就是判断 channel,私聊直接 return。

### 2.3 ratings 字段(messages 表)

做题模式,小白和大咖各打钩 `up`/`down` 存进 `messages.ratings` jsonb。**双钩 up 触发 DB trigger 自动 relay AI 摘要到私聊频道**(`trg_relay_pass_to_private`)。**你的后端不用管做题模式逻辑** —— DB trigger 已经做完。

### 2.4 关键 RPC(你可能要调用)

| RPC | 用途 |
|---|---|
| `bridge_pong(p_pid, p_hostname)` | ★ 心跳,每 5-10 秒一次,SECURITY DEFINER 绕开 bridge_state RLS |
| `agent_auth_exchange(key)` | bridge 启动时用 connection_key 换 magiclink OTP |
| `request_bridge_restart()` | 大咖前端点击重启按钮触发(你的后端可监听 `bridge_state.restart_requested_at`) |
| `get_expert_follower_count` / `get_expert_followers` | 主要给前端用 |
| `get_room_member_count` / `get_room_members` | 同上 |
| `rate_message` | 做题模式打钩,前端调,你不用管 |
| `admin_*` 系列 | admin 后台用,你不用管 |

### 2.5 Edge Functions(已部署,你直接调)

- `POST /functions/v1/agent-auth/exchange`(body: `{key: c2g-key_xxx}`)→ 返回 `{token_hash, email, expert_id}`,然后 `auth.verify_otp({token_hash, type: 'magiclink'})` 换 session
- `POST /functions/v1/chat-ai`(备用,Deno 写的 server-side LLM 调用,当你的后端离线时降级用,不强求实现)

### 2.6 Storage

`chat-uploads` bucket(已改 private):图片 / pdf / docx 等附件。**你需要**:
- 收到带附件的 inbound 消息时,下载附件提取文本(pdf/docx → text)或用 vision URL
- AI 回复带附件(可选,MVP 阶段非必需)
- 大咖私有 / 公开都可用,通过 `storage_path` 字段拿;过期的可重新生成 signed URL

---

## 3. 前端契约(`chat2go` 仓库)

前端 5 个静态 HTML 页面已部署在 GitHub Pages(`chat2go.cn` 当前,`chat2go.ai` 主域计划)。**不要改前端代码**;你只需让 backend 满足前端的预期。

前端的硬性预期:
1. **收到大咖 / 小白消息后,你必须在 30 秒内 INSERT 一条 role='ai' 的回复**(用大咖 user_id 占位,channel 跟原消息一致),否则前端 typing 指示器会消失
2. **bridge_state.last_seen 每 5-15 秒必须刷新**(用 `bridge_pong` RPC),否则信号格变红 ✕
3. **AI 消息 type='text' 或 'markdown'**(MVP 暂时一律 'text' 也可,markdown 自动检测)
4. **附件回显**(`messages.attachments` JSONB):AI 不需要主动产附件,但收到的附件文本/图片必须处理
5. **mention @ 真人时 AI 不抢话**(消息含 `@非AI名字` 时跳过响应)
6. **重启信号**:监听 `bridge_state.restart_requested_at` > 后端启动时间,触发自我退出(让 launchd/k8s 拉起新进程)

---

## 4. Hermes 是什么 + 集成方式(参考实现)

Hermes 是一个本地 AI agent 框架(本机已装 `~/.hermes/hermes-agent/`)。它原生支持把多个 messaging platform 当成 IM 渠道(Discord / Telegram / WhatsApp / WeChat / **Chat2GO**)。

### 4.1 Hermes 的核心抽象

- **Platform adapter**:订阅外部 IM 平台的入站消息,把 Hermes 的回复写回
- **Brain**:LLM 调用(支持 Anthropic / OpenAI / Gemini 等)
- **Memory**:Hermes 自有 memory(本地文件 `~/.hermes/memories/MEMORY.md`)+ 跨会话上下文压缩
- **Skills**:可加载的能力包,跟我们的「行业 skill」概念兼容但不同设计

### 4.2 本机参考实现:`gateway/platforms/chat2go.py`(~533 行)

本机已经跑通的 chat2go platform adapter 在:
`/Users/dami2026/.hermes/hermes-agent/gateway/platforms/chat2go.py`

主要方法:
- `connect()`:用 CHAT2GO_TOKEN 调 agent-auth 兑换 session
- `_subscribe_realtime()`:订阅 messages 表 INSERT 事件
- `_poll_loop()`:5 秒轮询兜底 + ★ `bridge_pong` 心跳
- `_dispatch_inbound(msg)`:收到消息派给 Hermes brain
- `send(chat_id, content)`:把 brain 回复 INSERT 进 messages 表 + 写 `model_usage` stub

**外部 LLM 重做时可以照抄这份逻辑,也可以完全重新设计架构 —— 关键是满足 §3 前端契约。**

### 4.3 Hermes 的限制(为啥要重建到云端)

- Hermes 是本地框架,设计上跑在大咖自己机器上
- 多大咖多进程 / 跨地域部署 → 需要重新设计
- Hermes memory 是本地文件,不接 Supabase `memories` 表 → **学习闭环目前已经断了**(2026-05-16 实测:Hermes 启动后 memories 表 0 新增,详见 §5)
- 云端跑 Hermes 需要把它容器化 + 多 expert 共用 instance

---

## 5. ★ Memory 学习闭环(产品差异化核心)

### 5.1 设计意图

大咖发完纠正消息后:
1. **后端用 LLM 提取该消息里的「事实/规则/偏好」** → JSON 数组
2. 写入 `memories` 表(scope=`room`/`expert`/`user`)
3. 下次任何消息触发 AI 调用前,先 prefetch 该房间的 memories → 拼进 system prompt
4. AI 自动应用大咖知识,无需人工 prompt-engineering

### 5.2 实测验证场景(2026-05-15 闭环跑通过一次)

- 大咖发:「命理是科学,算命是神学」
- 后端 LLM 提取出 fact,scope=`expert` 写入 memories
- 新进房的 focal user(Lexi)说「算命可以吗」
- AI **自动**回:「我们一般不叫'算命',命理分析会更准确...」
- 全程无人工 prompt engineering

### 5.3 2026-05-15 踩通的 6 层 bug(避免重新踩)

| Bug | 你怎么避坑 |
|---|---|
| Python `str.format()` 把 prompt 里的 JSON 示例 `{"content": ...}` 当占位符 → KeyError | 用 `str.replace("{dialogue}", ...)` 或 jinja2,**不要** `.format()` 配 JSON 示例 |
| `asyncio.create_task` 协程被 GC | task 必须 add 到 strong-ref 集合;done callback discard;别 fire-and-forget |
| `asyncio.wait_for` 的 `_cancel_and_wait` 卡 macOS DNS getaddrinfo | 用 `asyncio.wait({task}, timeout=...)` 而不是 wait_for,真硬超时不 await cancel 完成 |
| LLM `max_tokens=512` 输出 JSON 被截断,正则 `\[.*\]` 找不到闭合 `]` | max_tokens >= 2048 |
| `httpx` timeout=10s 太严,Gemini JSON 输出常需 10-20s | inner timeout=30s,外层 wait=25s |
| `memories` 表 INSERT RLS policy 缺失,bridge 用 expert session 写被 deny | 已 apply migration `20260515200000_memories_insert_policy.sql`,生产 DB 上 INSERT policy 已开;但 UPDATE/DELETE 也按 scope owner-self 开了 |

### 5.4 当前(2026-05-16 下午)状态:**✅ 已重新打通,可参考实现**

- Hermes 平台适配器内**已实现** `_prefetch_memory` + `_sync_memory`(参考 §5.6)
- 实战验证:Hermes 接管后 87 分钟自动写入 23 条新 memory,scope/tags/source_message_id 全程正确
- 闭环复现:大咖发「命理是科学」→ 几秒后 memories 表新行 → 新消息触发时 `<memory-context>` 自动 prepend 进 prompt

### 5.5 你重建时的 3 个选项

| 选项 | 说明 | 推荐度 |
|---|---|---|
| **(a) 复刻 sync_memory + prefetch_memory pattern** | 大咖消息后 LLM 提取 fact,JSON,写 `memories` 表;每次入站消息前 prefetch 三 scope 的 memory 注入 prompt | ★★★ 跟前端契约最对,产品差异化能延续 |
| (b) 用 Hermes 自带 memory,但同步到 `memories` 表 | 双向同步 Hermes 本地文件 ↔ Supabase 表 | ★ 复杂 |
| (c) 完全弃 `memories` 表,改用 Hermes memory + 前端读 Hermes 本地文件 | 改前端契约 | ✗ 违背"前端不动"原则 |

**推荐 (a)**。本机参考实现在 `docs/hermes-patches/02-chat2go-platform-adapter.patch`(本仓库),
是已经在生产跑通的版本(2026-05-16 23 条 memory 实测),不是设计文档,是 working code。

### 5.6 ★ 参考实现关键点(直接抄)

**Prefetch**(每次入站消息前):
```python
# 3 个 scope:room / expert / user,各最多 10 条,按 updated_at desc
# 拼成 markdown 段落,prepend 到消息 content 前
# 用 <memory-context>...</memory-context> 包起来便于 LLM 识别
mem_ctx = await self._prefetch_memory(room_id, expert_id, user_id)
if mem_ctx:
    content = f"<memory-context>\n{mem_ctx}\n</memory-context>\n\n{content}"
```

**Sync**(大咖消息 + AI 回复后,fire-and-forget):
```python
# 1. LLM(claude-haiku 够用)按预设 prompt 提取事实
# 2. 解析返回 JSON: [{"content":..., "scope":"room|expert", "tags":[...]}, ...]
# 3. 逐条 INSERT 到 memories 表,source_message_id 关联原消息
# 4. 简单去重:content 完全相同跳过
```

**两个易踩的坑**(已在 §5.3 列):
- `asyncio.create_task` 必须 add 到 `self._bg_tasks: set`,否则 Python 3.11+ 弱引用模型下被 GC
- `_EXTRACT_PROMPT` 模板含 `{"content": ...}` JSON 示例,用 `.replace("{dialogue}", ...)` 而非 `.format()`,否则 `KeyError: '"content"'`

---

## 6. 云端部署目标

### 6.1 当前状态(本机版,Track A)

`~/.hermes/hermes-agent/` + launchd plist `ai.hermes.gateway` → 跑在 user 自己 Mac 上,连接 chat2go.cn 的 Supabase。**这是参考实现,不是生产方案**。

### 6.2 云端版本(你的目标)

- **部署目标**:`chat2go.ai` 主域(对比 `chat2go.cn` 跑老的本机 Hermes 兜底)
- **基础设施选型(待定,你可以推荐)**:
  - Fly.io / Railway / Cloudflare Workers(轻量,启动快)
  - 或 EC2 / Hetzner 之类(完整 Docker 容器,资源多)
- **多 expert 处理**:
  - MVP 阶段 1-3 个大咖,可以全部跑在同一进程里(每个 expert 一个 connection_key)
  - 也可以 1 expert 1 容器(隔离更彻底,但成本高)
- **持久化**:无需,所有状态都在 Supabase

### 6.3 凭证管理

每个大咖在网页生成 `c2g-key_xxx`(已实现 `expert_agent_keys` 表 + `generate_agent_key` RPC + admin UI)。你的后端用这个 key 调 `agent-auth/exchange` 拿 magiclink session。

云端部署时 token 的安全管理:
- 不能让所有 token 在容器环境变量里(信息泄漏)
- 推荐方案:大咖把 token 输入到 chat2go.cn 网页 → 写进 Supabase 某个表(只 service_role 可读)→ 后端启动时读
- 或:容器启动时给一个 expert_id 参数 → 现场用 service_role 生成 ephemeral magiclink

### 6.4 流量切换

`chat2go.cn`(GitHub Pages,本机 Hermes 接)→ `chat2go.ai`(目标新域,云端后端接)。
DNS / CNAME 切换在 chat2go 仓库 / chat2go.ai 注册商配。
A/B 阶段两套并存,**用同一份 Supabase 数据库**(bridge_state singleton 行要小心,可能多写者抢锁)。

---

## 7. 业务约束 / 不变量

你的后端必须满足:

1. **私聊频道 AI 不参与**:`channel='expert_user'` 直接跳过
2. **真人 @ 时 AI 不抢话**:消息含 `@<非 AI 名字>` 时跳过
3. **AI 消息字段**:role='ai',user_id=room.expert_id(占位,前端按 role 渲染),channel 跟入站消息一致
4. **focal_user 自动锁定**:不用你管,DB trigger 已处理
5. **quiz_mode pass relay**:不用你管,DB trigger 已处理
6. **重启信号**:监听 `bridge_state.restart_requested_at`,自我退出让外部拉起
7. **心跳**:每 5-15s 调 `bridge_pong()` RPC
8. **AI 名字显示**:用 `rooms.ai_name`(为空 fallback 「AI 助手」)

---

## 8. 本周已踩过的坑(避免重新踩)

完整列表见 `chat2go/docs/CHANGELOG-2026-05-15.md` + `CHANGELOG-WEEK-2026-W19.md`,精选:

1. **Supabase JS UMD 全局 `supabase`** → 前端变量必须叫 `sb`
2. **中文文件名上传 400** → 前端已处理(ASCII 清洗),你后端下载附件时按 storage_path 而非中文名
3. **Homebrew Python SSL** → 用 certifi 修复(参考 chat2go-agent `bridge.py` 头部 SSL fix)
4. **`room_members` RLS 递归** → SELECT 不能开 `using(true)`,通过 SECURITY DEFINER RPC 绕开
5. **AI 消息显示「我」bug** → 前端按 `role !== 'ai' && isOwn` 判断,你只管写 role='ai' 即可
6. **`model_usage` RETURNING * 报 42501** → INSERT 时用 `returning="minimal"`,因为 cost_usd 列被 GRANT 屏蔽
7. **JWT expired 卡死** → bridge 必须 50min refresh_session,加 token 续命循环
8. **macOS Python DNS getaddrinfo 卡死** → 见 §5.3 timeout 设计

---

## 9. MVP 阶段砍掉的功能(不用做)

- 计费 / 佣金分成 / 汇率快照(model_usage 表只写 input_tokens / output_tokens,**不填** cost_usd / commission_pct / exchange_rate / user_charge_cny)
- DSPy 平行记忆服务(chat2go-agent 接过 localhost:7788 的 DSPy,新版直接砍)
- 大咖私有 skill 模板(`~/.chat2go/skills/` override),改用大咖在 `rooms.system_prompt` 自由编辑
- Hermes brain shell-out 模式(`brains/hermes.py` 子进程 fork),改用 Hermes API / function call

---

## 10. 验收标准

你的云端 backend 部署到 chat2go.ai 后,以下场景必须 pass:

| # | 场景 | 验证方式 |
|---|---|---|
| 1 | 小白发消息 → AI 30 秒内回复 | 看 chat2go.ai 房间气泡 |
| 2 | 大咖纠正消息 → 几秒后看到 fact 写入 `memories` 表 | 查 DB:`select * from memories where scope='expert' order by created_at desc` |
| 3 | 新小白进房问类似问题 → AI 自动应用大咖记忆纠正 | 实测对话:不用提示 AI 应该主动用记忆 |
| 4 | 大咖私聊小白 → AI 不抢话 | channel=expert_user 消息 AI 无回复 |
| 5 | 三角色 / quiz_mode / focal_user | DB trigger 自动维护,前端显示正确即可 |
| 6 | 前端信号格在 30s 内显示绿色(在线)| `select last_seen from bridge_state` 在 30s 内 |
| 7 | model_usage 表每次 AI 回复后有新行 | 前端 token 进度环每次更新 |
| 8 | 大咖点重启按钮 → backend 5-10s 内重新连接 | 看 `restart_requested_at` + backend log |

---

## 11. 参考资料速查

- **`docs/REBUILD-HANDOFF.md`** —— 本文件,v0.2(2026-05-16 下午)
- **★ `docs/hermes-patches/`** —— **2026-05-16 实战跑通的本机 Hermes 改动 patch**,含完整 platform adapter(_prefetch_memory / _sync_memory / bridge_pong 心跳 / model_usage token 写入 / chat2go ack 静默)+ README 说明如何 apply。**这是当前生产实际在跑的代码,推荐作为重建的参考**
- **`docs/HANDOFF.md`** — 完整技术蓝图(本文件的母版,前 v0.1 → 现已升级到 chat2go.ai 主域)
- **`docs/AGENT_DESIGN.md`** — Phase 2 Skills / RAG 设计文档
- **`docs/CHANGELOG-2026-05-15.md`** — 昨天 47 commit 摘要,memory 6 层 bug 链全在
- **`docs/CHANGELOG-WEEK-2026-W19.md`** — 本周 249 commits 周报
- **chat2go-agent**(已归档,git tag `archived-v0.2-pre-hermes`)— chat2go_agent/memory.py 是 sync_memory 最早实现,**踩坑材料,不建议直接抄**(参考用)。物理位置 `~/chat2go-archive/chat2go-agent/`
- **`~/.hermes/hermes-agent/gateway/platforms/chat2go.py`** — 当前生产实际跑的代码(2026-05-16 PID 74319 在跑,~700 行,含 23 条 memory 实测产出),已快照到 `docs/hermes-patches/02-chat2go-platform-adapter.patch`
- **Supabase Dashboard** → SQL Editor 可查所有表的当前状态

---

## 12. 给外部 LLM 的最终 prompt 模板(把这段贴进去)

```
你是 chat2go.ai 的后端工程师。读 docs/REBUILD-HANDOFF.md(本文件)+ 整个 chat2go 仓库代码,
然后用你选定的技术栈(建议 TypeScript + Deno,或 Python + FastAPI)重新实现 backend。

目标:部署到云端(平台你推荐),让 chat2go.ai 主域跑你的 backend,功能跟 chat2go.cn 完全一样。

前端代码不要改。只满足 §3 的契约即可。

§5 的 memory 学习闭环是产品核心,必须实现 §5.5 的选项 (a)。

§10 的 8 个验收场景全部 pass 才算交付。

如果有不清楚的地方,先列假设清单回来跟我确认,不要瞎猜。
```

---

> 本 handoff doc draft v0.1 由 Track A 跑通 Phase 1-3 后写成。
> 后续(同日 / 几天内)随 Phase 4 + 外部 LLM 反馈持续迭代。
