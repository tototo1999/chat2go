# Chat2GO.ai 技术交接文档

> 本文档为 vibe-coding agent 配合双仓库代码独立重建 Chat2GO.ai 的完整技术蓝图。
> 阅读顺序建议:① 仓库结构 → ② 数据模型 → ③ 前端 → ④ Agent 包 → ⑤ Edge Functions → ⑥ 部署 → ⑦ 已知缺陷 → ⑧ 决策与踩坑。
> 最后快照:2026-05-14(含 focal_user / quiz_mode / pass_relay / bridge_state)。
> 上一版本文档:2026-05-13 v0.6.8-voice-clear-fix(本文档全面替换该版本)。

---

## 1. 项目定位

Chat2GO.ai 是 **AI marketplace** ——「行业大咖 × AI × 小白用户」三方协作平台。

- **大咖**(expert):行业从业者,在「Chat 调试室」陪小白调 AI,被 follower 关注。
- **小白 / 八字主**(focal user):第一个 follow 进房的非大咖用户,该房间的「主角」。
- **路人**(audience):房间已有 focal 之后再加入的成员,可观摩但不参与计费。
- **AI**:第三方 LLM(Claude / Gemini / 国产模型) 通过 agent bridge 接入,参与三方对话。

最终形态:每个大咖向小白「交付」一个专属 AI 助手(Phase 4 的 Go 交付室,尚未开发)。

**域名**:chat2go.ai(GitHub Pages 托管,CNAME 文件指向)。

---

## 2. 仓库结构 ★

Chat2GO.ai 实际由**两个独立仓库**组成。上一版 HANDOFF 没记这点,容易遗漏:

### 2.1 `chat2go/`(本仓库)
前端 + Supabase 资产。GitHub: `tototo1999/chat2go`。

```
chat2go/
├── index.html              # 落地页(expert 卡片 + follow 入口)
├── login.html              # 登录 / 注册(含昵称、角色选择)
├── chat.html               # 调试室主界面(140KB+,核心)
├── onboarding.html         # 大咖入住流程(建房 + ai_name 设置)
├── admin.html              # 管理后台(房间观测 / 清空消息)
├── CNAME                   # chat2go.ai
├── CLAUDE.md               # 项目上下文(喂给 Claude Code)
├── vendor/                 # 本地化 JS 依赖(supabase / marked / html2pdf)
├── supabase/
│   ├── config.toml
│   ├── migrations/         # 34 个迁移文件(到 2026-05-14)
│   └── functions/
│       ├── chat-ai/        # Deno Edge Function(备用,当 bridge 离线时降级)
│       └── agent-auth/     # connection_key → magiclink OTP
├── docs/
│   ├── AGENT_DESIGN.md     # 自研 Agent 设计文档
│   ├── HANDOFF.md          # 本文档
│   └── TOMORROW.md         # 旧的决策记录(2026-05-09 起点)
└── logs/                   # 旧 bridge 残留日志(已迁出)
```

### 2.2 `chat2go-agent/`(独立仓库,在 `~/chat2go-agent/`)

Python 包 `chat2go_agent`(原 chat2go/bridge.py 已迁出并扩成完整包)。

```
chat2go-agent/
├── pyproject.toml          # name='chat2go-agent', version='0.2.0'
├── start.sh                # 杀重复进程 + 拉起 venv + 启动
├── ai.chat2go.bridge.plist # launchd KeepAlive 配置
├── credentials.yaml.example
├── chat2go_agent/
│   ├── __main__.py         # CLI: connect / rooms / send / set-* / whoami
│   ├── bridge.py           # 主循环(726 行)
│   ├── config.py           # SUPABASE_URL / credentials.yaml 加载
│   ├── auth.py             # connection_key → magiclink OTP → session
│   ├── soul.py             # SKILL.md / SOUL.md 加载
│   ├── memory.py           # Phase A prefetch + Phase B sync(★ 有 RLS / GC 隐患)
│   ├── prompt_builder.py   # system prompt 拼装
│   ├── attachments.py      # 文件下载 / 文本提取(pypdf / python-docx)
│   ├── pricing.py          # 计费 + 汇率快照
│   ├── dspy_client.py      # 并行的 DSPy 记忆服务(localhost:7788)
│   ├── adapters/           # provider 抽象:anthropic / openai_compatible / gemini
│   ├── brains/             # 引擎抽象:builtin / hermes
│   ├── skills/             # 内置 6 行业 skill(SKILL.md frontmatter + body)
│   └── templates/SOUL.md.example
├── hermes_plugin/          # Hermes 集成(预留)
├── tests/
└── logs/
    ├── bridge.log
    └── bridge.error.log
```

**关键约定**:
- 大咖私有 skill 放 `~/.chat2go/skills/`(覆盖同名内置)
- 大咖人格 `~/.chat2go/SOUL.md`(可选)
- 凭证 `~/.chat2go/credentials.yaml` 或 `.env`

---

## 3. 技术栈

