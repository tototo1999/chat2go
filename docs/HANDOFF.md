# Chat2GO 技术交接文档

> 本文档为 vibe-coding agent 配合 GitHub 代码库（https://github.com/tototo1999/chat2go）独立重建 Chat2GO 的完整技术蓝图。
> 阅读顺序建议：1️⃣ 项目定位 → 2️⃣ 数据模型 → 3️⃣ 前端架构 → 4️⃣ AI Bridge → 5️⃣ Edge Functions → 6️⃣ 部署 → 7️⃣ 关键决策与踩坑。
> 最后版本快照：`v0.6.8-voice-clear-fix`（2026-05-13）。

---

## 1. 项目定位

Chat2GO 是 **AI marketplace** ——「行业大咖 × AI × 小白用户」三方协作平台。

- **大咖**（expert）：行业从业者，在「Chat 调试室」里陪小白调 AI。
- **小白**（user）：终端用户，跟随大咖学习 AI 用法。
- **AI**：第三方（Claude / 后续可扩展 Gemini/GPT/...）通过 bridge 接入，参与三方对话。

最终形态：每个大咖向小白「交付」一个专属 AI 助手（Phase 4 的 Go 交付室，尚未开发）。

**域名**：chat2go.cn（GitHub Pages 托管，CNAME 文件指向）。

---

## 2. 技术栈