| 层 | 技术 |
|---|---|
| 前端 | **纯 HTML / CSS / JS**,无框架。5 个页面:`index.html` / `login.html` / `chat.html` / `onboarding.html` / `admin.html` |
| 字体 | Noto Serif SC(标题) / Noto Sans SC(正文) via Google Fonts |
| 后端 / 数据 | **Supabase**(PostgreSQL + Auth + Realtime + Storage) |
| Agent | **chat2go-agent** Python 包(独立仓库,本地 / launchd 运行) |
| Python | 3.10+,实测 3.14。依赖见 `pyproject.toml`(supabase / httpx / pyyaml / pypdf / python-docx) |
| Edge Function | **Deno**(`supabase/functions/`,备用 + agent-auth) |
| LLM Provider | **多 provider 并存**:Anthropic / OpenAI 协议(DeepSeek / Qwen / Kimi / GLM / Ollama) / Gemini / OpenRouter |
| 当前默认模型 | **`openrouter/google/gemini-2.5-pro`**(credentials.yaml 的 `defaults.model`;HANDOFF 旧版的 sonnet 已被覆盖) |
| Brain | **builtin**(自己拼 prompt 调 LLM) / **hermes**(shell out 到本地 hermes 二进制,复用 ~/.hermes 配置)/ auto |
| JS 依赖 | `vendor/` 本地化:supabase-js / marked / html2pdf;CDN 作 fallback |

---

## 4. 数据模型(PostgreSQL via Supabase)

> 全表 RLS 默认开启。下方仅列字段定义和关键策略;完整 SQL 见 `supabase/migrations/`。

### 4.1 `rooms` — 调试室
```sql
id                      uuid pk
name                    text not null              -- 房间名
industry                text not null              -- 行业(决定 skill / prompt)
expert_id               uuid → auth.users          -- 房主大咖
focal_user_id           uuid → auth.users          -- ★ 八字主(第一个非大咖加入者)
status                  text default 'active'
model                   text                       -- 房间级模型覆盖(provider/name 格式)
system_prompt           text                       -- 房间级 system prompt 覆盖
ai_name                 text                       -- AI 在本房显示名
brain                   text check (in ('builtin','hermes','auto'))
commission_pct          numeric default 0.15       -- 佣金比例
exchange_rate_to_cny    numeric default 7.20       -- 汇率快照
invite_token            uuid unique not null       -- 邀请链接 token
created_at              timestamptz default now()
```

### 4.2 `messages` — 消息
```sql
id           uuid pk
room_id      uuid → rooms(id) on delete cascade
user_id      uuid → auth.users on delete cascade   -- AI 消息用大咖 user_id 写入
role         text not null                          -- 'user' | 'expert' | 'ai'
content      text not null
type         text default 'text'                    -- 'text' | 'markdown'
attachments  jsonb default '[]'                     -- [{name,url,size,mime_type,storage_path}]
channel      text default 'main' check (in ('main','expert_user'))
ratings      jsonb default '{}'                     -- ★ 做题模式:{"<uid>": "up"|"down"}
created_at   timestamptz default now()
```

- `channel='main'`:三方共聊,AI 响应。
- `channel='expert_user'`:大咖 ↔ 小白私聊,AI **不参与**(bridge L221-224 直接 skip)。
- `ratings`:做题模式评价。任意成员双钩 up 才算 pass,会触发 `trg_relay_pass_to_private` 把摘要写到私聊频道。
- Realtime publication:`alter publication supabase_realtime add table messages;`

### 4.3 `profiles` — 用户角色与昵称
```sql
user_id      uuid pk → auth.users
role         text in ('user','expert') default 'user'
display_name text
created_at, updated_at
```

注册时由 trigger `handle_new_user()` 自动建行。`raw_user_meta_data` 里 `role` / `display_name` 决定值。

### 4.4 `room_members` — 房间成员
```sql
room_id   uuid → rooms
user_id   uuid → auth.users
joined_at timestamptz default now()
primary key (room_id, user_id)
```

- Trigger `trg_auto_add_expert_as_member`:建房时自动加大咖成员。
- Trigger `trg_auto_lock_focal`:第一个非大咖加入者自动写入 `rooms.focal_user_id`,后续都是 audience。
- RLS:SELECT 只能看自己那行(防递归,见踩坑 §10.5);count 与成员列表通过 SECURITY DEFINER RPC 绕开。

### 4.5 `follow_requests` — 历史审核流(已废弃)
2026-05-12 起 instant-follow,表保留作历史 fallback。

### 4.6 `expert_agent_keys` — 大咖 agent 连接密钥
```sql
id, expert_id, name, key_hash (sha256), key_prefix
last_used_at, last_used_ip
expires_at, revoked_at, created_at
```

大咖在网页生成 `c2g-key_xxx` token,bridge 用它换 magiclink session。RPC:`generate_agent_key` / `list_agent_keys` / `revoke_agent_key`。

### 4.7 `model_usage` — 每次 LLM 调用计费
```sql
id, message_id → messages, room_id, expert_id, triggered_by, model
input_tokens, output_tokens
cache_creation_input_tokens, cache_read_input_tokens
cost_source ('online'|'local'), cost_usd
commission_pct, exchange_rate, user_charge_cny
created_at
```

- View `room_costs` 按 room_id 聚合 tokens / cost_usd / user_charge_cny。
- RLS + GRANT 屏蔽:小白通过 view 拿不到 `cost_usd` 列。
- INSERT 必须用 `returning="minimal"`,否则 RETURNING * 撞列权限报 42501(见踩坑 §10.11)。

### 4.8 `memories` — 记忆 ★ 写权限缺失,详见 §11
```sql
id, scope ('room'|'expert'|'user'), scope_id
content text, tags text[]
source_message_id → messages
created_at, updated_at
```

- SELECT policy `memories_read_scoped`:room scope 需是成员、expert/user scope 需是本人。
- **INSERT policy 没定义** → bridge 用 expert session 写入会被 RLS 拦截(默认 deny)。
- Phase A 设计上「只读 prefetch」,Phase B 由 bridge `sync_memory` 写入 —— 但写入路径目前 broken。

### 4.9 `bridge_state` — Agent 心跳与重启 ★
```sql
id text pk default 'singleton'    -- 单行表
last_seen           timestamptz
restart_requested_at timestamptz
pid int, hostname text
```

- bridge 每 ~5 秒 UPDATE `last_seen`;前端检测超 30 秒视为离线。
- RPC `request_bridge_restart()` 写 `restart_requested_at = now()`;bridge 检测到该时间 > 自己启动时间 → `sys.exit(1)` 让 launchd KeepAlive 拉起新进程。
- RPC `bridge_pong()` 兜底心跳上报。

### 4.10 RPC(公开 / SECURITY DEFINER)

| RPC | 用途 |
|---|---|
| `get_expert_follower_count(p_expert_id uuid) → int` | 落地页 anon 也可读 |
| `get_expert_followers(p_expert_id uuid) → table(...)` | follower 列表(authenticated) |
| `get_room_member_count(p_room_id uuid) → int` | 群人数(绕过 RLS 限制)|
| `get_room_members(p_room_id uuid) → table(uid, name, role, joined_at)` | 含三角色标签 expert/focal/audience |
| `join_room_by_token(token uuid) → uuid` | 邀请链接加入房间(备用) |
| `generate_agent_key(name) / list / revoke` | 大咖管理 connection_key |
| `agent_auth_exchange(key) → OTP` | bridge.py 启动用(Edge Function 包装) |
| `request_bridge_restart() → timestamptz` | 前端请求重启 bridge |
| `bridge_pong() → void` | bridge 心跳 |
| `rate_message(p_msg_id, p_val)` | 做题模式打 up/down/clear |
| `admin_clear_room_messages(p_room_id) → int` | admin 后台清空房间 |
| `reset_room(p_room_id)` | 重置房间(保留 owner,清成员 + 消息) |

### 4.11 关键 Trigger

- `trg_auto_add_expert_as_member`(room_members):建房时自动加 expert
- `trg_auto_lock_focal`(room_members):首位非大咖加入者锁为 focal_user_id
- `trg_relay_pass_to_private`(messages):AI 消息双钩 up 时往私聊频道写摘要
- `handle_new_user()`(auth.users):自动建 profiles 行
- `memories_updated_at`(memories):自动维护 updated_at

### 4.12 Storage Bucket
- `chat-uploads`(**private**,2026-05-13 安全加固改为非 public)
- 上传:任何登录用户。
- 读取:owner 或 admin;前端通过 `createSignedUrl` 短期签名访问。
- 文件名清洗:中文转 ASCII 否则 400。

---

## 5. 前端架构

### 5.1 全局样式 token(每页面 `<style>` 顶部)
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

角色色:小白黄 `#E5B85A` / 大咖紫 `--purple` / AI 绿 `--teal`。

### 5.2 `index.html` — 落地页
4 张 expert-card(grid 2x2),目前唯一启用:`fbb9ab4b-dc51-40f8-800e-e824ff6fb8c0` = 「森山大道 san」(fortune teller)。

- `followExpert(btn)` → insert room_members → 跳 `/chat.html?room=<id>`
- `loadFollowerCounts()` → `get_expert_follower_count` RPC
- `openFollowers(btn)` → `get_expert_followers` RPC + modal

### 5.3 `login.html` — 登录注册
Tab 切 Login / Register;Register 4 字段(邮箱 / 密码 / 昵称 / 角色);调 `sb.auth.signUp({ ..., options:{ data:{ display_name, role }}})`。
邮箱验证关掉(demo 阶段)。

### 5.4 `chat.html` — 调试室主界面

三栏布局:sidebar(220px,顶部胶囊 + ToDoList) + chat-panel(head + messages + input)。

#### 5.4.1 关键全局状态
```js
currentUser           // Supabase session.user
currentRole           // 'user' | 'expert'
currentDisplayName    // profiles.display_name
currentRoom           // 当前房(含 expert_id, ai_name, model, focal_user_id...)
currentChannel        // 'main' | 'expert_user'(默认 'main')
pendingAttachments
recognition           // SpeechRecognition
voiceTextBefore       // 录音前 input 已有文本(语音清残留 fix 关键)
unreadCounts          // { main: 0, expert_user: 0 }
```

#### 5.4.2 三角色识别
- 由 `get_room_members(room_id)` RPC 返回 `role: 'expert' | 'focal' | 'audience'`。
- 前端按角色渲染头像与气泡颜色;audience 仅可读,不可发 main 消息。

#### 5.4.3 Channel 切换
- `switchChannel('main' | 'expert_user')` 切换当前频道,重新 loadMessages。
- 顶部胶囊 tab 显示当前频道 + 未读徽章。
- 发消息:`channel: currentChannel`;但 typing 等元信号硬写 `expert_user`。

#### 5.4.4 ToDoList(forntend localStorage)
3 个父胶囊(我是谁/我从哪里来/我要去哪里),每父 3 个子 ☐。展开/勾选状态全部 localStorage:`c2g_todog_<group>` / `c2g_todo_<key>`。