| 层 | 技术 |
|---|---|
| 前端 | **纯 HTML / CSS / JS**，无框架。三个核心页面：`index.html`、`login.html`、`chat.html` |
| 字体 | Noto Serif SC（标题）/ Noto Sans SC（正文）via Google Fonts |
| 后端 / 数据 | **Supabase**（PostgreSQL + Auth + Realtime + Storage） |
| AI Bridge | **bridge.py**（Python asyncio，本地运行，不在 git） |
| Edge Function | **Deno**（`supabase/functions/`，备用） |
| AI Provider | Anthropic Claude（默认 `claude-sonnet-4-5`，房间级可覆盖） |
| JS 依赖 | **vendor/** 本地化：supabase-js / marked / html2pdf；CDN 作 fallback |
| Python 依赖 | supabase, httpx, certifi, pypdf, python-docx（在 `.venv` 中） |

---

## 3. 目录结构

```
chat2go/
├── index.html              # 落地页（大咖卡片 + Follow 入口）
├── login.html              # 登录 / 注册（含昵称、角色选择）
├── chat.html               # 调试室主界面（2700+ 行，核心）
├── onboarding.html         # 大咖入住流程（建房+ai_name 设置）
├── bridge.py               # AI Bridge（gitignored，本地运行）
├── CNAME                   # chat2go.cn
├── CLAUDE.md               # 项目上下文（喂给 Claude Code）
├── vendor/                 # 本地化 JS 依赖
│   ├── supabase.js
│   ├── marked.min.js
│   └── html2pdf.bundle.min.js
├── supabase/
│   ├── config.toml
│   ├── migrations/         # 22 个迁移文件
│   └── functions/
│       ├── chat-ai/        # Deno Edge Function（备用）
│       └── agent-auth/     # 大咖 agent 用 key 换 session
├── docs/
│   ├── AGENT_DESIGN.md     # 自研 Agent 设计文档
│   ├── TOMORROW.md         # 决策记录
│   └── HANDOFF.md          # 本文档
└── logs/
    ├── bridge.log
    └── bridge.error.log
```

---

## 4. 数据模型（PostgreSQL via Supabase）

> 全表 RLS 默认开启。下方仅列字段定义和关键策略；完整 SQL 见 `supabase/migrations/`。

### 4.1 `rooms` — 调试室
```sql
id              uuid primary key
name            text not null              -- 房间名（如「森山大道 的 Chat」）
industry        text not null              -- 行业（决定 system prompt）
expert_id       uuid → auth.users          -- 房主大咖
status          text default 'active'
model           text                       -- 房间级 AI model 覆盖（可空）
system_prompt   text                       -- 房间级 system prompt 覆盖（可空）
ai_name         text                       -- AI 在本房显示名，空 → 'AI 助手'
brain           text in ('builtin','hermes','auto')  -- agent 运行时
commission_pct  numeric default 0.15       -- 佣金比例
exchange_rate_to_cny numeric default 7.20  -- USD→CNY 汇率（快照）
invite_token    uuid unique not null       -- 邀请链接 token
created_at      timestamptz default now()
```

### 4.2 `messages` — 消息
```sql
id           uuid primary key
room_id      uuid → rooms(id) on delete cascade
user_id      uuid → auth.users            -- AI 消息用大咖 user_id 写入
role         text not null                -- 'user' | 'expert' | 'ai'
content      text not null
type         text default 'text'          -- 'text' | 'markdown'
attachments  jsonb default '[]'           -- [{name,url,size,mime_type,storage_path}]
channel      text default 'main' check (in ('main','expert_user'))
created_at   timestamptz default now()
```
- `channel='main'`：三方共聊，AI 会响应。
- `channel='expert_user'`：大咖 ↔ 小白私聊，AI 不参与。
- Realtime publication: `alter publication supabase_realtime add table messages;`

### 4.3 `profiles` — 用户角色与昵称
```sql
user_id      uuid primary key → auth.users
role         text in ('user','expert') default 'user'
display_name text
created_at, updated_at
```
- 注册时由 trigger `handle_new_user()` 自动建行；`raw_user_meta_data` 里 `role` / `display_name` 决定值。
- RLS：所有登录用户可读；只能更新自己的。

### 4.4 `room_members` — 房间成员表
```sql
room_id   uuid → rooms
user_id   uuid → auth.users
joined_at timestamptz default now()
primary key (room_id, user_id)
```
- 建房时触发器 `trg_auto_add_expert_as_member` 自动把大咖加成成员。
- RLS：登录用户可 INSERT 自己（小白 instant follow）；只能 SELECT 自己的成员行（注意 SELECT 不能开成 `true`，会引发 RLS 递归 → 见 `20260511200000_fix_room_members_rls_recursion.sql`）。

### 4.5 `follow_requests` — 历史审核流（已废弃但保留表）
```sql
expert_id, user_id, status('pending'|'approved'|'rejected'), created_at
```
- 2026-05-12 起 instant-follow，前端不再写入；表保留作历史与 fallback 数据。

### 4.6 `expert_agent_keys` — 大咖 agent 连接密钥
```sql
id, expert_id, name, key_hash (sha256), key_prefix, last_used_at, last_used_ip,
expires_at, revoked_at, created_at
```
- 大咖在本地跑 bridge.py，用 `c2g-key_xxx` token 通过 `/functions/v1/agent-auth/exchange` 换 Supabase session。
- RPC：`generate_agent_key()` / `list_agent_keys()` / `revoke_agent_key(id)`。

### 4.7 `model_usage` — 每次 LLM 调用计费
```sql
id, message_id → messages, room_id, expert_id, triggered_by, model
input_tokens, output_tokens
cache_creation_input_tokens, cache_read_input_tokens   -- prompt caching
cost_source ('online'|'local'), cost_usd
commission_pct, exchange_rate, user_charge_cny         -- 快照
created_at
```
- View `room_costs`：按 room_id 聚合 token、cost_usd、user_charge_cny。
- RLS：大咖看自己房；小白看自己触发的；`cost_usd` 通过 view 对小白隐藏。

### 4.8 `memories` — 记忆（Phase A 只读）
```sql
id, scope ('room'|'expert'|'user'), scope_id, content, tags text[],
source_message_id → messages, created_at, updated_at
```
- Phase A 只放只读 prefetch；Phase B 由 lessons 自动沉淀写入。

### 4.9 RPC（公开 / SECURITY DEFINER）

| RPC | 用途 |
|---|---|
| `get_expert_follower_count(p_expert_id uuid) → int` | 落地页 anon 也可读 |
| `get_expert_followers(p_expert_id uuid) → table(...)` | follower 列表（authenticated） |
| `join_room_by_token(token uuid) → uuid` | 邀请链接加入房间（备用） |
| `generate_agent_key(name) / list / revoke` | 大咖管理 agent key |
| `agent_auth_exchange(key) → OTP` | bridge.py 启动用 |

### 4.10 Storage Bucket
- `chat-uploads`（public）：消息附件（图片 / pdf / docx / csv / json / xml / html / md / txt）。
- **文件名清洗**：上传前把中文转 ASCII（否则 Supabase 返回 400）。

---

## 5. 前端架构

### 5.1 全局样式 token（每个页面 `<style>` 顶部）
```css
:root {
  --teal:    #1D9E75;
  --teal-50: #E1F5EE;
  --teal-100:#B6E3D2;
  --teal-600:#0F6E56;
  --bg:      #FAFAF8;
  --bg2:     #DDDCD6;
  --border:  rgba(60,58,54,0.12);
  --text:    #1a1a18;
  --text2:   #5f5e5a;
  --text3:   #888780;
}
```
- 角色色：小白黄 `#E5B85A` / 大咖紫 `--purple` / AI 绿 `--teal`。
- 警告红：`#DC2626`，浅红底 `#FEE2E2` / 浅红边 `#FECACA`。

### 5.2 `index.html` — 落地页（420 行）

- 顶部 nav：Logo + 登录/已登录用户 pill。
- Tagline：「真人大咖 × AI，<em>这就带你飞</em>」
- 4 张 expert-card（grid 2x2）：
  - 唯一启用：`fbb9ab4b-dc51-40f8-800e-e824ff6fb8c0` = 「森山大道 san」（fortune teller）。
  - 其它 3 张 `.disabled`：Tony 哥 / 戴维斯 / 大白老师。
- 每张激活卡内含 follow 胶囊 `<div class="follow-pill">`：♥ 关注按钮 + follower 数（点数字打开 modal）。
- JS 关键函数：
  - `followExpert(btn)` → 插入 `room_members(room_id, user_id)`（依赖 RLS instant follow）→ 跳 `/chat.html?room=<id>`
  - `loadFollowerCounts()` → 调 `get_expert_follower_count` RPC
  - `openFollowers(btn)` → 调 `get_expert_followers` RPC，渲染 modal

### 5.3 `login.html` — 登录注册（208 行）

- Tab 切换 Login / Register。
- Register 三字段：邮箱、密码、昵称、角色（user/expert）。
- 调 `sb.auth.signUp({ email, password, options: { data: { display_name, role } }})`。
- 注册成功 → 跳 `/`（小白）或 `/onboarding.html`（大咖）。
- **关键：邮箱验证已关掉**（migration `986e0a8` 同步配置；Supabase Dashboard → Auth → Email confirm = off）。

### 5.4 `chat.html` — 调试室主界面（2700+ 行）

整体三栏布局：

```
┌──────────────┬─────────────────────────────────────┐
│  sidebar     │  chat-panel                         │
│  (220px)     │  ┌─────────────────────────────┐    │
│              │  │ chat-head（metrics+status） │    │
│              │  ├─────────────────────────────┤    │
│ - 顶部胶囊   │  │ messages 列表                │    │
│   (大咖人设  │  │                              │    │
│    名字)     │  │  msg-group:                  │    │
│              │  │   ┌─────────────────────┐    │    │
│ - ToDoList   │  │   │ av │ meta+bubble    │    │    │
│   3 父项 +   │  │   │    │ +rate(✓/✗)     │    │    │
│   9 子项     │  │   └─────────────────────┘    │    │
│              │  ├─────────────────────────────┤    │
│ (rooms-list  │  │ input-area                  │    │
│  hidden)     │  │ (role-badge|📎|🎙|input|GO) │    │
└──────────────┴─────────────────────────────────────┘
```

#### 5.4.1 关键全局状态变量
```js
let currentUser           // Supabase session.user
let currentRole           // 'user' | 'expert'
let currentDisplayName    // profiles.display_name
let currentRoom           // 当前打开的房（含 expert_id, ai_name, model...）
let currentChannel        // 'main' | 'expert_user'
let pendingAttachments    // 待上传附件队列
let recognition           // SpeechRecognition 实例
let voiceTextBefore       // 录音前 input 已有的文本（修复发送残留 bug 关键）
```

#### 5.4.2 init / 角色加载流程（`init()`）
```
session → currentUser
  ↓
profiles.select() → currentRole + currentDisplayName
  ↓
角色为 expert → ensureExpertRoom()（没房则建一个）
  ↓
一次性清理 name='Todo list' 的残留房（chore）
  ↓
loadRooms()（rooms-list 已 display:none，但 auto-open 第一个房逻辑保留）
  ↓
小白 → subscribeMyMemberships()
  ↓
URLSearchParams.room → openRoomById(roomId)
```

#### 5.4.3 顶部 sidebar 胶囊
- HTML：`<div class="sidebar-room-title" id="sidebarRoomTitle">`（绿底白字 serif）。
- 进入房间时 `openRoom(room)` 内查 `profiles.display_name`，但**优先级**：
  ```js
  const EXPERT_PERSONAS = {
    'fbb9ab4b-dc51-40f8-800e-e824ff6fb8c0': '森山大道 san',
  }
  ```
  → 「人设名」（公开），与首页卡片一致；fallback 才是 `display_name`（账户昵称）。
- **重要约定**：私人 `display_name`（如「我是大咖我怕谁」）≠ 公开 persona 名。未来应在 `profiles` 加 `public_name` 列。

#### 5.4.4 ToDoList（前端 localStorage 本地状态）
- 3 个父胶囊（我是谁? / 我从哪里来? / 我要去哪里?），无勾选框，左边 `+` 按钮（展开 → 旋 45° 变 ×）。
- 每父项展开后 3 个子 ☐：
  - who → 五行 / 强弱 / 对错
  - from → 过去 / 三个 / 节点
  - to → 未来 / 三个 / 节点
- `localStorage` keys：
  - 展开状态 `c2g_todog_<group>` ('1'/'0')
  - 子项 done `c2g_todo_<key>` ('1'/'0')
- 入口函数：`toggleTodoGroup(el)` / `toggleTodo(el)` / `restoreTodos()`。

#### 5.4.5 消息渲染 `appendMessage(msg)`
- 三种 role 三色 bubble：`.msg-bubble.user|.expert|.ai`。
- AI 消息可能 markdown：通过 `looksLikeMarkdown(content)` 嗅探或 `type === 'markdown'` 强制；marked.js 渲染，附带 `.btn-pdf` 导出 PDF（html2pdf.js）。
- **AI 头像可点击编辑名字**（大咖才能）：`onclick="editAIName()"` → 写 `rooms.ai_name`。
- 附件 `attachments` 渲染：图片直接 `<img>`，其它显示文件卡片。
- 每条都带：复制按钮（base64 绕过 HTML 转义）、ts。
- AI 消息额外底栏 `.msg-rate-bar`：✓/✗ 评价按钮
  - 函数 `rateMessage(btn, msgId, val)`，状态存 `c2g_rate_<msgId>`。
  - 互斥（一次只有一个 active），再点同一个取消。

#### 5.4.6 发消息 `sendMessage()`
- 取 input.value，trim；如果有附件等所有上传完才发。
- INSERT messages 表，role 由当前用户角色决定（expert / user）。
- **重要**：发送时除了清 `input.value`，还要清 `voiceTextBefore`（语音输入缓存）—— 否则录音中发送会被 onresult 重新写回。

#### 5.4.7 Realtime 订阅 `subscribeRoom(roomId)`
```js
sb.channel(`room-${roomId}`, { config: { presence: { key: currentUser.id } } })
  .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'messages',
        filter: `room_id=eq.${roomId}` }, ...)
  .on('presence', { event: 'sync' }, renderPresence)
  ...
```
- 收到 INSERT → 去重 (`data-msg-id`)，appendMessage。
- AI INSERT → loadRoomCost(roomId) 延迟 500ms 刷新成本徽章。

#### 5.4.8 轮询兜底
- 每 5 秒（`POLL_INTERVAL = 5000`）跑一次轮询补漏，防 Realtime 断线漏消息。

#### 5.4.9 语音输入（Web Speech API）
- `recognition.lang = 'zh-CN'`、`continuous=true`、`interimResults=true`。
- onresult 把 `voiceTextBefore + finalText + interimText` 写回 input。
- onend 如果 `isRecording=true` 自动再 `start()`（用户停顿不停录）。
- Chrome / Edge / Safari 支持；不支持的浏览器 toast 提示。

#### 5.4.10 PDF 导出
- `exportPdf(targetId, filename)`：html2pdf 把 `.md-body` 内容生成 PDF，A4 边距固定。
- 浏览器端生成（不依赖后端）。

#### 5.4.11 模型名展示 `shortModelName(model)`
- 拆 provider / model，两段都 cap，用 `·` 连接。
- `PROVIDER_LABELS` 修正大小写：`openai → OpenAI`, `deepseek → DeepSeek`, etc。
- `MODEL_CONTEXT_WINDOWS` 表给 chat-head 的 token 进度条用。

### 5.5 `onboarding.html` — 大咖入住（201 行）

- 注册角色 = expert 后落到这里：
- 1) 填昵称 → update profiles
- 2) 建房（industry 必选）→ insert rooms（trigger 自动加 room_members 自己）
- 3) 设置 ai_name（可选）→ update rooms.ai_name
- 完成 → 跳 `/chat.html`

---

## 6. AI Bridge（bridge.py）

> 不在 git，但接口和数据流必须保持稳定。重建时按本节实现。

### 6.1 启动流程
```
读取 .env（ANTHROPIC_API_KEY, AGENT_KEY=c2g-key_xxx）
  ↓
POST /functions/v1/agent-auth/exchange { key: AGENT_KEY }
  ↓ { token_hash, email, expert_id }
sb.auth.verifyOtp({ token_hash, type: 'magiclink' })
  ↓ session（自动续命）
sb.realtime.channel('messages') 订阅 INSERT
  +
每 5 秒轮询 messages（兜底）
```

### 6.2 触发条件
对一条新 message：
1. `role == 'user'` 或 `role == 'expert'` → 需要 AI 回应；
2. `channel == 'main'`（私聊频道不触发）；
3. `expert_id` 是本 bridge 绑定的大咖；
4. 消息不是 AI 自己写的（user_id ≠ 大咖 id 或 role ≠ ai 防自激）。

### 6.3 AI 调用 `call_claude(...)`
```
1. 拉 room.system_prompt，否则按 industry 用 INDUSTRY_PROMPTS（见 6.5）
2. 拉最近 N 条 messages（channel=main）作为上下文
3. 处理 attachments：
   - text/pdf/docx → 下载 + 抽文本 + 拼 system message
   - image → 直接 image_url 传 Vision
4. anthropic API 调用，default model = 'claude-sonnet-4-5'
   - 房间级 rooms.model 覆盖
5. 返回 text → 判定 type:
   - 含 # ## ``` 等 → 'markdown'
   - 否则 'text'
6. INSERT messages（用大咖 user_id 写 role='ai'）
7. INSERT model_usage 行（含 cache_creation_input_tokens / cache_read_input_tokens）
```

### 6.4 计费写入
- 每次 LLM 调用结束后 insert model_usage 一行；金额字段全部在 insert 时锁定（commission_pct/exchange_rate 快照）。
- 前端 `loadRoomCost(roomId)` 用 `room_costs` view 聚合。

### 6.5 行业 system prompt（共 6 个）

`docs/AGENT_DESIGN.md` 有完整版；摘要：
- 外贸（合同/信用证/报关）
- 健身（CRM/训练计划/营养）
- 地产（带客/谈判/合同）
- 教育（讲解/题库/规划）
- 量化（回测/因子/Python）
- 医疗（症状/病历，强调「以医生判断为准」）
- 算命（fortune teller，新加的 demo line，prompt 待补）

### 6.6 SSL 修复
Homebrew Python 的 SSL 证书路径不对，websocket 连接会失败；用 `certifi.where()` 注入 `os.environ['SSL_CERT_FILE']`。

---

## 7. Edge Functions（Deno）

> 注意：当前主链路走 bridge.py，Edge Functions 为备用 / 辅助。

### 7.1 `chat-ai` (`supabase/functions/chat-ai/index.ts`)
- POST `/functions/v1/chat-ai`，Body: `{ room_id, messages }`。
- Server-side Claude 调用（备用：当大咖没跑 bridge 时可降级用 Edge Function）。
- 行业 prompt 同 6.5 表，硬编码在 ts 里（保持同步）。

### 7.2 `agent-auth` (`supabase/functions/agent-auth/index.ts`)
- POST `/functions/v1/agent-auth/exchange`，Body: `{ key }`。
- 用 SERVICE_ROLE_KEY：
  - sha256 hash key → 查 expert_agent_keys；
  - 未 revoked / 未过期 → 生成 magiclink OTP（admin.generateLink）；
  - 返回 `{ token_hash, email, expert_id }`。

---

## 8. 关键流程图

### 8.1 注册 → 落地

```
register form
  ↓
sb.auth.signUp({ email, pw, options:{ data:{ role, display_name }} })
  ↓
auth.users INSERT → trigger handle_new_user()
  ↓
profiles INSERT (role, display_name)
  ↓
role = 'expert' → /onboarding.html
role = 'user'   → /
```

### 8.2 Follow 大咖（instant，2026-05-12 之后）

```
landing page 点 ♥
  ↓
sb.from('rooms').select('id').eq('expert_id', expertId).limit(1)
  ↓ roomId
sb.from('room_members').insert({ room_id: roomId, user_id: me })
  ↓ RLS 允许（user_id = auth.uid()）
跳转 /chat.html?room=<roomId>
```

### 8.3 发消息 → AI 回复

```
小白在 input 敲字 / 语音 → sendMessage()
  ↓
messages.insert({ room_id, user_id, role:'user', channel:'main', content })
  ↓ Realtime broadcast
[ 前端 ] appendMessage（消息出现在小白屏幕）
[ 大咖端 ] appendMessage（实时看到）
[ bridge.py ] onResult → 满足触发条件 → call_claude(...)
  ↓
messages.insert({ role:'ai', user_id: expert_id, content, type })
model_usage.insert({ tokens, cost, ... })
  ↓ Realtime broadcast
[ 三方 ] appendMessage（AI 回复出现）
[ 前端 ] loadRoomCost(roomId)（500ms 后刷新成本徽章）
```

### 8.4 大咖 agent 启动鉴权

```
bridge.py 启动
  ↓ POST /functions/v1/agent-auth/exchange { key }
sha256 → expert_agent_keys 查 → admin.generateLink magiclink
  ↓ { token_hash, email, expert_id }
sb.auth.verifyOtp({ token_hash, type:'magiclink' })
  ↓ session（带 refresh_token）
订阅 Realtime + 轮询
```

---

## 9. 部署

### 9.1 前端（GitHub Pages）

- 仓库：`tototo1999/chat2go` → main 分支。
- 直接静态托管（无构建）。push main 后约 30~90s 全球生效。
- CNAME 文件指向 `chat2go.cn`（在 DNS 端配 A / CNAME → GH Pages）。

### 9.2 Supabase

- Project URL / anon key 硬编码在前端三个 HTML 顶部 `<script>` 段。
- Migrations 用 `supabase db push` 应用（或 SQL Editor 手动跑）。
- Edge Functions：`supabase functions deploy chat-ai` / `agent-auth`。
- Environment：`ANTHROPIC_API_KEY`、`SUPABASE_URL`、`SUPABASE_SERVICE_ROLE_KEY`。

### 9.3 Bridge.py（本地）

- macOS：`.venv` + Homebrew Python 3.11+；`source .venv/bin/activate`。
- `.env`：
  ```
  ANTHROPIC_API_KEY=sk-ant-...
  AGENT_KEY=c2g-key_...
  SUPABASE_URL=https://xxx.supabase.co
  SUPABASE_ANON_KEY=eyJ...
  ```
- 启动：`python bridge.py`；logs 到 `logs/bridge.log` / `bridge.error.log`。

---

## 10. 关键技术决策与踩坑

### 决策

| # | 决策 | 原因 |
|---|---|---|
| 1 | 自研 Agent，不依赖 Hermes | 控制力 + 不锁死生态 |
| 2 | 纯静态前端（无 React/Vue） | GitHub Pages 直发；JS 库本地化避免 CDN 不稳 |
| 3 | Bridge.py 本地运行 | MVP 阶段大咖自己跑；后期可云端部署 |
| 4 | 术语「大咖」/「小白」 | UI 友好；数据库 role 字段保持英文 `expert`/`user` |
| 5 | AI 消息用大咖 user_id 写 | role='ai' 决定显示，user_id 字段只为 RLS |
| 6 | follow 改 instant（2026-05-12） | 砍 approval 流减摩擦；保留 follow_requests 表 |
| 7 | 邮箱验证关掉 | demo 阶段；上线前需重开 |
| 8 | profiles.display_name 是私昵称 | 公开 persona 名硬编码在 EXPERT_PERSONAS（未来抽 DB 列） |

### 踩坑

1. **Supabase JS UMD 注入全局 `supabase`** → 本地变量必须命名为 `sb`，否则冲突。
2. **中文文件名 400** → 上传前 ASCII 清洗（保留扩展名）。
3. **Homebrew Python SSL** → certifi 修复，否则 websocket 连不上。
4. **CDN 国内不稳** → JS 依赖全部本地化到 `vendor/`。
5. **`room_members` RLS 递归** → SELECT 不能开 `using (true)`，会和 rooms 的 SELECT 互相依赖；解法见 `20260511200000_fix_room_members_rls_recursion.sql`。
6. **AI 消息显示「我」的 bug** → bridge 用大咖账号写 role='ai'，前端必须用 `role !== 'ai' && isOwn` 判断，不能光看 user_id。
7. **deleteRoom RLS 静默拦截** → DELETE 失败 RLS 不会报错；必须 `.select()` 拿返回行数辨别（`25dcd11`）。
8. **语音输入发送残留** → 录音中点发送，input 清了但 `voiceTextBefore` 缓存被 onresult 再写回；修复见 `c7d77d9`。
9. **rooms.active 状态色 = mint pill = todo-head 一模一样** → 视觉混淆；用户以为是 bug。建议未来把 active 房间样式做出区分。
10. **Edge Function `dollar quote`** → Supabase SQL Editor 对 PL/pgSQL `$$ ... $$` 兼容差，instant follow 改回直白 RLS 而非 RPC。

---

## 11. 命名约定

- **变量**：JS 全部 camelCase；常量 SCREAMING_SNAKE_CASE。
- **DB**：snake_case；表名复数（rooms, messages, profiles）。
- **角色**：DB `'user'` / `'expert'` ；UI 「小白」/「大咖」/「AI 助手」。
- **commit message**：中文，格式 `类型: 描述`
  - `feat:` 新功能 / `fix:` 修复 / `ui:` 仅样式 / `refactor:` / `chore:` / `content:` 文案 / `docs:`
- **tag**：`vX.Y.Z-slug`（如 `v0.6.7-feedback-loop`）。

---

## 12. 未完成与下一步

### Phase 1（MVP）— 最优先
- [ ] **大咖纠正自动沉淀**（Learner agent 提取规则 → memories / lessons 表）
- [ ] **PDF 真生成**（服务端 weasyprint/reportlab）
- [ ] **Multi-model Router**（按任务复杂度选 sonnet/haiku，省 60% 成本）

### Phase 2 — 壁垒
- [ ] **知识库 RAG**（大咖资料 → pgvector → 检索增强）
- [ ] **Skills 系统**（skill.yaml + triggers + templates + lessons）

### Phase 3 — 体验
- [ ] 图片 OCR / Web 搜索（Tavily / SerpAPI）/ 服务端语音转文字（Whisper）

### Phase 4 — 商业化
- [ ] Go 交付室（小白独立用 AI 的私人空间）
- [ ] 模型计费表 + 大咖分成
- [ ] 部署迁移（GH Pages → Vercel / Cloudflare Pages）

### UX 待办（短期）
- [ ] 把 `EXPERT_PERSONAS` 硬编码挪进 `profiles.public_name` 列
- [ ] sidebar room-item active 状态视觉与 todo-head 区分
- [ ] 移动端 UI 对齐打磨
- [ ] 评价按钮 → DB `message_ratings` 表，喂回 AI 训练

---

## 13. 重要文件入口（速查）

| 想做的事 | 改哪里 |
|---|---|
| 改首页 expert 卡片 | `index.html` line ~288（`.expert-card`） |
| 加新 expert persona 名 | `chat.html` 的 `EXPERT_PERSONAS` |
| 改 AI 行业 prompt | `bridge.py`（INDUSTRY_PROMPTS） + `supabase/functions/chat-ai/index.ts` 双写 |
| 改默认 model | `bridge.py`（DEFAULT_MODEL）；房间级 → `rooms.model` |
| 加新行业 | `chat.html` 新建房模态框 + bridge.py 加 prompt |
| 改样式 token | 每个 HTML 顶部 `:root { --teal: ... }` |
| 改 DB schema | 新增 `supabase/migrations/YYYYMMDDHHMMSS_xxx.sql` |
| 改 RLS | 同上，注意 room_members 递归坑 |
| 调对话气泡颜色 | `chat.html` `.msg-bubble.user/.expert/.ai` |
| 改 ToDoList 文字 | `chat.html` `.todo-section` HTML 块 + `data-todo` key |

---

## 14. 重建 checklist（给 vibe-coding agent）

按此顺序可以从零搭起：

1. ✅ 起 Supabase project，跑全部 `supabase/migrations/*.sql`。
2. ✅ Supabase Dashboard → Auth → Email confirm = off（demo 阶段）。
3. ✅ Storage 建 bucket `chat-uploads`（public）。
4. ✅ 把 `supabase/functions/{chat-ai, agent-auth}` deploy 上去；配 env。
5. ✅ 前端三个 HTML 顶部填 `SUPABASE_URL` / `SUPABASE_ANON_KEY`。
6. ✅ GitHub Pages 启用，CNAME → 你的域名。
7. ✅ 注册一个 expert 账号，跑 `onboarding.html` 建房，记下 `expert_id`。
8. ✅ 把 `EXPERT_PERSONAS` 里替换成你的 expert_id 和 persona 名。
9. ✅ 在大咖账号下生成 agent_key（`generate_agent_key('local')`）。
10. ✅ 本地写 bridge.py（参考 6 节），跑起来。
11. ✅ 注册一个 user 账号，落地页 follow 大咖，进调试室聊一句，看 AI 回应。

完成后即拥有一个完整的 v0.6.8 Chat2GO。

---

> 📌 本文档随代码演进。每次重大改动应同步更新对应节。
> 维护者：项目 owner / 你（vibe-coding agent）。