#### 5.4.5 消息渲染 `appendMessage(msg)`
- 三色 bubble:`.msg-bubble.user|.expert|.ai`。
- AI 消息可能 markdown(`type='markdown'` 或 `looksLikeMarkdown()`),marked.js 渲染 + `.btn-pdf` 导出。
- AI 头像可点击编辑名字(只有大咖):`onclick="editAIName()"` → `rooms.ai_name`。
- 每条带:复制按钮(base64 绕 HTML 转义)、ts。
- AI 消息额外底栏 `.msg-rate-bar`:✓/✗ 评价 → 调 `rate_message(msgId, val)` RPC。

#### 5.4.6 发消息 `sendMessage()`
- 取 input.value,trim;等所有附件上传完才发。
- INSERT messages 表,role 由当前用户角色决定。
- **重要**:发送除清 input.value 外,还要清 `voiceTextBefore`(否则录音中发送会被 onresult 写回)。

#### 5.4.7 Realtime 订阅 `subscribeRoom(roomId)`
- INSERT 监听 → appendMessage + 去重(`data-msg-id`)。
- AI INSERT → 500ms 后 `loadRoomCost(roomId)` 刷成本徽章。
- presence sync → `renderPresence()` 渲染在线状态。

#### 5.4.8 Bridge 状态显示
- 每 N 秒查 `bridge_state.last_seen`,>30s 视为离线,图标变灰。
- 点击图标 → `request_bridge_restart()` RPC。

#### 5.4.9 轮询兜底
- `POLL_INTERVAL=5000`:5 秒一次补漏。

#### 5.4.10 语音输入(Web Speech API)
- `recognition.lang='zh-CN'`,`continuous=true`,`interimResults=true`。
- onresult 拼 `voiceTextBefore + finalText + interimText`。
- onend 自动重启录音(用户停顿不停录)。

#### 5.4.11 PDF 导出
- `exportPdf(targetId, filename)`:html2pdf 把 `.md-body` 导成 PDF,A4 边距固定。

#### 5.4.12 模型名展示
- `shortModelName(model)`:拆 provider/model,两段 cap,`·` 连接。
- `PROVIDER_LABELS` 大小写修正(openai → OpenAI, deepseek → DeepSeek)。
- `MODEL_CONTEXT_WINDOWS`:给 chat-head 的 token 进度条用。

### 5.5 `onboarding.html` — 大咖入住
1) 填昵称 → update profiles
2) 建房(industry 必选)→ insert rooms(trigger 加 room_members 自己)
3) 设置 ai_name(可选)→ update rooms.ai_name
4) 完成 → `/chat.html`

### 5.6 `admin.html` — 后台
房间观测 / 清空消息(`admin_clear_room_messages`)。需 `is_admin()` 返回 true(策略中硬绑定 admin uid)。

---

## 6. Agent 包 `chat2go-agent` ★

### 6.1 启动流程
```
start.sh / launchd 拉起
  ↓
load_dotenv() + load_credentials(~/.chat2go/credentials.yaml)
  ↓
acreate_client(SUPABASE_URL, SUPABASE_ANON_KEY)
  ↓ 优先 connection_key:POST /functions/v1/agent-auth/exchange → magiclink OTP
  ↓ 失败回退:email/password sign_in_with_password
  ↓
sb.auth.verify_otp({token_hash, type:'magiclink'}) → session(自动续命)
  ↓
load_skills() + load_soul()
  ↓
realtime.channel('messages') 订阅 INSERT
  +
每 5 秒轮询 messages(兜底)
  +
心跳 bridge_state.last_seen 每 ~5 秒
  +
监听 restart_requested_at,触发 sys.exit(1)
```

### 6.2 触发条件(`handle_message`)
对一条新 message:
1. `channel == 'expert_user'` → skip(AI 不参与私聊)
2. `room_id` 在本 bridge 的 rooms 列表
3. 消息内容里 `@真人名字` → skip(人类互@,AI 不抢话)
4. `processing` set 去重(防重入)

满足 → 进入 LLM 调用流程。

### 6.3 LLM 调用流程
```
1. attachments 分类:image 走 vision url、text/pdf/docx → 下载提取
2. _fetch_history(room_id, channel, limit=12) — 同 channel 历史
3. select_skill_by_industry(skills, room.industry) — 单 skill,按 industry 硬绑
4. prefetch_memory(room/expert/user 三 scope) — 拼 markdown 注入(★ 写入路径 broken,见 §11)
5. dspy_ask(content, user_id) — 调 localhost:7788 DSPy 服务(并行记忆)
6. resolve_brain_name(room) — 'builtin' | 'hermes' | 'auto'
7. brain.call(BrainContext{room, soul, skill, memory_ctx, history, current, image_urls, attachment_texts, model})
8. _normalize_markdown(result.text) — 压缩多余空行
9. messages.insert({room_id, user_id=expert_id, role='ai', channel, type, content})
10. sender_role=='expert' → asyncio.create_task(sync_memory(...))  ★ 协程引用没保,可能 GC
11. asyncio.create_task(dspy_extract(...))  ★ 同上
12. model_usage.insert(...) with returning='minimal'
```

### 6.4 Skill 系统(文件驱动 MVP)
- `chat2go_agent/skills/<industry>/SKILL.md`:YAML frontmatter + markdown body。
- frontmatter 字段:`name` / `display_name` / `version` / `triggers.industry` / `triggers.keywords`。
- 内置 6 个:`foreign-trade` / `fitness` / `real-estate` / `education` / `quant` / `medical`。
- 加载顺序:内置 → `~/.chat2go/skills/` 用户覆盖(同名优先用户)。
- 选择逻辑(`select_skill_by_industry`):**只匹配 `room.industry`**;frontmatter 的 `keywords` 字段**当前无效**(只是预留)。
- 与 AGENT_DESIGN §3.8 的差距:无 DB 表 / 无 room_skills 多对多 / 无 required_tools / 无 templates 数组 / 无 lessons 嵌套 / 无 is_public 公开标记。

### 6.5 SOUL.md(大咖人格)
- `~/.chat2go/SOUL.md`(可选)。
- prompt_builder 把它放在 system prompt 第 2 段(全局人格之后,skill 之前)。
- 模板见 `chat2go_agent/templates/SOUL.md.example`。

### 6.6 System Prompt 拼装(`prompt_builder.build_system_prompt`)
```
1. GLOBAL_PERSONA(全局人格 + 输出风格强约束:简短、无空行列表、紧凑 markdown)
2. 大咖 SOUL.md(若有)
3. 行业能力包 skill.body(若 industry 命中)
4. 房间级 rooms.system_prompt(若有)
5. <memory-context> memory_ctx(若有)
```

### 6.7 Brain 抽象(`brains/`)
- `builtin.py`:chat2go 自己拼 prompt + 调 LLM adapter。
- `hermes.py`:shell out 到本地 hermes 二进制(`/Users/dami2026/.local/bin/hermes`),复用 ~/.hermes 配置。
- `defaults.brain = 'auto'`:装了 hermes 用 hermes,否则 builtin。

### 6.8 Provider Adapter(`adapters/`)
统一接口 `base.py:dispatch_call(adapters, model, system, messages, max_tokens, timeout)`,model 格式 `provider/name`。
- `anthropic.py`:Anthropic 官方 SDK,支持 prompt caching、vision。
- `openai_compatible.py`:覆盖 OpenAI / DeepSeek / Qwen / Kimi / GLM / OpenRouter / Ollama 本地。
- `gemini.py`:Google Gemini 协议(不兼容 OpenAI)。

### 6.9 计费(`pricing.py`)
- `calculate_charge(model, usage, commission_pct, exchange_rate, local_prices)`:
  - online cost = usage × 厂商价目表
  - local cost = usage × local_prices(大咖自报硬件 + 电费摊销)
  - user_charge = cost_usd × (1 + commission_pct) × exchange_rate
- INSERT model_usage 时锁定 commission_pct / exchange_rate / user_charge_cny 快照。

### 6.10 DSPy 并行记忆(`dspy_client.py`)
- 外部服务 `http://localhost:7788`(独立进程,不在本仓库)。
- 接口:`/ask`(检索)/ `/remember`(手动写入)/ `/extract`(自动提取)/ `/health`。
- bridge 在 LLM 调用前 `dspy_ask` 拼到 memory_ctx,LLM 调用后 `dspy_extract` 异步写入。
- **与 Supabase `memories` 表并行**,双轨需明天讨论是否合并。

### 6.11 CLI(`__main__.py`)
- `chat2go-agent`(默认):启动 bridge 主循环
- `connect <key>`:写入 connection_key 到 ~/.chat2go/credentials.yaml
- `rooms`:列当前大咖所有房间
- `send <room> <content> [--role expert|ai|user] [--silent]`:以大咖身份发消息(脚本可用)
- `set-model <room_id> <model>`:设置房间默认模型
- `set-prompt <room_id> <prompt>`:设置房间 system_prompt
- `whoami`:显示当前身份

---

## 7. Edge Functions(Deno)

> 主链路走 chat2go-agent;Edge Functions 为备用 / 辅助。

### 7.1 `chat-ai`
- POST `/functions/v1/chat-ai`,Body: `{ room_id, messages }`
- Server-side Claude 调用,当 bridge 离线时降级。
- 行业 prompt 同 bridge 的 INDUSTRY_PROMPTS,**双写需保持同步**。

### 7.2 `agent-auth`
- POST `/functions/v1/agent-auth/exchange`,Body: `{ key }`
- 用 SERVICE_ROLE_KEY:sha256 hash key → 查 expert_agent_keys → 未过期 → admin.generateLink magiclink → 返回 `{ token_hash, email, expert_id }`。

---

## 8. 关键流程图

### 8.1 注册 → 落地
```
sb.auth.signUp({email, pw, options:{data:{role, display_name}}})
  ↓ trigger handle_new_user()
profiles INSERT
  ↓
role=expert → /onboarding.html
role=user   → /
```

### 8.2 Follow 大咖(instant)
```
landing page 点 ♥
  ↓
sb.from('rooms').select('id').eq('expert_id', expertId).limit(1)
  ↓
room_members.insert({room_id, user_id: me})
  ↓ trigger trg_auto_lock_focal(若是首位非大咖 → 写 focal_user_id)
跳 /chat.html?room=<roomId>
```

### 8.3 发消息 → AI 回复(main 频道)
```
input → sendMessage()
  ↓
messages.insert({room_id, user_id, role:'user'|'expert', channel:'main', content})
  ↓ Realtime broadcast → 三方前端 + bridge
[bridge] handle_message
  ↓ channel='expert_user' → skip
  ↓ 否则 → LLM 调用
messages.insert({role:'ai', user_id:expert_id, content, type, channel:'main'})
model_usage.insert(...)
sender_role=='expert' → asyncio.create_task(sync_memory(...))   ★ 见 §11
  ↓ Realtime broadcast → 三方
loadRoomCost(roomId)
```

### 8.4 大咖 ↔ 小白私聊(expert_user 频道)
```
切换 channel tab → currentChannel='expert_user'
  ↓
messages.insert({..., channel:'expert_user'})
  ↓ bridge handle_message → channel=='expert_user' → skip(无 AI)
```

### 8.5 做题模式 pass relay
```
任意成员点 ✓ → rate_message(msg_id, 'up')
  ↓ messages.ratings 更新
trigger trg_relay_pass_to_private:
  if 新 up 数 >=2 且 旧 up 数 <2:
    insert messages(channel='expert_user', content='✓✓ pass · <AI 消息摘要>')
```

### 8.6 Bridge 心跳 / 重启
```
bridge 每 5 秒 UPDATE bridge_state.last_seen
前端检测 last_seen 距 now>30s → 显示离线
前端点击 → request_bridge_restart() RPC → UPDATE restart_requested_at
bridge 监测 restart_requested_at > 启动时间 → sys.exit(1) → launchd KeepAlive 拉起新进程
```

---

## 9. 部署

### 9.1 前端(GitHub Pages)
- 仓库 `tototo1999/chat2go` main 分支,静态托管,无构建。push 后 30~90s 全球生效。
- CNAME → `chat2go.ai`,DNS 端配 A / CNAME。

### 9.2 Supabase
- Project URL / anon key 硬编码在前端 HTML 顶部 `<script>` + `chat2go-agent/config.py`。
- Migrations 用 `supabase db push` 或 SQL Editor。
- Edge Functions:`supabase functions deploy chat-ai` / `agent-auth`。
- Env:`ANTHROPIC_API_KEY` / `SUPABASE_SERVICE_ROLE_KEY` 等。
- 邮箱验证关掉(demo;上线前重开)。

### 9.3 chat2go-agent(本地 / launchd)
- 路径:`~/chat2go-agent/`。
- 一键启动:`./start.sh`(自动 wipe 旧进程 / 建 venv / 拉起)。
- launchd:`launchctl load ai.chat2go.bridge.plist`(KeepAlive,断了自重启)。
- 凭证:`~/.chat2go/credentials.yaml`(YAML)或仓库根 `.env`(优先 env)。
- 日志:`logs/bridge.log` + `logs/bridge.error.log`。
- 实测 Python 3.14 可跑,有 realtime websocket 超时偶发问题。

### 9.4 DSPy 服务(独立)
- `http://localhost:7788`,不在本两个仓库内。
- bridge 启动时检测健康度;失败则跳过 DSPy 增强但主链路不阻断。

---

## 10. 关键决策与踩坑

### 10.1 决策
| # | 决策 | 原因 |
|---|---|---|
| 1 | 自研 Agent,不依赖 Hermes | 控制力 + 不锁死生态(但保留 hermes brain 作可选) |
| 2 | Agent 独立成包 `chat2go-agent` | 与前端解耦,可独立升级 / 测试 / pyproject |
| 3 | 纯静态前端 | GitHub Pages 直发,JS 库本地化避 CDN |
| 4 | bridge 本地运行 | MVP 阶段大咖自己跑,launchd KeepAlive 自愈 |
| 5 | 多 provider 多 brain | 大咖自带 API key,平台不锁厂商 |
| 6 | 三角色 expert/focal/audience | focal 是计费主体,audience 旁观不计费 |
| 7 | channel 区分 main / expert_user | 大咖可与单个小白私聊不打扰公共流 |
| 8 | 做题模式双钩 pass | 用 ratings JSONB 而非独立表,trigger 处理 relay |
| 9 | AI 消息用大咖 user_id 写 | role='ai' 决定显示,user_id 字段服 RLS |
| 10 | follow 改 instant | 砍 approval 流减摩擦 |
| 11 | 邮箱验证关闭 | demo 阶段 |
| 12 | display_name 是私昵称 | 公开 persona 名硬编码 EXPERT_PERSONAS(未来抽 DB 列) |

### 10.2 踩坑
1. **Supabase JS UMD 注入全局 `supabase`** → 本地变量必须叫 `sb`。
2. **中文文件名 400** → 上传前 ASCII 清洗(保留扩展名)。
3. **Homebrew Python SSL** → certifi 修复,否则 websocket 连不上。
4. **CDN 国内不稳** → JS 依赖全部本地化到 `vendor/`。
5. **`room_members` RLS 递归** → SELECT 不能开 `using(true)`,会和 rooms 互相依赖;解法见 `20260511200000_fix_room_members_rls_recursion.sql`。SELECT 限自己那行,人数 / 列表通过 SECURITY DEFINER RPC 绕开。
6. **AI 消息显示「我」的 bug** → bridge 用大咖账号写 role='ai',前端必须 `role!=='ai' && isOwn` 判断。
7. **deleteRoom RLS 静默拦截** → DELETE 失败 RLS 不报错;必须 `.select()` 拿返回行数辨别。
8. **语音输入发送残留** → 录音中点发送,input 清了但 `voiceTextBefore` 缓存被 onresult 再写回。
9. **rooms.active 状态色 = mint pill = todo-head 一模一样** → 视觉混淆,待区分。
10. **Edge Function `dollar quote`** → SQL Editor 对 PL/pgSQL `$$..$$` 兼容差,instant follow 改回直白 RLS 而非 RPC。
11. **model_usage RETURNING * 报 42501** → cost_usd 列 GRANT 屏蔽,必须 `returning="minimal"`。
12. **bridge 当前默认模型偏离 doc** → HANDOFF 旧版说 sonnet,实际 credentials.yaml `defaults.model = openrouter/google/gemini-2.5-pro`。
13. **Python 3.14 + realtime websocket 偶发超时** → 已有重连退避,但 5 秒/10/20/40 退避期间消息可能错过(轮询兜底接住)。
14. **★ `asyncio.create_task` 协程被 GC** → bridge 多处 fire-and-forget 没保 task 引用,Python 3.14 弱引用模型下可能随时被回收(详见 §11.2)。
15. **★ 大咖纠正发到私聊频道** → 当前大咖大量在 expert_user 私聊里调教 AI,但 bridge 看到私聊就 skip,Learner / Lessons 系统的产品前提受冲击(详见 §11.4)。

---

## 11. 已知缺陷 ★(明天讨论清单)

### 11.1 memories 表 INSERT 权限缺失
- migration 只开了 SELECT,INSERT policy 注释掉了,后续没补。
- bridge 用 expert user session 写入会被 RLS 默认 deny。
- 修法:加 migration 开 `memories_insert_scoped` policy:
  ```sql
  create policy "memories_insert_scoped" on memories
    for insert to authenticated
    with check (
      (scope='user'   and scope_id=auth.uid()) or
      (scope='expert' and scope_id=auth.uid()) or
      (scope='room'   and exists (select 1 from room_members rm
                                    where rm.room_id=scope_id
                                      and rm.user_id=auth.uid()))
    );
  ```

### 11.2 `asyncio.create_task` 引用丢失被 GC
- bridge.py L331(sync_memory)/ L345(dspy_extract)/ L454(handle_message)/ L464(refresh_session)/ L561(poll)。
- Python 3.11+ 起 asyncio 对 task 持弱引用,fire-and-forget 协程可能在 await 点被 GC 静默取消。
- 证据:121 次大咖 main 消息处理,sync_memory 0 行 print(连失败 print 都没)。
- 修法:`ChatBridge` 加 `self._bg_tasks: set[asyncio.Task]`,封装 `_spawn(coro)` 持引用 + done callback discard。

### 11.3 双轨记忆系统
- Supabase `memories` 表(memory.py)+ DSPy 服务(dspy_client.py)并行。
- DSPy 是黑盒外部进程,数据所有权 / 隔离规则不清。
- 需明天拍板:保留双轨(主备 / 互补)还是合并(留一条)。

### 11.4 大咖纠正发在私聊频道 → Lessons 触发不到
- 实测最近 30 条事件:大咖 7 次在 expert_user / 3 次在 main。
- bridge L221 私聊直接 skip,sync_memory 触发条件 `sender_role=='expert'` 在 L330,前置已 return。
- 产品决策:
  - (a) 私聊里的大咖发言也喂 Learner(改 L221,把 sync_memory 提到 skip 之前)
  - (b) UI 引导大咖到 main 公开发言
  - (c) 给私聊加「✓ 沉淀」手动按钮,明示触发

### 11.5 skill 选择只看 industry,keywords 没用
- SKILL.md frontmatter 写了 `triggers.keywords` 但 `select_skill_by_industry` 不读。
- 一房只能命中一个 skill,无法细分(如「外贸合同」vs「外贸询盘」)。
- 计划:升级到 keyword 命中 / LLM Planner 路由 / 或拆细分 skill。

### 11.6 知识库(RAG)完全没做
- pgvector 未启用,kb_chunks 未建,embedding provider 未选。
- 设计已在 AGENT_DESIGN §3.3 写完,待 Phase 2 启动。

### 11.7 chat-ai Edge Function 与 bridge prompt 漂移
- 两套 INDUSTRY_PROMPTS 双写,容易脱节。
- 长期方案:Edge Function 走同一份 skills/ 目录(打包到 deno?或读 Supabase 表)。

### 11.8 公开 persona 名硬编码
- `EXPERT_PERSONAS` 写死在 chat.html;`profiles.display_name` 是私昵称。
- 待加 `profiles.public_name` 列。

---

## 12. 未完成与下一步

### Phase 1(MVP)—— 最优先
- [ ] 修 §11.1 + §11.2(memories 写入路径打通)
- [ ] 拍板 §11.3 + §11.4 记忆 / Lessons 产品形态
- [ ] PDF 真生成(服务端 weasyprint/reportlab)
- [ ] Multi-model Router 自动选 sonnet/haiku/local

### Phase 2 —— 壁垒
- [ ] 知识库 RAG(pgvector / kb_chunks / 切片 / 上传 UI)
- [ ] Skills 系统升级(细分 / keyword 路由 / DB 表 / 大咖私有上传)

### Phase 3 —— 体验
- [ ] 图片 OCR / Web 搜索(Tavily/SerpAPI/Bocha)/ 服务端语音转写(Whisper)

### Phase 4 —— 商业化
- [ ] Go 交付室(小白独立用 AI 的私人空间)
- [ ] 大咖分成结算
- [ ] 部署迁移(GH Pages → Vercel / Cloudflare Pages)

### UX 短期
- [ ] `EXPERT_PERSONAS` → `profiles.public_name`
- [ ] sidebar room-item active 视觉与 todo-head 区分
- [ ] 移动端 UI 对齐打磨
- [ ] 评价 → `message_ratings` 持久表(目前是 `messages.ratings` JSONB + localStorage UI)

---

## 13. 命名约定

- **JS**:camelCase;常量 SCREAMING_SNAKE_CASE
- **Python**:snake_case;包名 `chat2go_agent`,CLI `chat2go-agent`
- **DB**:snake_case;表名复数(rooms, messages, profiles)
- **角色**:DB `'user'` / `'expert'` ;UI 「小白」/「大咖」/「AI 助手」/「八字主 focal」/「路人 audience」
- **commit message**:中文,格式 `类型: 描述`(feat / fix / ui / refactor / chore / content / docs)
- **tag**:`vX.Y.Z-slug`
- **provider/model 格式**:`<provider>/<model_name>`(如 `anthropic/claude-sonnet-4-5`, `openrouter/google/gemini-2.5-pro`)

---

## 14. 重要文件入口(速查)

| 想做的事 | 改哪里 |
|---|---|
| 改首页 expert 卡片 | `chat2go/index.html` `.expert-card` |
| 加新 expert persona 名 | `chat2go/chat.html` `EXPERT_PERSONAS` |
| 改 AI 行业 prompt | `chat2go-agent/chat2go_agent/skills/<industry>/SKILL.md` + `chat2go/supabase/functions/chat-ai/index.ts`(双写) |
| 改默认 model | `~/.chat2go/credentials.yaml` `defaults.model`;房间级 → `rooms.model` |
| 加新行业 | `chat2go/chat.html` 建房模态框 + `chat2go-agent/chat2go_agent/skills/<新行业>/SKILL.md` |
| 加大咖私有 skill | `~/.chat2go/skills/<name>/SKILL.md` |
| 改大咖人格 | `~/.chat2go/SOUL.md` |
| 改样式 token | 每个 HTML 顶部 `:root { --teal: ... }` |
| 改 DB schema | 新 `supabase/migrations/YYYYMMDDHHMMSS_xxx.sql` |
| 改 RLS | 同上,注意 room_members 递归坑 + memories INSERT 缺漏 |
| 调对话气泡颜色 | `chat.html` `.msg-bubble.user/.expert/.ai` |
| 改 ToDoList 文字 | `chat.html` `.todo-section` HTML 块 + `data-todo` key |
| 加 LLM 计费规则 | `chat2go-agent/chat2go_agent/pricing.py` |
| 加 provider | `chat2go-agent/chat2go_agent/adapters/<provider>.py` + credentials.yaml |
| 加 brain | `chat2go-agent/chat2go_agent/brains/<brain>.py` |

---

## 15. 重建 checklist

按此顺序可从零搭起:

### Supabase 侧
1. 起 Supabase project,跑全部 `chat2go/supabase/migrations/*.sql`。
2. Dashboard → Auth → Email confirm = off(demo 阶段)。
3. Storage 建 bucket `chat-uploads`(private,见 §4.12)。
4. `supabase functions deploy {chat-ai, agent-auth}`;配 env。

### 前端
5. `chat2go/{index,login,chat,onboarding,admin}.html` 顶部填 SUPABASE_URL / SUPABASE_ANON_KEY。
6. GitHub Pages 启用,CNAME → 域名。
7. 注册 expert 账号,跑 onboarding 建房,记 expert_id。
8. `EXPERT_PERSONAS` 替换 expert_id 与 persona 名。

### Agent 侧
9. `git clone chat2go-agent` 到 `~/chat2go-agent`(独立仓库)。
10. 在大咖账号下 `generate_agent_key('local')` 拿到 `c2g-key_xxx`。
11. `cd ~/chat2go-agent && ./start.sh`,首次会跑 `chat2go-agent connect <key>`。
12. 配 `~/.chat2go/credentials.yaml` 至少一个 provider 的 API key。
13. (可选) 起 DSPy 服务 `localhost:7788`。
14. (可选) `launchctl load ai.chat2go.bridge.plist` 设开机自启。

### 验证
15. 注册 user 账号,落地页 follow 大咖,进调试室聊一句,看 AI 回应。
16. 切到 expert_user 频道,大咖私聊小白,确认 AI 不参与。
17. 任意成员对 AI 消息双钩 up,检查 expert_user 频道出现 ✓✓ pass 摘要。
18. 检查 `bridge_state.last_seen` 持续刷新。

---

## 16. 文档维护

- 每次重大改动同步更新对应章节。
- 添加 migration 后,更新 §4 + §15。
- 添加 provider/brain/skill 后,更新 §6 + §14。
- 发现新踩坑加 §10.2;发现新缺陷加 §11(并标 ★)。
- 当前文档主轴反映 **2026-05-14 双仓库 + 多 provider + 三角色 + 做题模式** 状态。

---

> 维护者:项目 owner / 你(vibe-coding agent)。
> 上次大改:2026-05-14 重写,主要变化是把 chat2go-agent 包独立结构、三角色 / channel / 做题模式 / bridge 心跳 / focal 等新增能力以及 memory 写入隐患 全部归位。
